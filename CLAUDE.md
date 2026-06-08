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
- Claude API → planned, not yet built (was to be log_claude.py)

## Vault Inbox
All scripts write to ~/obsidian-brain/00-inbox/
Triage: move notes to 01-conversations/ and add tags/summary

## Scripts
All scripts live in developer/obsidian-brain/scripts/

## Commands
```bash
python scripts/proxy.py                                # run Ollama logging proxy on NUC (:11435 → :11434)
python scripts/log_ollama.py                           # Ollama client helper (ask/chat), logs each call
python scripts/convert_chatgpt.py conversations.json   # convert ChatGPT export
```

## Note Frontmatter
Every ingested note uses:
```yaml
---
date: YYYY-MM-DD
source: claude-api        # claude-api | claude-ai | chatgpt | ollama
model: claude-sonnet-4-6
tags: []
summary: ""
project: ""
---
```
