#!/usr/bin/env python3
"""Add semantic ## Related backlinks between conversation notes.

Embeds each note (title+summary+tags) via an Ollama embedding model, finds each
note's top-K nearest neighbors by cosine similarity, and writes a `## Related`
section linking them. Turns the hub-and-spoke graph into a peer web.

Dry-run by default: prints proposed links and a similarity-score histogram, and
writes nothing. Pass --apply to write. The `## Related` block is regenerated on
each run, so re-running is idempotent.

    python3 relate_notes.py                 # dry run over 01-conversations/
    python3 relate_notes.py --apply         # write the ## Related sections
    python3 relate_notes.py --source chatgpt --k 5 --floor 0.62 --apply
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np

VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))
CONVERSATIONS = VAULT / "01-conversations"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://gx10-909f:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "mxbai-embed-large")
CACHE = Path.home() / ".cache" / "obsidian-brain-embeddings.json"

RELATED_HEADER = "## Related"


def parse_note(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm, m.group(2)


def embed_text(fm):
    """Concise semantic signature: title + summary + tags (not the noisy body)."""
    parts = [fm.get("title", ""), fm.get("summary", ""),
             fm.get("tags", "").strip("[]")]
    return "\n".join(p for p in parts if p).strip()


def load_notes(root):
    notes = []
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        fm, body = parse_note(path)
        sig = embed_text(fm)
        if not sig:
            continue
        notes.append({"path": path, "stem": path.stem,
                      "title": fm.get("title", "").strip() or path.stem,
                      "sig": sig})
    return notes


def ollama_embed(text):
    body = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["embeddings"][0] if "embeddings" in data else data["embedding"]


def embed_all(notes):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    vectors, misses = [], 0
    for i, note in enumerate(notes):
        key = hashlib.sha1((EMBED_MODEL + "\n" + note["sig"]).encode()).hexdigest()
        vec = cache.get(key)
        if vec is None:
            vec = ollama_embed(note["sig"])
            cache[key] = vec
            misses += 1
            if misses % 50 == 0:
                print(f"  embedded {misses} new (at note {i+1}/{len(notes)})...",
                      file=sys.stderr)
        vectors.append(vec)
    if misses:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
        print(f"  cached {misses} new embeddings", file=sys.stderr)
    return np.array(vectors, dtype=np.float32)


def neighbors(notes, vectors, k, floor):
    vectors = np.nan_to_num(vectors.astype(np.float64), posinf=0.0, neginf=0.0)
    mag = np.linalg.norm(vectors, axis=1, keepdims=True)
    norm = np.divide(vectors, mag, out=np.zeros_like(vectors), where=mag > 0)
    with np.errstate(all="ignore"):
        sims = np.clip(norm @ norm.T, -1.0, 1.0)
    np.fill_diagonal(sims, -1.0)
    out = {}
    for i in range(len(notes)):
        order = np.argsort(sims[i])[::-1][:k]
        out[i] = [(j, float(sims[i, j])) for j in order if sims[i, j] >= floor]
    return out


def strip_related(body):
    pat = re.compile(r"\n*" + re.escape(RELATED_HEADER) + r"\n.*?(?=\n## |\Z)",
                     re.DOTALL)
    return pat.sub("", body).rstrip()


def render_related(notes, picks):
    lines = [RELATED_HEADER]
    for j, score in picks:
        n = notes[j]
        lines.append(f"- [[{n['stem']}|{n['title']}]]  <!-- {score:.2f} -->")
    return "\n".join(lines)


def histogram(nbrs):
    scores = [s for picks in nbrs.values() for _, s in picks]
    if not scores:
        return "  (no links above floor)"
    bins = {}
    for s in scores:
        bins.setdefault(round(s, 1), 0)
        bins[round(s, 1)] += 1
    rows = [f"    {b:.1f}-{b+0.1:.1f}: {'#' * (c // 20)} {c}"
            for b, c in sorted(bins.items())]
    return "\n".join(rows)


def relate(root, k, floor, apply):
    notes = load_notes(root)
    print(f"Loaded {len(notes)} notes from {root}", file=sys.stderr)
    vectors = embed_all(notes)
    nbrs = neighbors(notes, vectors, k, floor)

    linked = sum(1 for picks in nbrs.values() if picks)
    print(f"\n{linked}/{len(notes)} notes get >=1 related link "
          f"(k={k}, floor={floor})")
    print("Similarity histogram of chosen links:")
    print(histogram(nbrs))

    if not apply:
        print("\n--- DRY RUN sample (first 8 notes with links) ---")
        shown = 0
        for i, picks in nbrs.items():
            if not picks:
                continue
            print(f"\n{notes[i]['title']}")
            for j, s in picks:
                print(f"   -> {notes[j]['title']}  ({s:.2f})")
            shown += 1
            if shown >= 8:
                break
        print("\nDry run only. Re-run with --apply to write.")
        return

    written = 0
    for i, picks in nbrs.items():
        if not picks:
            continue
        fm_text, body = _split(notes[i]["path"])
        new_body = strip_related(body)
        new_body += "\n\n" + render_related(notes, picks) + "\n"
        notes[i]["path"].write_text(fm_text + new_body)
        written += 1
    print(f"\nWrote ## Related into {written} notes.")


def _split(path):
    text = path.read_text()
    m = re.match(r"^(---\n.*?\n---\n?)(.*)$", text, re.DOTALL)
    return (m.group(1), m.group(2)) if m else ("", text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", help="limit to 01-conversations/<source>/ "
                    "(e.g. chatgpt); default = all conversations")
    ap.add_argument("--k", type=int, default=5, help="max related links per note")
    ap.add_argument("--floor", type=float, default=0.62,
                    help="min cosine similarity to link")
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()
    root = CONVERSATIONS / args.source if args.source else CONVERSATIONS
    if not root.exists():
        sys.exit(f"No such folder: {root}")
    relate(root, args.k, args.floor, args.apply)


if __name__ == "__main__":
    main()
