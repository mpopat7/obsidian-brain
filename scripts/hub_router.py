#!/usr/bin/env python3
"""Pick the best-fit hub note for a capture, so no note is ever filed as a satellite.

A **satellite** is a note (or a small group of notes linked only to each other)
with no path to the main graph component. They accumulate whenever a capture is
filed with tags and a summary but no `[[link]]`, because link-on-triage is a
manual step and filing is not. This router closes that gap: `analyze_inbox.py`
routes every note to a hub as it files it, and triage upgrades that floor link
to real curated links later.

Routing is deterministic and learned from the vault itself, in four tiers:

  history — the tag/hub co-occurrence table observed across already-linked
            conversations. This is the strongest signal and carries most notes:
            `nutrition` has pointed at [[nutrition-and-training]] 168 times.
  project — the frontmatter `project:` field, when it names a real 03-projects
            hub. Often it names a git repo instead ("dev", "memory"), which is
            why this cannot be the only tier.
  mention — for a brand-new topic with no tag history, the hub whose body talks
            about the note's tags most. Cold-start path: `mcp` finds
            [[mcp-server-management]] on 34 mentions.
  floor   — [[unrouted-captures]] when nothing scores. Deliberately a real note
            rather than a guessed topic: it keeps the note on the graph without
            lying about what it is about, and its backlinks pane is the triage
            queue. A tag that lands here repeatedly is a hub that should exist.

Read-only with respect to the vault — callers do the writing.

    python3 hub_router.py                      # explain routing for unlinked notes
    python3 hub_router.py --note <path>        # explain one note
    python3 hub_router.py --table              # dump the learned tag table
"""

import argparse
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))
CONVERSATIONS = VAULT / "01-conversations"
HUB_DIRS = ("02-knowledge", "03-projects", "05-context")
PROJECT_DIR = "03-projects"

#: Where a note goes when no tier can place it. Must exist in the vault.
FLOOR_HUB = "unrouted-captures"

LINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_RE = re.compile(r"`[^`\n]*`")
WORD_RE = re.compile(r"[a-z0-9]{4,}")

#: A tag must have pointed at a hub at least this often before history trusts it.
#: 1 is noise — a single hand-made link would route every future note with that tag.
MIN_HISTORY = 2
#: A hub must mention a term at least this often for the cold-start tier to fire.
MIN_MENTIONS = 3
#: A term found in more than this share of hubs carries no signal about which hub.
#: Without it, prose words ("project", "python", "change") outvote the real topic:
#: an SIE/FINRA note routed to [[algoverse-research]] purely on shared vocabulary.
MAX_HUB_SHARE = 0.20

TIER_WEIGHT = {"history": 1.0, "project": 1.2, "mention": 0.10}
#: A tag is a deliberate topic label; a word in the summary is incidental.
TAG_TERM_BONUS = 1.5
#: Below this the winner is not beating the field on anything meaningful, so the
#: floor is more honest than the guess. Tuned against the holdout in tests.
MIN_SCORE = 0.30


def strip_code(text):
    """Remove fences and inline spans — Obsidian draws no edge from code."""
    return INLINE_RE.sub(" ", FENCE_RE.sub(" ", text))


