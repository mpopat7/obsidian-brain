#!/usr/bin/env python3
"""One-off: insert `chatgpt` into ChatGPT note filenames (YYYY-MM-DD-slug.md ->
YYYY-MM-DD-chatgpt-slug.md) and rewrite every [[wikilink]] to them vault-wide so
links don't break. Idempotent. Dry run by default; pass --apply to write."""

import re
import sys
from pathlib import Path

VAULT = Path.home() / "obsidian-brain"
FOLDER = VAULT / "01-conversations" / "chatgpt"
PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")


def build_mapping():
    mapping = {}
    for path in sorted(FOLDER.glob("*.md")):
        if path.name.startswith("_"):
            continue
        m = PATTERN.match(path.name)
        if not m or m.group(2).startswith("chatgpt-"):
            continue
        date, rest = m.groups()
        mapping[path.stem] = f"{date}-chatgpt-{rest}"
    return mapping


def rewrite_links(text, mapping):
    # Only rewrite link targets bounded by ]] | or # so a stem that prefixes
    # another isn't partially matched.
    def repl(m):
        new = mapping.get(m.group("stem"))
        return f"[[{new}{m.group('tail')}" if new else m.group(0)

    return re.sub(r"\[\[(?P<stem>[^\[\]|#]+)(?P<tail>[\]|#])", repl, text)


def main(apply):
    mapping = build_mapping()
    print(f"{len(mapping)} files to rename.")
    for old, new in list(mapping.items())[:5]:
        print(f"  {old}.md  ->  {new}.md")

    link_edits = 0
    for md in VAULT.rglob("*.md"):
        if "/.git/" in str(md):
            continue
        text = md.read_text()
        new_text = rewrite_links(text, mapping)
        if new_text != text:
            link_edits += 1
            if apply:
                md.write_text(new_text)
    print(f"{link_edits} notes have links to update.")

    if apply:
        for old, new in mapping.items():
            (FOLDER / f"{old}.md").rename(FOLDER / f"{new}.md")
        print(f"APPLIED — {len(mapping)} renamed, links rewritten in {link_edits} notes.")
    else:
        print("DRY RUN — re-run with --apply.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
