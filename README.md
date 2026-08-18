# Obsidian AI Brain — Scripts

Scripts that capture AI conversations from Ollama, ChatGPT, Claude Code, and Codex into `~/obsidian-brain/` (a local Obsidian vault synced across devices via Obsidian Sync), then analyze and file them. Claude API logging is planned but not yet built.

## Scripts

### Ingestion (conversation → `00-inbox/`)
| Script | Source | Mode |
|---|---|---|
| `scripts/proxy.py` | Ollama (NUC on the LAN) — logging proxy on :11435 | Fully automatic |
| `scripts/log_ollama.py` | Ollama — Python client helper (`ask()` / `chat()`) | On call |
| `scripts/convert_chatgpt.py` | ChatGPT JSON export | Periodic / manual |
| `scripts/convert_claude_code.py` | Settled `~/.claude/projects/**/*.jsonl` sessions | Hourly local sweep + fallback before `/brain-triage` |
| `scripts/convert_codex.py` | Settled `~/.codex/sessions/**/*.jsonl` chats | Hourly local sweep + fallback before `/brain-triage` |
| `scripts/capture_chats.py` | Runs both local transcript converters | Hourly LaunchAgent target |
| `scripts/capture_text.py` | Shared hygiene for both converters: neutralizes quoted `[[wikilinks]]` and strips slash-command envelopes from titles | Imported, not run |

Claude Code and Codex each use a vault-synced watermark under
`99-archive/system/capture-state/`, so persistent state does not clutter the inbox and the first
run imports nothing from the past. Existing `_claude-code-capture.md` and `_codex-capture.md`
inbox markers migrate there automatically on the next non-dry capture sweep. Later runs capture
new sessions with at least two user turns after they have been idle
for three hours. If a captured session is resumed, its next settled capture is a separate,
back-linked continuation containing only messages added since the prior capture; one new user
turn is enough for a continuation. Only visible Codex user/assistant messages are included;
instructions, reasoning, and tool traffic are excluded. Both initial-capture thresholds can be
overridden for diagnostics:

```bash
python3 scripts/convert_claude_code.py --init
python3 scripts/convert_codex.py --init
python3 scripts/capture_chats.py --dry-run
python3 scripts/capture_chats.py --settle-hours 1 --min-turns 3
```

On macOS, install the hourly local sweep once per Mac that runs Claude Code:

```bash
python3 scripts/install_claude_code_capture.py
```

The LaunchAgent runs only the two deterministic converters—never Ollama or inbox triage. Eligible Markdown files
therefore remain visible in `00-inbox/` until `/brain-triage` is run. Because the sweep is hourly,
a new session or continuation normally appears between three and four hours after its last write.
Inspect or remove the agent with `--status` or `--uninstall`; logs live at
`~/Library/Logs/obsidian-brain-claude-code-capture.log`.

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

### Checks and repair
| Script | What it does |
|---|---|
| `scripts/check_vault.py` | Three gates: retrieval expectations still rank, curated notes have no dangling links, and no capture holds a live ghost link. Exits non-zero so it can gate a triage run. |
| `scripts/repair_ghost_links.py` | One-time cleanup for captures written before the converters sanitized their output. Backtick-wraps unresolved links in `01-conversations/**` only; curated notes are never touched. `--dry-run` first. |

```bash
python3 scripts/check_vault.py
python3 scripts/repair_ghost_links.py --dry-run
```

Why this exists: a transcript quotes `[[ -n "$x" ]]`, `[[:space:]]`, CSV rows and
`~/dev/memory` note names. Obsidian reads every one as a wikilink and draws an
unresolved node, so a capture whose only links are quoted noise appears in the
graph as a small island cluster. See
`06-decisions/2026-08-18-transcript-links-are-not-graph-edges.md`.

## Vault
The vault lives at `~/obsidian-brain/`. Sync is handled by Obsidian Sync — no git needed for the vault. Ingestion scripts write to `~/obsidian-brain/00-inbox/`; `analyze_inbox.py` empties the inbox into `01-conversations/`.

## No dependencies
Standard library only (`json`, `pathlib`, `urllib`, `datetime`, `re`, `shutil`). Python ≥ 3.8.
