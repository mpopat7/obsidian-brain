# Obsidian AI Brain — Scripts

Ingestion scripts that capture AI conversations from Claude API, Ollama, and ChatGPT into `~/obsidian-brain/` (a private Obsidian vault).

## Scripts

| Script | Source | Mode |
|---|---|---|
| `scripts/log_claude.py` | Claude API | Fully automatic |
| `scripts/log_ollama.py` | Ollama (NUC gx10-909f) | Fully automatic |
| `scripts/convert_chatgpt.py` | ChatGPT JSON export | Periodic / manual |

## Vault
The vault lives at `~/obsidian-brain/` in a separate private GitHub repo. All scripts write to `~/obsidian-brain/00-inbox/`.

## No dependencies
Standard library only (`json`, `pathlib`, `urllib`, `datetime`). Python ≥ 3.8.
