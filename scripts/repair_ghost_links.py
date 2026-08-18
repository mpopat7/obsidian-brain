#!/usr/bin/env python3
"""Neutralize ghost wikilinks that capture pipelines copied out of transcripts.

A captured conversation quotes whatever the session contained: shell tests
(``[[ -n "$x" ]]``), POSIX classes (``[[:space:]]``), CSV rows, and references
to ``~/dev/memory`` notes that are not vault notes. Obsidian reads every one of
those as a wikilink and renders an unresolved "ghost" node, so a capture whose
only links are quoted noise shows up in the graph as a small island cluster.

This wraps the offending link in backticks. Inline code draws no edge, so the
ghost disappears while the text stays exactly as the transcript had it.

Only links that do NOT resolve to a real note are touched, and only in
conversation folders — curated notes own their links and are left alone.

    python3 repair_ghost_links.py --dry-run
    python3 repair_ghost_links.py
"""

import argparse
import os
import re
from collections import defaultdict

VAULT = os.path.expanduser(os.environ.get("VAULT", "~/obsidian-brain"))
# Captures quote prose and code verbatim; curated notes are authored by hand and
# their broken links are real graph intent, not transcript noise.
CAPTURE_ROOTS = ("01-conversations",)
SKIP_DIRS = {".obsidian", "attachment", "docs", "04-templates"}

FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
# Matches what Obsidian actually links: [[target]] closed on one line, with no
# bracket inside the target. A bare "[[" with no closer (a truncated tool result)
# renders as literal text and is not a ghost node, so it must not match.
LINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
INLINE_RE = re.compile(r"`[^`]*`")


def note_stem(name):
    """Strip only a .md extension.

    os.path.splitext is wrong here: vault names are dotted
    (2026.06.30-02.18.40-claude-ai-...), so it would cut at the last dot and
    invent a broken target out of a link that resolves fine.
    """
    return name[:-3] if name.endswith(".md") else name


def index_notes(vault):
    notes, paths = {}, []
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, f), vault)
                paths.append(rel)
                notes.setdefault(note_stem(f), rel)
    return notes, paths


def repair_text(text, resolves):
    """Backtick-wrap every unresolved wikilink outside code spans and fences.

    Returns (new_text, targets_wrapped).
    """
    out, wrapped, fenced = [], [], False
    for line in text.split("\n"):
        if FENCE_RE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced or "[[" not in line:
            out.append(line)
            continue

        # Blank out inline-code spans so links already inside them are left be.
        masked = INLINE_RE.sub(lambda m: " " * len(m.group(0)), line)
        pieces, cursor = [], 0
        for m in LINK_RE.finditer(line):
            target = m.group(1).split("|")[0].split("#")[0].strip()
            if resolves(target):
                continue
            if masked[m.start():m.end()].strip() == "":
                continue  # already inert inside inline code
            pieces.append((m.start(), m.end(), m.group(0)))
            wrapped.append(target)

        if not pieces:
            out.append(line)
            continue

        rebuilt = []
        for start, end, raw in pieces:
            if start < cursor:      # overlapping match from a nested [[ — skip
                continue
            rebuilt.append(line[cursor:start])
            rebuilt.append(f"`{raw}`")
            cursor = end
        rebuilt.append(line[cursor:])
        out.append("".join(rebuilt))
    return "\n".join(out), wrapped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--vault", default=VAULT)
    args = ap.parse_args()

    vault = os.path.expanduser(args.vault)
    notes, paths = index_notes(vault)

    def resolves(target):
        return note_stem(os.path.basename(target.strip())) in notes

    changed, total, by_target = 0, 0, defaultdict(int)
    for rel in sorted(paths):
        if not rel.startswith(CAPTURE_ROOTS):
            continue
        full = os.path.join(vault, rel)
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        new, wrapped = repair_text(text, resolves)
        if not wrapped:
            continue
        changed += 1
        total += len(wrapped)
        for t in wrapped:
            by_target[t] += 1
        if not args.dry_run:
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(new)

    verb = "would wrap" if args.dry_run else "wrapped"
    print(f"{verb} {total} ghost link(s) across {changed} capture note(s)")
    print(f"distinct ghost targets: {len(by_target)}")
    for t, c in sorted(by_target.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c:4d}  [[{t[:70]}]]")


if __name__ == "__main__":
    main()
