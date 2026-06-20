# Obsidian AI Brain

## What This Is
Ingestion scripts that capture AI conversations from multiple sources into ~/obsidian-brain/ (a local Obsidian vault synced across devices via Obsidian Sync).

## One Repo
- This project (developer/obsidian-brain/) → scripts and tooling only
- ~/obsidian-brain/ → the vault, synced automatically by Obsidian Sync (no git)

## Sources
- Ollama on NUC gx10-909f → proxy.py (logging proxy on :11435, fully automatic) or log_ollama.py (Python client helper, on call)
- ChatGPT → convert_chatgpt.py (periodic manual export)
- Claude.ai → QuickAdd hotkey in Obsidian (manual paste)
- Perplexity → QuickAdd hotkey in Obsidian (manual paste)
- Claude API → planned, not yet built (was to be log_claude.py)

## Vault Inbox
Ingestion scripts write to ~/obsidian-brain/00-inbox/
Triage is automated by analyze_inbox.py: asks local Ollama for title/summary/tags,
writes them to frontmatter, moves the note to 01-conversations/<source>/.
Run it when Obsidian Sync is idle (moving files mid-sync can create duplicates).

## Peer Links (graph, not star)
analyze_inbox.py only links each note UP to one hub MOC (e.g. [[nutrition-and-training]]),
which leaves the graph a hub-and-spoke star. relate_notes.py adds the missing peer
(note<->note) edges: it embeds each note's title+summary+tags via an Ollama embedding
model (mxbai-embed-large on the NUC), finds each note's top-K nearest neighbors by
cosine similarity, and writes a `## Related` section. It is idempotent (regenerates the
`## Related` block each run) and caches embeddings at ~/.cache/obsidian-brain-embeddings.json.
Dry-run by default; pass --apply to write. Run after analyze_inbox.py to link new imports.

## Scripts
All scripts live in developer/obsidian-brain/scripts/

## Commands
```bash
python scripts/proxy.py                                # run Ollama logging proxy on NUC (:11435 → :11434)
python scripts/log_ollama.py                           # Ollama client helper (ask/chat), logs each call
python scripts/convert_chatgpt.py conversations.json   # convert ChatGPT export
python3 scripts/analyze_inbox.py                       # title/summarize/tag + file the inbox
python3 scripts/relate_notes.py                        # DRY RUN: preview ## Related peer links
python3 scripts/relate_notes.py --apply                # write ## Related into every conversation note
python3 scripts/relate_notes.py --source chatgpt --k 5 --floor 0.62 --apply   # tune scope/precision
```

## Note Frontmatter
Every ingested note uses:
```yaml
---
date: YYYY-MM-DD
source: claude-api        # claude-api | claude-ai | chatgpt | perplexity | ollama
model: claude-sonnet-4-6
tags: []
summary: ""
project: ""
---
```
