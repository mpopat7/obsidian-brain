#!/usr/bin/env python3
"""Run all local chat-to-Obsidian capture sweeps."""

import argparse

try:
    from . import convert_claude_code, convert_codex
except ImportError:  # Direct script execution puts scripts/ itself on sys.path.
    import convert_claude_code
    import convert_codex


CAPTURES = (
    ("Claude Code", convert_claude_code),
    ("Codex", convert_codex),
)


def run(dry_run=False, settle_hours=3.0, min_turns=2):
    results = {}
    for label, module in CAPTURES:
        results[label] = module.sweep(
            dry_run=dry_run,
            settle_hours=settle_hours,
            min_turns=min_turns,
        )
    return results


def _report(label, result, dry_run):
    if result["would_initialize"]:
        print(f"{label}: watermark missing; a normal run would initialize without backfill.")
    elif result["initialized"]:
        print(f"{label}: initialized without backfill.")
    elif dry_run:
        print(f"{label}: {len(result['eligible'])} settled chat(s) eligible (dry run).")
    else:
        print(f"{label}: {len(result['captured'])} new chat(s) saved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="initialize all missing watermarks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--settle-hours", type=float, default=3.0)
    parser.add_argument("--min-turns", type=int, default=2)
    args = parser.parse_args()

    if args.init:
        for label, module in CAPTURES:
            watermark, created = module.initialize_watermark()
            state = "initialized" if created else "already initialized"
            print(f"{label}: {state} at {module._iso(watermark)}")
        return

    results = run(
        dry_run=args.dry_run,
        settle_hours=args.settle_hours,
        min_turns=args.min_turns,
    )
    for label, result in results.items():
        _report(label, result, args.dry_run)


if __name__ == "__main__":
    main()
