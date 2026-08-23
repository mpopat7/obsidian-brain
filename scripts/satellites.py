#!/usr/bin/env python3
"""Find satellite nodes — notes with no path to the main graph component.

A **satellite** is a note, or a small group of notes linked only to each other,
that has no route into the vault's main connected component. In Obsidian's graph
view they read as little clusters orbiting the brain at a distance, which is where
the name comes from.

Satellites matter because the vault's retrieval story is the graph: a note nothing
reaches is a note that will not surface. The vault's rule (`AGENTS.md`) has always
been "no islands", but that rule was enforced only by the manual triage step, and
nothing measured it. Three separate cleanups repaired the population by hand and
each time it grew straight back, because filing a capture and linking it were two
different steps and only one of them was automatic.

Some sectors are satellites by design and are not defects:

  99-archive     — retired material, deliberately cut loose
  04-templates   — scaffolding, never part of the knowledge graph
  docs, attachment — non-note assets
  _-prefixed     — folder "about" notes
  00-inbox       — pre-triage staging; transient by definition, reported separately

Everything else that floats free is a real satellite and a bug.

Read-only — never writes to the vault.

    python3 satellites.py                 # report
    python3 satellites.py --strict        # count the inbox as satellites too
    python3 satellites.py --quiet         # summary only
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))

#: Sectors whose notes are allowed to sit off the graph.
EXEMPT_SECTORS = ("99-archive", "04-templates", "docs", "attachment", ".obsidian")
#: Staging area: transient, reported but not failed unless --strict.
STAGING_SECTORS = ("00-inbox",)

LINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_RE = re.compile(r"`[^`\n]*`")


def load_notes(vault=VAULT):
    """stem -> {rel, sector, links}. Code spans are stripped: Obsidian draws no
    edge from a wikilink inside backticks, which is exactly how captures quote
    shell tests and note names without creating ghost nodes."""
    notes = {}
    for path in sorted(Path(vault).rglob("*.md")):
        rel = path.relative_to(vault)
        if rel.parts[0] == ".obsidian":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        body = INLINE_RE.sub(" ", FENCE_RE.sub(" ", text))
        links = {l.split("|")[0].split("#")[0].strip() for l in LINK_RE.findall(body)}
        notes[path.stem] = {
            "rel": str(rel),
            "sector": rel.parts[0],
            "name": path.name,
            "links": {l for l in links if l},
        }
    return notes


def components(notes):
    """Undirected connected components over resolved links, largest first."""
    adj = defaultdict(set)
    for stem, info in notes.items():
        adj[stem]
        for target in info["links"]:
            if target in notes:
                adj[stem].add(target)
                adj[target].add(stem)

    seen, out = set(), []
    for start in sorted(adj):
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            node = stack.pop()
            group.append(node)
            for neighbour in adj[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        out.append(sorted(group))
    out.sort(key=len, reverse=True)
    return out, adj


def is_exempt(info, strict=False):
    if info["sector"] in EXEMPT_SECTORS:
        return True
    if info["name"].startswith("_"):
        return True
    if not strict and info["sector"] in STAGING_SECTORS:
        return True
    return False


def find(vault=VAULT, strict=False):
    """Return (notes, clusters, offenders).

    clusters   — every component outside the main one, largest first
    offenders  — the notes in them that are not exempt: the real satellites
    """
    notes = load_notes(vault)
    if not notes:
        return notes, [], []
    comps, _ = components(notes)
    clusters = comps[1:]
    offenders = [stem for cluster in clusters for stem in cluster
                 if not is_exempt(notes[stem], strict)]
    return notes, clusters, offenders


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="treat 00-inbox notes as satellites too")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    args = ap.parse_args()

    notes, clusters, offenders = find(strict=args.strict)
    main_size = len(notes) - sum(len(c) for c in clusters)

    print("notes: %d   main component: %d (%.1f%%)"
          % (len(notes), main_size, 100 * main_size / max(len(notes), 1)))
    print("off the main component: %d notes in %d clusters"
          % (sum(len(c) for c in clusters), len(clusters)))
    print("satellites (excluding %s): %d"
          % ("exempt sectors" if not args.strict else "exempt sectors, inbox counted",
             len(offenders)))

    if not args.quiet and offenders:
        multi = [c for c in clusters if len(c) > 1 and
                 any(s in offenders for s in c)]
        if multi:
            print("\nmulti-note satellite clusters:")
            for cluster in multi:
                sectors = Counter(notes[s]["sector"] for s in cluster)
                print("  [%d] %s" % (len(cluster), dict(sectors)))
                for stem in cluster:
                    print("      %s" % notes[stem]["rel"])
        lone = [s for s in offenders
                if len([c for c in clusters if s in c][0]) == 1]
        if lone:
            print("\nlone satellites:")
            by_sector = defaultdict(list)
            for stem in lone:
                by_sector[notes[stem]["sector"]].append(stem)
            for sector in sorted(by_sector):
                print("  %s (%d)" % (sector, len(by_sector[sector])))
                for stem in sorted(by_sector[sector]):
                    print("      %s" % notes[stem]["rel"])

    if not args.strict:
        staged = [s for c in clusters for s in c
                  if notes[s]["sector"] in STAGING_SECTORS
                  and not notes[s]["name"].startswith("_")]
        if staged:
            print("\n%d unlinked notes in 00-inbox (transient, awaiting triage)"
                  % len(staged))

    sys.exit(1 if offenders else 0)


if __name__ == "__main__":
    main()
