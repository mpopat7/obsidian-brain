#!/usr/bin/env python3
"""Canonicalize the tag vocabulary across conversation notes.

The tag space is badly fragmented (e.g. protein / protein-estimate /
protein-estimation / protein-content are four tags for one idea). This embeds
every distinct tag, unions tags whose cosine similarity is >= THRESHOLD (plus
trivial plural/whitespace normalization), and rewrites each note's `tags:` line
to use the most-frequent member of each cluster as the canonical tag.

Dry-run by default: prints the biggest merges and before/after vocab size.
Pass --apply to rewrite frontmatter.

    python3 tag_canon.py                      # preview merges
    python3 tag_canon.py --threshold 0.88     # looser/tighter clustering
    python3 tag_canon.py --apply
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from relate_notes import (CONVERSATIONS, EMBED_MODEL, CACHE, OLLAMA_HOST,
                          parse_note)
import urllib.request


def collect_tags(root):
    counts = Counter()
    note_tags = {}
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        fm, _ = parse_note(path)
        raw = fm.get("tags", "")
        tags = [t.strip() for t in raw.strip("[]").split(",") if t.strip()]
        note_tags[path] = tags
        counts.update(tags)
    return counts, note_tags


def normalize(tag):
    """Trivial pre-merge: collapse whitespace/underscores, depluralize simply."""
    t = re.sub(r"[\s_]+", "-", tag.lower()).strip("-")
    if len(t) > 4 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        t = t[:-1]
    return t


def embed_batch(texts):
    body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["embeddings"]


def embed_tags(tags):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    key = lambda t: hashlib.sha1(("tag\n" + EMBED_MODEL + "\n" + t).encode()).hexdigest()
    missing = [t for t in tags if key(t) not in cache]
    for i in range(0, len(missing), 100):
        chunk = missing[i:i + 100]
        for t, vec in zip(chunk, embed_batch(chunk)):
            cache[key(t)] = vec
        print(f"  embedded {min(i+100, len(missing))}/{len(missing)} new tags",
              file=sys.stderr)
    if missing:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return np.array([cache[key(t)] for t in tags], dtype=np.float64)


class Union:
    def __init__(self, items):
        self.p = {x: x for x in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build_map(counts, threshold):
    tags = list(counts)
    uf = Union(tags)
    # trivial normalization merges (plurals / underscores)
    norm_groups = {}
    for t in tags:
        norm_groups.setdefault(normalize(t), []).append(t)
    for group in norm_groups.values():
        for other in group[1:]:
            uf.union(group[0], other)
    # semantic merges
    vecs = embed_tags(tags)
    mag = np.linalg.norm(vecs, axis=1, keepdims=True)
    norm = np.divide(vecs, mag, out=np.zeros_like(vecs), where=mag > 0)
    with np.errstate(all="ignore"):
        sims = np.clip(norm @ norm.T, -1.0, 1.0)
    n = len(tags)
    for i in range(n):
        for j in np.where(sims[i] >= threshold)[0]:
            if j > i:
                uf.union(tags[i], tags[j])
    # canonical = most frequent in cluster (tie -> shortest -> alpha)
    clusters = {}
    for t in tags:
        clusters.setdefault(uf.find(t), []).append(t)
    mapping = {}
    merges = []
    for members in clusters.values():
        canon = max(members, key=lambda t: (counts[t], -len(t), t))
        canon = min((m for m in members if counts[m] == counts[canon]),
                    key=lambda t: (len(t), t))
        for m in members:
            mapping[m] = canon
        if len(members) > 1:
            merges.append((canon, sorted(members, key=lambda t: -counts[t])))
    return mapping, merges


def remap_line(raw, mapping):
    tags = [t.strip() for t in raw.strip().strip("[]").split(",") if t.strip()]
    seen, out = set(), []
    for t in tags:
        c = mapping.get(t, t)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return "[" + ", ".join(out) + "]"


def run(root, threshold, apply):
    counts, note_tags = collect_tags(root)
    print(f"{len(counts)} distinct tags across {len(note_tags)} notes",
          file=sys.stderr)
    mapping, merges = build_map(counts, threshold)
    canon_set = {mapping[t] for t in counts}
    print(f"\n{len(counts)} -> {len(canon_set)} canonical tags "
          f"(threshold={threshold})")
    merges.sort(key=lambda m: -sum(counts[t] for t in m[1]))
    print("\nTop 30 merges (canonical <- members[count]):")
    for canon, members in merges[:30]:
        shown = ", ".join(f"{m}[{counts[m]}]" for m in members if m != canon)
        print(f"  {canon}[{counts[canon]}] <- {shown}")

    if not apply:
        print(f"\n{len(merges)} clusters merge >=2 tags. Dry run — "
              f"re-run with --apply to rewrite frontmatter.")
        return

    changed = 0
    for path, tags in note_tags.items():
        if not tags:
            continue
        text = path.read_text()
        new = re.sub(r"^tags:.*$",
                     lambda m: "tags: " + remap_line(m.group(0).split(":", 1)[1], mapping),
                     text, count=1, flags=re.MULTILINE)
        if new != text:
            path.write_text(new)
            changed += 1
    print(f"\nRewrote tags in {changed} notes.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, default=0.88,
                    help="min cosine similarity to merge two tags")
    ap.add_argument("--source", help="limit to 01-conversations/<source>/")
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()
    root = CONVERSATIONS / args.source if args.source else CONVERSATIONS
    run(root, args.threshold, args.apply)


if __name__ == "__main__":
    main()
