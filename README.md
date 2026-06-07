# Obsidian AI Brain — Scripts

Ingestion scripts that capture AI conversations from Claude API, Ollama, and ChatGPT into `~/obsidian-brain/` (a local Obsidian vault synced across devices via Obsidian Sync).

## Scripts

| Script | Source | Mode |
|---|---|---|
| `scripts/log_claude.py` | Claude API | Fully automatic |
| `scripts/log_ollama.py` | Ollama (NUC gx10-909f) | Fully automatic |
| `scripts/convert_chatgpt.py` | ChatGPT JSON export | Periodic / manual |

## Vault
The vault lives at `~/obsidian-brain/`. Sync is handled by Obsidian Sync — no git needed for the vault. All scripts write to `~/obsidian-brain/00-inbox/`.

## No dependencies
Standard library only (`json`, `pathlib`, `urllib`, `datetime`). Python ≥ 3.8.
