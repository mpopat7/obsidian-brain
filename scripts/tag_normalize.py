#!/usr/bin/env python3
"""Merge tags that are the same word spelled differently — deterministic, no model.

Two tags merge only when they collapse to an identical key under punctuation
folding and conservative depluralization (note-taking/notetaking,
datascience/data-science, application-essay/application-essays). Nothing is
merged on similarity, so unrelated tags in the same domain stay separate.

Namespaced tags (`subject/*`, `topic/*`) are never merged — they are a
deliberate overlay layer, and folding them into their bare counterpart would
erase the distinction.

Dry-run by default; --apply rewrites the `tags:` line in frontmatter.

    python3 tag_normalize.py            # preview merges
    python3 tag_normalize.py --apply
"""

import argparse
import re
import sys

from tag_canon import CONVERSATIONS, collect_tags, remap_line

# Endings where a trailing "s" is part of the word, not a plural.
_NOT_PLURAL = ("ss", "us", "is", "as", "os")


def depluralize(word):
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "xes", "ses", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(_NOT_PLURAL):
        return word[:-1]
    return word


def key(tag):
    """Fold a tag to the form two spellings of the same word share."""
    return depluralize(re.sub(r"[\s_\-]+", "", tag.lower()))


def readable(tag):
    """Hyphenated is house style, but not when it splits off a 1-2 char stub
    (t-sa, mc-donalds, e-gpu) — those read worse than the joined form."""
    parts = tag.split("-")
    return len(parts) > 1 and all(len(p) > 2 for p in parts)


def build_map(counts):
    groups, protected = {}, 0
    for tag in counts:
        if "/" in tag:                      # namespaced overlay — leave alone
            protected += 1
            continue
        groups.setdefault(key(tag), []).append(tag)

    mapping, merges = {}, []
    for members in groups.values():
        canon = min(members, key=lambda t: (-counts[t], not readable(t), len(t), t))
        for m in members:
            mapping[m] = canon
        if len(members) > 1:
            merges.append((canon, sorted(members, key=lambda t: -counts[t])))
    return mapping, merges, protected


def run(root, apply):
    counts, note_tags = collect_tags(root)
    mapping, merges, protected = build_map(counts)
    after = len({mapping.get(t, t) for t in counts})

    print(f"{len(counts)} distinct tags across {len(note_tags)} notes")
    print(f"{protected} namespaced tags protected (subject/*, topic/*)")
    print(f"\n{len(counts)} -> {after} canonical tags "
          f"({len(counts) - after} merged away)\n")

    merges.sort(key=lambda m: -sum(counts[t] for t in m[1]))
    print(f"All {len(merges)} merges (canonical <- members[count]):")
    for canon, members in merges:
        shown = ", ".join(f"{m}[{counts[m]}]" for m in members if m != canon)
        print(f"  {canon}[{counts[canon]}] <- {shown}")

    if not apply:
        print("\nDry run — re-run with --apply to rewrite frontmatter.")
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
    ap.add_argument("--source", help="limit to 01-conversations/<source>/")
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()
    run(CONVERSATIONS / args.source if args.source else CONVERSATIONS, args.apply)


if __name__ == "__main__":
    main()
