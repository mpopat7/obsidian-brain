#!/usr/bin/env python3
"""Check that the vault still answers correctly and that curated notes link cleanly.

Two checks, each guarding a failure that actually happened:

  retrieval — every `query -> note` pair in retrieval-expectations.txt must put
              that note in the top N. Catches a scoring change that demotes a
              hub, and a newly written note that steals another hub's query.
  links     — no [[link]] in a curated note may point at a note that doesn't
              exist. Conversation captures are skipped: they quote [[link]] as
              prose and would drown the signal in false positives.

Exits non-zero if anything fails, so it can gate a triage run.

    python3 check_vault.py
    python3 check_vault.py --top 5
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import brain_mcp  # noqa: E402

VAULT = brain_mcp.VAULT
EXPECTATIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "retrieval-expectations.txt")
# 06-decisions is append-only: it quotes links that were broken at the time and
# then fixed, so flagging them is unactionable by rule.
CURATED = ("02-knowledge", "03-projects", "05-context")
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def strip_code(text):
    """Drop code spans and fences — `[[link]]` there is an example, not an edge.

    Splitting on backticks pairs them exactly; a regex mis-pairs on lines
    carrying several spans and then eats the real links between them.
    """
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        out.append("".join(p for i, p in enumerate(line.split("`")) if i % 2 == 0))
    return "\n".join(out)


def check_retrieval(top):
    with open(EXPECTATIONS, encoding="utf-8") as fh:
        pairs = [ln.split("->") for ln in fh
                 if "->" in ln and not ln.lstrip().startswith("#")]
    failures = []
    for raw_q, raw_want in pairs:
        query, want = raw_q.strip(), raw_want.strip()
        out = brain_mcp.tool_search_notes(query, max_results=top)
        heads = [ln[4:] for ln in out.splitlines() if ln.startswith("### ")]
        stems = [os.path.splitext(os.path.basename(h))[0] for h in heads]
        if want not in stems:
            found = brain_mcp.tool_search_notes(query, max_results=50)
            all_stems = [os.path.splitext(os.path.basename(ln[4:]))[0]
                         for ln in found.splitlines() if ln.startswith("### ")]
            rank = all_stems.index(want) + 1 if want in all_stems else None
            failures.append((query, want, rank, stems[0] if stems else "(nothing)"))
    print("retrieval: {}/{} queries put the expected note in the top {}"
          .format(len(pairs) - len(failures), len(pairs), top))
    for query, want, rank, got in failures:
        where = "#{}".format(rank) if rank else "not in top 50"
        print("  FAIL  {!r}: wanted {} ({}), got {}".format(query, want, where, got))
    return not failures


def check_links():
    stems, folders = set(), set()
    for path in brain_mcp._walk():
        stems.add(os.path.splitext(os.path.basename(path))[0])
        folders.add(os.path.relpath(path, VAULT).split(os.sep)[0])

    broken = []
    for path in brain_mcp._walk():
        rel = os.path.relpath(path, VAULT)
        if not rel.startswith(CURATED):
            continue
        with open(path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        text = strip_code(text)
        for link in LINK_RE.findall(text):
            if link.split("|")[0].strip() in folders:   # [[02-knowledge|knowledge]] shorthand
                continue
            target = link.split("|")[0].split("#")[0].strip()
            if target and target not in stems:
                broken.append((rel, target))

    print("links: {} dangling [[link]]s in curated notes".format(len(broken)))
    for rel, target in broken[:20]:
        print("  FAIL  {} -> [[{}]]".format(rel, target))
    if len(broken) > 20:
        print("  ... and {} more".format(len(broken) - 20))
    return not broken


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=3,
                    help="rank an expected note must reach (default 3)")
    args = ap.parse_args()
    ok = check_retrieval(args.top)
    ok = check_links() and ok
    print("\n{}".format("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
