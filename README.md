# Obsidian AI Brain — Scripts

Ingestion scripts that capture AI conversations from Ollama and ChatGPT into `~/obsidian-brain/` (a local Obsidian vault synced across devices via Obsidian Sync). Claude API logging is planned but not yet built.

## Scripts

| Script | Source | Mode |
|---|---|---|
| `scripts/proxy.py` | Ollama (NUC gx10-909f) — logging proxy on :11435 | Fully automatic |
| `scripts/log_ollama.py` | Ollama — Python client helper (`ask()` / `chat()`) | On call |
| `scripts/convert_chatgpt.py` | ChatGPT JSON export | Periodic / manual |

## Vault
The vault lives at `~/obsidian-brain/`. Sync is handled by Obsidian Sync — no git needed for the vault. All scripts write to `~/obsidian-brain/00-inbox/`.

## No dependencies
Standard library only (`json`, `pathlib`, `urllib`, `datetime`). Python ≥ 3.8.
