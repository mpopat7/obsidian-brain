#!/usr/bin/env python3
"""Find topic clusters among conversations that have no hub note covering them.

Builds the conversation-to-conversation link graph (ignoring the big life-area
hubs, which otherwise pull everything into one blob), runs label propagation to
find communities, then reports each community with its dominant tags and the
hubs its members already point at. A large community whose members share no
02-knowledge / 03-projects hub is a knowledge note that should exist.

Read-only — never writes to the vault.

    python3 cluster_graph.py              # top 15 uncovered clusters
    python3 cluster_graph.py --min-size 5 --all
"""

import argparse
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path.home() / "obsidian-brain"
SKIP_DIRS = {"99-archive", "04-templates", "attachment", "docs", ".obsidian"}
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def load():
    notes = {}
    for path in VAULT.rglob("*.md"):
        rel = path.relative_to(VAULT)
        if rel.parts[0] in SKIP_DIRS or path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        fm = FM_RE.match(text)
        tags = []
        if fm:
            m = re.search(r"tags:\s*\[(.*?)\]", fm.group(1), re.S)
            tags = [t.strip() for t in m.group(1).split(",") if t.strip()] if m else []
        links = {l.split("|")[0].split("#")[0].strip() for l in LINK_RE.findall(text)}
        notes[path.stem] = {
            "sector": rel.parts[0],
            "tags": tags,
            "links": links,
            "title": path.stem,
        }
    return notes


def label_propagation(adj, seed=0, rounds=30):
    rng = random.Random(seed)
    label = {n: n for n in adj}
    nodes = sorted(adj)
    for _ in range(rounds):
        rng.shuffle(nodes)
        changed = 0
        for n in nodes:
            if not adj[n]:
                continue
            counts = Counter(label[m] for m in adj[n])
            best = max(counts.values())
            # deterministic tie-break so runs are reproducible
            winner = min(l for l, c in counts.items() if c == best)
            if label[n] != winner:
                label[n] = winner
                changed += 1
        if not changed:
            break
    comms = defaultdict(list)
    for n, l in label.items():
        comms[l].append(n)
    return sorted(comms.values(), key=len, reverse=True)


def split_large(adj, comms, max_size, depth=0):
    """Label propagation under-partitions: a few hub-adjacent conversations fuse
    unrelated topics into one blob. Re-cluster anything oversized on its own
    induced subgraph, where those bridging links no longer dominate."""
    out = []
    for c in comms:
        if len(c) <= max_size or depth >= 4:
            out.append(c)
            continue
        members = set(c)
        sub = {n: adj[n] & members for n in c}
        parts = label_propagation(sub, seed=depth + 1)
        if len(parts) == 1:                   # cannot split further
            out.append(c)
        else:
            out.extend(split_large(sub, parts, max_size, depth + 1))
    return sorted(out, key=len, reverse=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-size", type=int, default=40,
                    help="re-cluster communities larger than this")
    ap.add_argument("--min-size", type=int, default=4)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--all", action="store_true", help="include covered clusters")
    args = ap.parse_args()

    notes = load()
    convs = {n for n, d in notes.items() if d["sector"] == "01-conversations"}
    hubs = {n for n, d in notes.items()
            if d["sector"] in ("02-knowledge", "03-projects", "05-context")}

    adj = defaultdict(set)
    for n in convs:
        for l in notes[n]["links"]:
            if l in convs:                    # peer edges only — hubs excluded
                adj[n].add(l)
                adj[l].add(n)
    for n in convs:
        adj.setdefault(n, set())

    comms = [c for c in split_large(adj, label_propagation(adj), args.max_size)
             if len(c) >= args.min_size]
    print(f"{len(convs)} conversations, {sum(len(v) for v in adj.values())//2} peer edges")
    print(f"{len(comms)} communities of size >= {args.min_size}\n")

    rows = []
    for c in comms:
        tags = Counter(t for n in c for t in notes[n]["tags"]
                       if not t.startswith(("subject/", "topic/")))
        hub_hits = Counter(l for n in c for l in notes[n]["links"] if l in hubs)
        # "covered" = a hub that most of the cluster already points at
        covered = [h for h, k in hub_hits.items() if k >= max(3, len(c) * 0.5)]
        rows.append((c, tags, hub_hits, covered))

    shown = 0
    for c, tags, hub_hits, covered in rows:
        if covered and not args.all:
            continue
        shown += 1
        if shown > args.top:
            break
        print(f"── {len(c)} conversations " + ("─" * 40))
        print(f"   tags : {', '.join(f'{t}({k})' for t, k in tags.most_common(8)) or '—'}")
        print(f"   hubs : {', '.join(f'{h}({k})' for h, k in hub_hits.most_common(4)) or 'NONE'}")
        print(f"   {'COVERED by ' + ', '.join(covered) if covered else '>> NO HUB COVERS THIS'}")
        for n in sorted(c)[:4]:
            print(f"     · {n}")
        if len(c) > 4:
            print(f"     · … {len(c) - 4} more")
        print()

    if not args.all:
        print(f"({len(rows) - shown} clusters already covered by a hub — --all to see them)")


if __name__ == "__main__":
    main()
