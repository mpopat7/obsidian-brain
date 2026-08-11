#!/usr/bin/env python3
"""Capture settled Claude Code sessions into the Obsidian inbox.

The first run creates a vault-synced watermark and deliberately captures
nothing. Later runs only consider sessions with activity after that watermark.
Deduplication is derived from ``session_id`` frontmatter already in the vault,
so there is no machine-local capture database to drift.
"""

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .capture_state import CaptureState, capture_states, migrate_state_file
except ImportError:
    from capture_state import CaptureState, capture_states, migrate_state_file


VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))
INBOX = VAULT / "00-inbox"
TRANSCRIPT_ROOT = Path(
    os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects")
)
WATERMARK_PATH = VAULT / "99-archive" / "system" / "capture-state" / "claude-code.md"
LEGACY_WATERMARK_NAME = "_claude-code-capture.md"
DEFAULT_SETTLE_HOURS = 3.0
DEFAULT_MIN_TURNS = 2
MAX_TOOL_INPUT_CHARS = 360
MAX_TOOL_RESULT_CHARS = 700


def _slug(text, max_len=60):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len].strip("-") or "untitled"


def _unique_path(folder, stem):
    path = folder / f"{stem}.md"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.md"
        n += 1
    return path


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _yaml_string(value):
    # JSON strings are valid YAML scalars and safely handle quotes/newlines.
    return json.dumps(str(value), ensure_ascii=False)


def read_watermark():
    path = WATERMARK_PATH if WATERMARK_PATH.exists() else INBOX / LEGACY_WATERMARK_NAME
    if not path.exists():
        return None
    match = re.search(
        r"^watermark:\s*[\"']?([^\n\"']+)",
        path.read_text(errors="replace"),
        re.MULTILINE,
    )
    return _parse_time(match.group(1).strip()) if match else None


def migrate_watermark():
    return migrate_state_file(INBOX / LEGACY_WATERMARK_NAME, WATERMARK_PATH)


def initialize_watermark(now=None):
    existing = read_watermark()
    if existing:
        migrate_watermark()
        return existing, False
    now = now or _utc_now()
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"watermark: {_iso(now)}\n"
        "---\n"
        "Claude Code capture begins at this timestamp. This state is synced by "
        "Obsidian Sync and kept outside the inbox.\n"
    )
    WATERMARK_PATH.write_text(content)
    return now, True


def _load_records(path):
    records = []
    with path.open(errors="replace") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def _text_blocks(record):
    content = record.get("message", {}).get("content", [])
    if isinstance(content, str):
        return [content.strip()] if content.strip() else []
    if not isinstance(content, list):
        return []
    return [
        str(block.get("text", "")).strip()
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and str(block.get("text", "")).strip()
    ]


def _record_after(record, after):
    if after is None:
        return True
    timestamp = _parse_time(record.get("timestamp"))
    return timestamp is not None and timestamp > after


def _user_turns(records, after=None):
    return sum(
        1
        for record in records
        if record.get("type") == "user"
        and _record_after(record, after)
        and _text_blocks(record)
    )


def _last_activity(records, path):
    timestamps = [
        parsed
        for parsed in (_parse_time(record.get("timestamp")) for record in records)
        if parsed
    ]
    if timestamps:
        return max(timestamps)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _session_id(records, path):
    for record in records:
        if record.get("sessionId"):
            return str(record["sessionId"])
    return path.stem


def _session_title(records):
    titles = [
        str(record.get("aiTitle", "")).strip()
        for record in records
        if record.get("type") == "ai-title" and str(record.get("aiTitle", "")).strip()
    ]
    if titles:
        return titles[-1]
    for record in records:
        texts = _text_blocks(record) if record.get("type") == "user" else []
        if texts:
            return re.sub(r"\s+", " ", texts[0])[:80].strip()
    return "Claude Code session"


def _session_model(records):
    models = [
        str(record.get("message", {}).get("model", "")).strip()
        for record in records
        if str(record.get("message", {}).get("model", "")).strip()
    ]
    return models[-1] if models else "claude"


def _session_project(records):
    workdirs = [str(record.get("cwd", "")).strip() for record in records if record.get("cwd")]
    return Path(workdirs[-1]).name if workdirs else ""


def _truncate(value, limit):
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _compact_json(value, limit):
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(value)
    return _truncate(rendered, limit)


def _tool_result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            elif item is not None:
                parts.append(str(item))
        return " ".join(part for part in parts if part)
    return str(content or "")


