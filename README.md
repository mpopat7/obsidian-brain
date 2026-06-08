# Obsidian AI Brain — Scripts

Scripts that capture AI conversations from Ollama and ChatGPT into `~/obsidian-brain/` (a local Obsidian vault synced across devices via Obsidian Sync), then analyze and file them. Claude API logging is planned but not yet built.

## Scripts

### Ingestion (conversation → `00-inbox/`)
| Script | Source | Mode |
|---|---|---|
| `scripts/proxy.py` | Ollama (NUC gx10-909f) — logging proxy on :11435 | Fully automatic |
| `scripts/log_ollama.py` | Ollama — Python client helper (`ask()` / `chat()`) | On call |
| `scripts/convert_chatgpt.py` | ChatGPT JSON export | Periodic / manual |

### Analysis (`00-inbox/` → `01-conversations/<source>/`)
| Script | What it does |
|---|---|
| `scripts/analyze_inbox.py` | For each inbox note: asks a local Ollama model for a title, summary, and tags; writes them into the frontmatter; moves the note to `01-conversations/<source>/`. |

```bash
python scripts/analyze_inbox.py
# config via env: OLLAMA_HOST (default http://localhost:11434),
#                 OLLAMA_MODEL (default llama3.1:8b), VAULT
```

**⚠️ Run when Obsidian Sync is idle.** `analyze_inbox.py` moves files; doing that while Sync is mid-download can leave duplicate notes (analyzed copy in `01-conversations/`, stale copy back in `00-inbox/`). Best run on the NUC, or pause Sync during a bulk run.

## Vault
The vault lives at `~/obsidian-brain/`. Sync is handled by Obsidian Sync — no git needed for the vault. Ingestion scripts write to `~/obsidian-brain/00-inbox/`; `analyze_inbox.py` empties the inbox into `01-conversations/`.

## No dependencies
Standard library only (`json`, `pathlib`, `urllib`, `datetime`, `re`, `shutil`). Python ≥ 3.8.

## No dependencies
Standard library only (`json`, `pathlib`, `urllib`, `datetime`). Python ≥ 3.8.
