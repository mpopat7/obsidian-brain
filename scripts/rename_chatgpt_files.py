#!/usr/bin/env python3
"""One-off: rename ChatGPT notes from YYYYMMDD-HHMMSS-slug.md to YYYY-MM-DD-slug.md.

Collapses repeated dashes and resolves collisions with -2, -3 suffixes.
Dry run by default; pass --apply to actually rename.
"""

import re
import sys
from pathlib import Path

FOLDER = Path.home() / "obsidian-brain" / "01-conversations" / "chatgpt"
PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})-\d{6}-(.+)\.md$")


def plan():
    taken = set()
    moves = []
    for path in sorted(FOLDER.glob("*.md")):
        m = PATTERN.match(path.name)
        if not m:
            continue
        y, mo, d, slug = m.groups()
        slug = re.sub(r"-+", "-", slug).strip("-")
        stem = f"{y}-{mo}-{d}-{slug}"
        new = f"{stem}.md"
        n = 2
        while new in taken or (new != path.name and (FOLDER / new).exists()):
            new = f"{stem}-{n}.md"
            n += 1
        taken.add(new)
        if new != path.name:
            moves.append((path, FOLDER / new))
    return moves


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    moves = plan()
    for old, new in moves[:8]:
        print(f"{old.name}  ->  {new.name}")
    print(f"... {len(moves)} files to rename." if len(moves) > 8 else "")
    if apply:
        for old, new in moves:
            old.rename(new)
        print(f"APPLIED — {len(moves)} renamed.")
    else:
        print(f"DRY RUN — {len(moves)} would be renamed. Re-run with --apply.")
