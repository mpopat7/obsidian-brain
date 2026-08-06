#!/usr/bin/env python3
"""Attach a cluster of conversations to a hub note via the #subject/* or #topic/* overlay.

Adds the namespaced tag to each note's frontmatter and appends the standard
footer, per the vault's AGENTS.md convention. Idempotent — notes already
carrying the tag are skipped. Note names come from stdin, one per line (no .md).

    printf '%s\\n' note-a note-b | python3 add_overlay_footer.py music-production
    printf '%s\\n' note-a note-b | python3 add_overlay_footer.py research-writing --subject
"""

import argparse
import re
import sys
from pathlib import Path

CONVERSATIONS = Path.home() / "obsidian-brain" / "01-conversations"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("hub", help="hub note to link (e.g. music-production)")
    ap.add_argument("--slug", help="tag slug if it differs from the hub name")
    ap.add_argument("--subject", action="store_true",
                    help="use the subject/* overlay instead of topic/*")
    args = ap.parse_args()

    kind = "Subject" if args.subject else "Topic"
    tag = f"{kind.lower()}/{args.slug or args.hub}"

    done = skipped = missing = 0
    for name in (n.strip() for n in sys.stdin):
        if not name:
            continue
        hits = list(CONVERSATIONS.rglob(name + ".md"))
        if not hits:
            print(f"  missing: {name}", file=sys.stderr)
            missing += 1
            continue
        path = hits[0]
        text = path.read_text(encoding="utf-8")
        if tag in text:
            skipped += 1
            continue
        text = re.sub(r"^(tags:\s*\[)(.*?)(\])",
                      lambda m: m.group(1) + m.group(2) + f", {tag}" + m.group(3),
                      text, count=1, flags=re.MULTILINE)
        path.write_text(
            text.rstrip("\n") + f"\n\n---\n**{kind}:** [[{args.hub}]] · #{tag}\n",
            encoding="utf-8")
        done += 1
    print(f"footered {done}, already tagged {skipped}, missing {missing}")


if __name__ == "__main__":
    main()
