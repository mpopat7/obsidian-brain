# Obsidian AI Brain

## What This Is
Ingestion scripts that capture AI conversations from multiple sources into ~/obsidian-brain/ (a local Obsidian vault synced across devices via Obsidian Sync).

## One Repo
- This project (developer/obsidian-brain/) → scripts and tooling only
- ~/obsidian-brain/ → the vault, synced automatically by Obsidian Sync (no git)

## Sources
- Claude API → log_claude.py (fully automatic)
- Ollama on NUC gx10-909f → log_ollama.py (fully automatic)
- ChatGPT → convert_chatgpt.py (periodic manual export)
- Claude.ai → QuickAdd hotkey in Obsidian (manual paste)

## Vault Inbox
All scripts write to ~/obsidian-brain/00-inbox/
Triage: move notes to 01-conversations/ and add tags/summary

## Scripts
All scripts live in developer/obsidian-brain/scripts/

## Commands
```bash
python scripts/log_claude.py       # log a Claude API conversation
python scripts/log_ollama.py       # log an Ollama conversation
python scripts/convert_chatgpt.py conversations.json  # convert ChatGPT export
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
