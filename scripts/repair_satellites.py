#!/usr/bin/env python3
"""Pull existing satellite notes back onto the graph by routing each to a hub.

The companion to the fix in `analyze_inbox.py`. That one stops new satellites
being created; this one clears the population already on disk. Both use the same
`hub_router`, so a note repaired here gets the link it would have been born with.

Dry-run by default — prints what it would write and touches nothing. Pass
`--apply` to write. Idempotent: a note that already carries a hub link is skipped,
so re-running is safe and a curated link is never overwritten by a routed one.

    python3 repair_satellites.py                # preview
    python3 repair_satellites.py --apply        # write
    python3 repair_satellites.py --strict --apply   # include 00-inbox
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import satellites  # noqa: E402
from analyze_inbox import add_hub_link  # noqa: E402
from hub_router import FLOOR_HUB, Router  # noqa: E402

VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the links")
    ap.add_argument("--strict", action="store_true", help="include 00-inbox notes")
    args = ap.parse_args()

    notes, clusters, offenders = satellites.find(vault=VAULT, strict=args.strict)
    if not offenders:
        print("No satellites — nothing to repair.")
        return

    router = Router(VAULT)
    tiers = Counter()
    written = skipped = 0

    print("%-34s %-9s %s" % ("ROUTE", "TIER", "NOTE"))
    for stem in offenders:
        path = VAULT / notes[stem]["rel"]
        text = path.read_text(encoding="utf-8", errors="ignore")
        new_text, hub, tier = add_hub_link(text, router)
        if hub is None:
            skipped += 1
            continue
        tiers[tier] += 1
        print("%-34s %-9s %s" % (hub, tier, notes[stem]["rel"]))
        if args.apply:
            path.write_text(new_text, encoding="utf-8")
            written += 1

    print("\nby tier: %s" % dict(tiers))
    if tiers.get("floor"):
        print("%d note(s) routed to [[%s]] — work them down during triage."
              % (tiers["floor"], FLOOR_HUB))
    if args.apply:
        print("wrote %d note(s), skipped %d that already had a hub link." % (written, skipped))
    else:
        print("DRY RUN — nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