def render_messages(records, after=None):
    lines = []
    current_speaker = None
    tool_names = {}

    def speaker(name):
        nonlocal current_speaker
        if current_speaker != name:
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend([f"## {name}", ""])
            current_speaker = name

    for record in records:
        if not _record_after(record, after):
            continue
        record_type = record.get("type")
        content = record.get("message", {}).get("content", [])
        blocks = content if isinstance(content, list) else []

        if record_type == "user":
            texts = _text_blocks(record)
            if texts:
                speaker("You")
                lines.extend(texts)
                lines.append("")
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                speaker("Claude Code")
                tool_name = tool_names.get(str(block.get("tool_use_id", "")), "tool")
                result = _truncate(_tool_result_text(block.get("content")), MAX_TOOL_RESULT_CHARS)
                status = "error" if block.get("is_error") else "result"
                lines.append(f"- **{tool_name} {status}:** {result or '[empty]'}")
            continue

        if record_type != "assistant":
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text" and str(block.get("text", "")).strip():
                speaker("Claude Code")
                lines.append(str(block["text"]).strip())
                lines.append("")
            elif block_type == "tool_use":
                speaker("Claude Code")
                tool_name = str(block.get("name") or "tool")
                tool_names[str(block.get("id", ""))] = tool_name
                args = _compact_json(block.get("input", {}), MAX_TOOL_INPUT_CHARS)
                lines.append(f"- **Tool — {tool_name}:** {args}")
            elif block_type == "thinking":
                # Thinking blocks are intentionally omitted. They are often encrypted or
                # extremely verbose and are not part of the visible conversation scrollback.
                continue

    return "\n".join(lines).strip() + "\n"


def _write_session(records, path, activity, state=None):
    session_id = _session_id(records, path)
    title = _session_title(records)
    model = _session_model(records)
    project = _session_project(records)
    revision = state.revision + 1 if state else 1
    body = render_messages(records, after=state.until if state else None)
    if state:
        body = f"> Continuation of [[{state.path.stem}]].\n\n" + body
    date = activity.strftime("%Y-%m-%d")
    frontmatter = [
        "---",
        f"date: {date}",
        "source: claude-code",
        f"model: {_yaml_string(model)}",
        f"title: {_yaml_string(title)}",
        'summary: ""',
        "tags: []",
        f"project: {_yaml_string(project)}",
        f"session_id: {_yaml_string(session_id)}",
        f"capture_revision: {revision}",
        f"capture_until: {_iso(activity)}",
    ]
    if state:
        frontmatter.append(f"continuation_of: {_yaml_string(state.path.stem)}")
    frontmatter.extend([
        "---",
        "",
    ])
    INBOX.mkdir(parents=True, exist_ok=True)
    stem = f"{date}-claude-code-{_slug(title)}"
    if state:
        stem += f"-continued-{revision}"
    dest = _unique_path(INBOX, stem)
    dest.write_text("\n".join(frontmatter) + body)
    return dest


def sweep(now=None, settle_hours=DEFAULT_SETTLE_HOURS, min_turns=DEFAULT_MIN_TURNS,
          dry_run=False):
    now = now or _utc_now()
    if not dry_run:
        migrate_watermark()
    watermark = read_watermark()
    if watermark is None:
        if dry_run:
            return {"initialized": False, "would_initialize": True, "captured": [], "eligible": []}
        initialize_watermark(now)
        return {"initialized": True, "would_initialize": False, "captured": [], "eligible": []}

    states = capture_states(VAULT, "claude-code")
    settle_before = now - timedelta(hours=settle_hours)
    eligible = []
    captured = []

    if not TRANSCRIPT_ROOT.exists():
        return {"initialized": False, "would_initialize": False, "captured": [], "eligible": []}

    for path in sorted(TRANSCRIPT_ROOT.rglob("*.jsonl")):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) > settle_before:
                continue
            records = _load_records(path)
        except OSError:
            continue
        if not records:
            continue
        activity = _last_activity(records, path)
        session_id = _session_id(records, path)
        state = states.get(session_id)
        if state:
            if activity <= state.until or _user_turns(records, after=state.until) < 1:
                continue
        elif activity <= watermark or _user_turns(records) < min_turns:
            continue
        eligible.append(path)
        if not dry_run:
            dest = _write_session(records, path, activity, state=state)
            revision = state.revision + 1 if state else 1
            states[session_id] = CaptureState(revision, activity, dest)
            captured.append(dest)

    return {
        "initialized": False,
        "would_initialize": False,
        "captured": captured,
        "eligible": eligible,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="create the watermark and exit")
    parser.add_argument("--dry-run", action="store_true", help="show eligible sessions without writing")
    parser.add_argument("--settle-hours", type=float, default=DEFAULT_SETTLE_HOURS)
    parser.add_argument("--min-turns", type=int, default=DEFAULT_MIN_TURNS)
    args = parser.parse_args()

    if args.init:
        watermark, created = initialize_watermark()
        state = "Initialized" if created else "Already initialized"
        print(f"{state} Claude Code capture at {_iso(watermark)}")
        return

    result = sweep(settle_hours=args.settle_hours, min_turns=args.min_turns,
                   dry_run=args.dry_run)
    if result["would_initialize"]:
        print(f"DRY RUN — watermark missing; a normal run would initialize capture at {_iso(_utc_now())}.")
        return
    if result["initialized"]:
        print("Initialized Claude Code capture — no past sessions were imported.")
        return
    if args.dry_run:
        print(f"DRY RUN — {len(result['eligible'])} settled session(s) eligible.")
        for path in result["eligible"]:
            print(f"  {path.name}")
        return
    print(f"Claude Code capture — {len(result['captured'])} new session(s) saved.")
    for path in result["captured"]:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
