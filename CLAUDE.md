# Obsidian AI Brain

## What This Is
Ingestion scripts that capture AI conversations from multiple sources into ~/obsidian-brain/ (a local Obsidian vault synced across devices via Obsidian Sync).

## One Repo
- This project (developer/obsidian-brain/) → scripts and tooling only
- ~/obsidian-brain/ → the vault, synced automatically by Obsidian Sync (no git)

## Sources
- Ollama on NUC (LAN) → proxy.py (logging proxy on :11435, fully automatic) or log_ollama.py (Python client helper, on call)
- ChatGPT → convert_chatgpt.py (periodic manual export)
- Claude.ai → QuickAdd hotkey in Obsidian (manual paste)
- Claude Code → hourly local `convert_claude_code.py` sweep, with a fallback sweep before `/brain-triage` (settled sessions and linked delta continuations)
- Codex → hourly local `convert_codex.py` sweep through the same LaunchAgent (visible messages only; settled sessions and linked delta continuations)
- Claude API → planned, not yet built (was to be log_claude.py)

## Vault Inbox
Ingestion scripts write to ~/obsidian-brain/00-inbox/
Triage is automated by analyze_inbox.py: asks local Ollama for title/summary/tags,
writes them to frontmatter, routes the note to a hub, moves it to 01-conversations/<source>/.
Persistent capture watermarks live under 99-archive/system/capture-state/, not in the inbox.
Run it when Obsidian Sync is idle (moving files mid-sync can create duplicates).

## Hub Links (no note is born a satellite)
analyze_inbox.py routes every note to one hub MOC as it files it, via hub_router.py, and
appends a `## Links` section carrying a `<!-- routed: tier confidence -->` marker so triage
can tell an auto-route from a curated link. Filing and linking used to be two steps with
only one of them automatic; that gap is what produced satellite nodes (see below).

Routing is deterministic and learned from the vault, in four tiers — `history` (tag/hub
co-occurrence), `project` (frontmatter naming a real 03-projects hub), `mention` (hub-body
vocabulary, for a brand-new topic), and `floor` ([[unrouted-captures]]). It commits on ~85%
of notes and agrees with the existing human hub choice 83% of the time; the rest go to the
floor hub on purpose, because a guessed hub is worse than an honest triage queue.

## Satellite nodes
A **satellite** is a note, or a small group linked only to each other, with no path to the
main graph component. Distinct from an orphan: a capture and its continuation child pointing
at each other and nothing else is internally linked and still unreachable.

`scripts/satellites.py` reports them; `check_vault.py`'s fourth gate fails on any that are
not in an exempt sector (99-archive, 04-templates, docs, attachment, `_`-prefixed, and
00-inbox which is transient staging). `scripts/repair_satellites.py` clears an existing
population. Background, and why three earlier cleanups regrew:
`06-decisions/2026-08-23-satellite-nodes.md`.

## Peer Links (graph, not star)
The hub link alone leaves the graph a hub-and-spoke star. relate_notes.py adds the
missing peer (note<->note) edges: it embeds each note's title+summary+tags via an Ollama embedding
model (mxbai-embed-large on the NUC), finds each note's top-K nearest neighbors by
cosine similarity, and writes a `## Related` section. It is idempotent (regenerates the
`## Related` block each run) and caches embeddings at ~/.cache/obsidian-brain-embeddings.json.
Dry-run by default; pass --apply to write. analyze_inbox.py calls it automatically
after filing new notes, so fresh imports self-link (it no-ops gracefully if the
embedding host is unreachable). Run it standalone to re-link or re-tune.

## Search Ranking (brain_mcp.py)
`search_notes` scores every match and sorts before truncating — it does not return
the first N files in filesystem order. Score = folder weight (02-knowledge/05-context
highest, 01-conversations low, 99-archive zero) + 40 for a filename match (hyphens
normalized, so "music production" matches `music-production.md`) + 25 for a
frontmatter hit + 10 for a heading hit + match density. Folder weight is deliberately
larger than the filename bonus so a curated hub outranks a chat that merely has the
word in its auto-generated title. Full-vault scan is ~0.15s over 1,860 notes.

## Scripts
All scripts live in developer/obsidian-brain/scripts/

## Commands
```bash
python scripts/proxy.py                                # run Ollama logging proxy on NUC (:11435 → :11434)
python scripts/log_ollama.py                           # Ollama client helper (ask/chat), logs each call
python scripts/convert_chatgpt.py conversations.json   # convert ChatGPT export
python3 scripts/convert_claude_code.py                 # capture settled Claude Code sessions
python3 scripts/convert_codex.py                       # capture settled Codex chats
python3 scripts/capture_chats.py                       # run both capture sweeps
python3 scripts/install_claude_code_capture.py         # install hourly macOS capture for both (once per Mac)
python3 scripts/analyze_inbox.py                       # title/summarize/tag + file the inbox
python3 scripts/relate_notes.py                        # DRY RUN: preview ## Related peer links
python3 scripts/relate_notes.py --apply                # write ## Related into every conversation note
python3 scripts/relate_notes.py --source chatgpt --k 5 --floor 0.62 --apply   # tune scope/precision
python3 scripts/check_vault.py                         # gate: retrieval + curated links + ghosts + satellites
python3 scripts/satellites.py                          # report notes off the main graph component
python3 scripts/repair_satellites.py --apply           # route existing satellites onto the graph
python3 scripts/hub_router.py --table                  # inspect the learned tag -> hub table
python3 scripts/repair_ghost_links.py --dry-run        # one-time: neutralize ghost links already in the vault
```

## Transcript text is never a graph edge
Captures quote whatever the session contained — `[[ -n "$x" ]]`, `[[:space:]]`,
CSV rows, and `~/dev/memory` note names that cannot resolve here. Written raw,
Obsidian renders each as an unresolved node, and a capture whose only links are
quoted noise shows up in the graph as a small island cluster.

`scripts/capture_text.py` backtick-wraps every wikilink the converters copy out of
a transcript, so the text survives exactly while the edge disappears. Real edges
are written by triage afterwards. The pipeline's own `> Continuation of [[…]]`
line is the single live link a capture may carry.

The same sanitizer strips slash-command envelopes before a title is slugged —
without it, a `/log-app` session became
`...command-messagelog-appcommand-message-command-namelog-appcom...`.

`check_vault.py`'s `ghosts` check fails the build if a capture ever holds a live
wikilink again. Background: `06-decisions/2026-08-18-transcript-links-are-not-graph-edges.md`.

## Note Frontmatter
Every ingested note uses:
```yaml
---
date: YYYY-MM-DD
source: claude-api        # claude-api | claude-ai | claude-code | codex | chatgpt | ollama
model: claude-sonnet-4-6
tags: []
summary: ""
project: ""
---
```
