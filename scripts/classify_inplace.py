#!/usr/bin/env python3
"""Classify already-filed conversation notes in place (summary/tags) without moving them.

Reuses analyze_inbox's logic. Resumable: skips notes that already have a non-empty summary.
Usage: python3 classify_inplace.py [subfolder]   # default: chatgpt
"""

import os
import sys
from pathlib import Path

from analyze_inbox import VAULT, CONVERSATIONS, parse_note, analyze, rebuild


def main(subfolder):
    folder = CONVERSATIONS / subfolder
    notes = sorted(p for p in folder.glob("*.md") if not p.name.startswith("_"))
    total = len(notes)
    done = skipped = failed = 0
    for i, path in enumerate(notes, 1):
        fm, body = parse_note(path)
        if fm.get("summary", "").strip().strip('"'):
            skipped += 1
            continue
        if not body.strip():
            skipped += 1
            continue
        try:
            result = analyze(body)
            if not result:
                raise ValueError("no JSON")
        except Exception as e:
            failed += 1
            print(f"[{i}/{total}] FAILED {path.name}: {e}", flush=True)
            continue
        path.write_text(rebuild(fm, result, body))
        done += 1
        if done % 25 == 0:
            print(f"[{i}/{total}] classified={done} skipped={skipped} failed={failed}", flush=True)
    print(f"DONE — classified={done} skipped={skipped} failed={failed} of {total}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "chatgpt")
