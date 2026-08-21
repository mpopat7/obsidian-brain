#!/usr/bin/env python3
"""Repair continuation captures whose parent link no longer resolves.

Continuation captures carry the same edge twice: a ``continuation_of``
frontmatter key and a ``> Continuation of [[parent]]`` banner. If triage
renames the parent after the child is captured, both pointers become stale.

The durable recovery keys are ``session_id`` and ``capture_revision``. For a
broken revision N capture, this script finds revision N-1 from the same session
and repoints both copies of the edge at that note's current stem.

Only ``01-conversations`` is inspected or changed. The default is a dry run;
writing requires the explicit ``--apply`` flag.

    python3 repair_continuations.py
    python3 repair_continuations.py --apply
"""

import argparse
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


VAULT = Path(os.path.expanduser(os.environ.get("VAULT", "~/obsidian-brain")))
CAPTURE_ROOT = "01-conversations"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)
FIELD_RE = re.compile(r"^([a-z_]+):\s*(.*?)\s*$")
CONTINUATION_FIELD_RE = re.compile(
    r"^(?P<prefix>\s*continuation_of:\s*)"
    r"(?P<quote>[\"']?)(?P<target>.*?)(?P=quote)(?P<suffix>\s*)$"
)
CONTINUATION_BANNER_RE = re.compile(
    r"^(?P<prefix>>\s*Continuation of\s+\[\[)"
    r"(?P<target>[^\[\]\n]+)(?P<suffix>\]\]\.?)"
    r"(?P<trailing>[ \t]*)$",
    re.MULTILINE,
)


@dataclass
class Capture:
    path: Path
    rel: str
    text: str
    session_id: str
    revision: int

    @property
    def stem(self):
        return self.path.stem


@dataclass
class Repair:
    child: Capture
    parent: Capture
    old_targets: tuple
    new_text: str
    pointer_count: int


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _metadata(text):
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        field = FIELD_RE.match(line)
        if field:
            fields[field.group(1)] = _unquote(field.group(2))
    return fields


def _target_stem(target):
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    return Path(target).name.removesuffix(".md")


def _continuation_targets(text):
    fields = _metadata(text)
    targets = []
    if fields.get("continuation_of"):
        targets.append(fields["continuation_of"])
    targets.extend(match.group("target").strip()
                   for match in CONTINUATION_BANNER_RE.finditer(text))
    return tuple(targets)


def rewrite_continuation_text(text, new_target, old_target=None):
    """Rewrite continuation frontmatter and banners, preserving their style.

    If ``old_target`` is supplied, only pointers exactly matching that stem are
    changed. Without it, every continuation pointer is repaired to ``new_target``.
    Returns ``(new_text, pointer_count)``.
    """
    old_stem = _target_stem(old_target) if old_target is not None else None
    changed = 0

    def should_replace(target):
        return old_stem is None or _target_stem(target) == old_stem

    frontmatter = FRONTMATTER_RE.match(text)
    if frontmatter:
        lines = frontmatter.group(1).split("\n")
        for index, line in enumerate(lines):
            match = CONTINUATION_FIELD_RE.match(line)
            if not match or not should_replace(match.group("target")):
                continue
            quote = match.group("quote")
            lines[index] = (match.group("prefix") + quote + new_target + quote
                            + match.group("suffix"))
            changed += 1
        rebuilt = "\n".join(lines)
        text = text[:frontmatter.start(1)] + rebuilt + text[frontmatter.end(1):]

    def replace_banner(match):
        nonlocal changed
        if not should_replace(match.group("target")):
            return match.group(0)
        changed += 1
        return (match.group("prefix") + new_target + match.group("suffix")
                + match.group("trailing"))

    return CONTINUATION_BANNER_RE.sub(replace_banner, text), changed


def _captures(vault):
    root = vault / CAPTURE_ROOT
    captures = []
    if not root.exists():
        return captures
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fields = _metadata(text)
        try:
            revision = int(fields.get("capture_revision", ""))
        except ValueError:
            revision = 0
        captures.append(Capture(
            path=path,
            rel=str(path.relative_to(vault)),
            text=text,
            session_id=fields.get("session_id", ""),
            revision=revision,
        ))
    return captures


def _note_stems(vault):
    return {path.stem for path in vault.rglob("*.md")}


def _choose_parent(child, candidates, targets, stems):
    if len(candidates) == 1:
        return candidates[0]

    resolving = {_target_stem(target) for target in targets
                 if _target_stem(target) in stems}
    pointed_at = [candidate for candidate in candidates
                  if candidate.stem in resolving]
    if len(pointed_at) == 1:
        return pointed_at[0]

    siblings = [candidate for candidate in candidates
                if candidate.path.parent == child.path.parent]
    if len(siblings) == 1:
        return siblings[0]
    return None


def find_repairs(vault):
    """Return ``(repairs, unresolved)`` for broken conversation continuations."""
    vault = Path(vault)
    captures = _captures(vault)
    stems = _note_stems(vault)
    by_revision = defaultdict(list)
    for capture in captures:
        if capture.session_id and capture.revision:
            by_revision[(capture.session_id, capture.revision)].append(capture)

    repairs, unresolved = [], []
    for child in captures:
        targets = _continuation_targets(child.text)
        if not targets or all(_target_stem(target) in stems for target in targets):
            continue

        candidates = by_revision.get((child.session_id, child.revision - 1), [])
        parent = _choose_parent(child, candidates, targets, stems)
        if parent is None:
            reason = "no unique same-session revision {} parent".format(
                child.revision - 1)
            unresolved.append((child, targets, reason))
            continue

        new_text, pointer_count = rewrite_continuation_text(child.text, parent.stem)
        if pointer_count == 0 or new_text == child.text:
            unresolved.append((child, targets, "continuation pointers could not be rewritten"))
            continue
        repairs.append(Repair(child, parent, targets, new_text, pointer_count))
    return repairs, unresolved


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write repairs (default: dry run)")
    parser.add_argument("--vault", default=str(VAULT))
    args = parser.parse_args()

    vault = Path(os.path.expanduser(args.vault))
    repairs, unresolved = find_repairs(vault)
    for repair in repairs:
        old = ", ".join("[[{}]]".format(target) for target in repair.old_targets)
        print("  {}: {} -> [[{}]]".format(
            repair.child.rel, old, repair.parent.stem))
        if args.apply:
            repair.child.path.write_text(repair.new_text, encoding="utf-8")
    for child, targets, reason in unresolved:
        old = ", ".join("[[{}]]".format(target) for target in targets)
        print("  UNRESOLVED {}: {} ({})".format(child.rel, old, reason))

    mode = "repaired" if args.apply else "would repair"
    print("{} {} broken continuation capture(s); {} unresolved".format(
        mode, len(repairs), len(unresolved)))
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