def parse_note(path):
    """Return (tags, title, summary, project, resolved_link_targets) for a note."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    match = FM_RE.match(text)
    front = match.group(1) if match else ""
    tag_match = re.search(r"tags:\s*\[(.*?)\]", front, re.S)
    tags = [t.strip() for t in tag_match.group(1).split(",") if t.strip()] if tag_match else []

    def field(name):
        hit = re.search(r"^%s:\s*(.*)$" % name, front, re.M)
        return hit.group(1).strip().strip('"').strip() if hit else ""

    links = {l.split("|")[0].split("#")[0].strip()
             for l in LINK_RE.findall(strip_code(text))}
    return tags, field("title"), field("summary"), field("project"), {l for l in links if l}


class Router:
    """Routes a note to a hub using tables learned from the vault."""

    def __init__(self, vault=VAULT):
        self.vault = Path(vault)
        self.hubs = self._load_hubs()
        self.projects = {p.stem for p in (self.vault / PROJECT_DIR).glob("*.md")
                         if not p.name.startswith("_")}
        self.tag_table = self._learn_tag_table()
        self.term_index = self._index_hub_bodies()

    def _load_hubs(self):
        hubs = {}
        for folder in HUB_DIRS:
            for path in (self.vault / folder).rglob("*.md"):
                if not path.name.startswith("_"):
                    hubs[path.stem] = folder
        return hubs

    def _learn_tag_table(self):
        """tag -> Counter(hub) over conversations that already carry a hub link."""
        table = defaultdict(Counter)
        conversations = self.vault / "01-conversations"
        for path in conversations.rglob("*.md") if conversations.exists() else []:
            if path.name.startswith("_"):
                continue
            tags, _, _, _, links = parse_note(path)
            hub_links = links & set(self.hubs)
            if not hub_links:
                continue
            for tag in tags:
                for hub in hub_links:
                    table[tag][hub] += 1
        return table

    def _index_hub_bodies(self):
        """term -> Counter(hub), so a brand-new tag can still find its home."""
        index = defaultdict(Counter)
        for hub, folder in self.hubs.items():
            path = self.vault / folder / (hub + ".md")
            if not path.exists():
                hits = list((self.vault / folder).rglob(hub + ".md"))
                if not hits:
                    continue
                path = hits[0]
            body = path.read_text(encoding="utf-8", errors="ignore").lower()
            for term, count in Counter(WORD_RE.findall(body)).items():
                if count >= MIN_MENTIONS:
                    index[term][hub] += count

        # Drop terms spread across many hubs: they say nothing about which one.
        ceiling = max(2, int(len(self.hubs) * MAX_HUB_SHARE))
        return {term: hubs for term, hubs in index.items() if len(hubs) <= ceiling}

    def score(self, tags, title="", summary="", project=""):
        """Return {hub: (score, tier)} for every hub with any support."""
        scores = Counter()
        tiers = {}

        def add(hub, amount, tier):
            if hub not in self.hubs:
                return
            scores[hub] += amount
            if amount > tiers.get(hub, (0, ""))[0]:
                tiers[hub] = (amount, tier)

        for tag in tags:
            observed = self.tag_table.get(tag)
            if not observed:
                continue
            total = sum(observed.values())
            for hub, count in observed.items():
                if count >= MIN_HISTORY:
                    add(hub, TIER_WEIGHT["history"] * count / total, "history")

        if project and project in self.projects:
            add(project, TIER_WEIGHT["project"], "project")

        # Cold start: the note's own vocabulary against what each hub talks about.
        # Hub bodies are indexed by bare word, so a slug tag ("gmail-connector")
        # only matches once split into the words it is made of.
        tag_terms = set(tags)
        for tag in tags:
            tag_terms.update(WORD_RE.findall(tag))
        prose_terms = set(WORD_RE.findall((title + " " + summary).lower())) - tag_terms
        for term, weight in [(t, TAG_TERM_BONUS) for t in tag_terms] + \
                            [(t, 1.0) for t in prose_terms]:
            observed = self.term_index.get(term)
            if not observed:
                continue
            total = sum(observed.values())
            for hub, count in Counter(observed).most_common(3):
                add(hub, TIER_WEIGHT["mention"] * weight * count / total, "mention")

        # A hub whose whole name appears in the title/summary is a direct hit.
        text = (title + " " + summary).lower()
        for hub in self.hubs:
            words = [w for w in hub.split("-") if len(w) > 3]
            if words and all(w in text for w in words):
                add(hub, 0.75, "mention")

        return {hub: (score, tiers[hub][1]) for hub, score in scores.items()}

    def route(self, tags, title="", summary="", project=""):
        """Return (hub, confidence, tier). Never returns None — the floor catches all."""
        # An unclassified note has nothing to route on; prose alone picks whichever
        # hub happens to share vocabulary with it, which is a guess, not a routing.
        if not tags and project not in self.projects:
            return FLOOR_HUB, 0.0, "floor"

        scores = self.score(tags, title, summary, project)
        if not scores:
            return FLOOR_HUB, 0.0, "floor"

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1][0], kv[0]))
        best_hub, (best_score, best_tier) = ranked[0]
        # Deliberately no "prefer a specific hub over a catch-all" rule here: it was
        # tried and cost 3-7 accuracy points in every weighting. The long tail really
        # does belong to [[everyday-life-and-personal-admin]], and history knows it.

        if best_score < MIN_SCORE:
            return FLOOR_HUB, 0.0, "floor"

        total = sum(score for score, _ in scores.values())
        confidence = best_score / total if total else 0.0
        return best_hub, confidence, best_tier


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--note", help="explain the routing for one note path")
    ap.add_argument("--table", action="store_true", help="dump the learned tag table")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    router = Router()

    if args.table:
        rows = [(tag, counter.most_common(1)[0]) for tag, counter in router.tag_table.items()
                if counter.most_common(1)[0][1] >= MIN_HISTORY]
        rows.sort(key=lambda r: -r[1][1])
        print("%d tags with a hub seen >=%d times" % (len(rows), MIN_HISTORY))
        for tag, (hub, count) in rows[:args.limit]:
            print("  %-34s -> %-40s (%d)" % (tag, hub, count))
        return

    if args.note:
        tags, title, summary, project, _ = parse_note(args.note)
        hub, confidence, tier = router.route(tags, title, summary, project)
        print("tags:    %s" % ", ".join(tags))
        print("project: %s" % project)
        print("route:   [[%s]]  confidence=%.2f  tier=%s" % (hub, confidence, tier))
        print("\ncandidates:")
        for h, (score, t) in sorted(router.score(tags, title, summary, project).items(),
                                    key=lambda kv: -kv[1][0])[:8]:
            print("  %-40s %.3f  %s" % (h, score, t))
        return

    # Default: explain every note that currently has no hub link.
    print("%-40s %-6s %-8s %s" % ("ROUTE", "CONF", "TIER", "NOTE"))
    counts = Counter()
    for folder in ("00-inbox", "01-conversations"):
        base = VAULT / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name.startswith("_"):
                continue
            tags, title, summary, project, links = parse_note(path)
            if links & set(router.hubs):
                continue
            hub, confidence, tier = router.route(tags, title, summary, project)
            counts[tier] += 1
            print("%-40s %-6.2f %-8s %s" % (hub, confidence, tier, path.name[:54]))
    print("\nby tier: %s" % dict(counts))


if __name__ == "__main__":
    main()
