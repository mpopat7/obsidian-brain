#!/usr/bin/env python3
"""Capture settled Codex chats into the Obsidian inbox.

Only user-visible user and assistant messages are rendered. Developer prompts,
reasoning records, tool calls, and tool outputs remain out of the note. The
first run creates a vault-synced watermark and deliberately captures nothing.
"""

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .capture_state import CaptureState, capture_states, migrate_state_file
    from .capture_text import clean_title, is_scaffolding, neutralize_wikilinks
except ImportError:
    from capture_state import CaptureState, capture_states, migrate_state_file
    from capture_text import clean_title, is_scaffolding, neutralize_wikilinks


VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))
INBOX = VAULT / "00-inbox"
CODEX_DATA = Path(os.environ.get("CODEX_DATA_DIR", Path.home() / ".codex"))
SESSION_DIRS = (CODEX_DATA / "sessions", CODEX_DATA / "archived_sessions")
SESSION_INDEX = CODEX_DATA / "session_index.jsonl"
WATERMARK_PATH = VAULT / "99-archive" / "system" / "capture-state" / "codex.md"
LEGACY_WATERMARK_NAME = "_codex-capture.md"
DEFAULT_SETTLE_HOURS = 3.0
DEFAULT_MIN_TURNS = 2


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
    WATERMARK_PATH.write_text(
        "---\n"
        f"watermark: {_iso(now)}\n"
        "---\n"
        "Codex capture begins at this timestamp. This state is synced by "
        "Obsidian Sync and kept outside the inbox.\n"
    )
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


def _visible_user_message(record):
    if record.get("type") == "event_msg":
        payload = record.get("payload", {})
        if payload.get("type") == "user_message":
            message = str(payload.get("message", "")).strip()
            return message or None
    return None


def _response_text(payload):
    content = payload.get("content", [])
    if not isinstance(content, list):
        return ""
    return "\n\n".join(
        str(block.get("text", "")).strip()
        for block in content
        if isinstance(block, dict)
        and block.get("type") in ("output_text", "text")
        and str(block.get("text", "")).strip()
    )


def _record_after(record, after):
    if after is None:
        return True
    timestamp = _parse_time(record.get("timestamp"))
    return timestamp is not None and timestamp > after


def _user_turns(records, after=None):
    return sum(
        1
        for record in records
        if _record_after(record, after) and _visible_user_message(record)
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


def _session_meta(records):
    for record in records:
        if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
            return record["payload"]
    return {}


def _session_id(records, path):
    meta = _session_meta(records)
    return str(meta.get("session_id") or meta.get("id") or path.stem.rsplit("-", 1)[-1])


def _thread_titles():
    titles = {}
    if not SESSION_INDEX.exists():
        return titles
    try:
        lines = SESSION_INDEX.read_text(errors="replace").splitlines()
    except OSError:
        return titles
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("id") and str(item.get("thread_name", "")).strip():
            titles[str(item["id"])] = str(item["thread_name"]).strip()
    return titles


def _session_title(records, path, titles):
    session_id = _session_id(records, path)
    if session_id in titles:
        return titles[session_id]
    for record in records:
        message = _visible_user_message(record)
        if not message or is_scaffolding(message):
            continue
        title = clean_title(message)
        if title:
            return title
    return "Codex session"


def _session_model(records):
    models = []
    for record in records:
        payload = record.get("payload", {})
        if payload.get("type") != "thread_settings_applied":
            continue
        model = payload.get("thread_settings", {}).get("model")
        if model:
            models.append(str(model))
    return models[-1] if models else "codex"


def _session_project(records):
    cwd = str(_session_meta(records).get("cwd", "")).strip()
    return Path(cwd).name if cwd else ""


def render_messages(records, after=None):
    has_agent_events = any(
        record.get("type") == "event_msg"
        and record.get("payload", {}).get("type") == "agent_message"
        for record in records
    )
    lines = []
    current_speaker = None

    def append_message(speaker, message):
        nonlocal current_speaker
        message = str(message).strip()
        if not message:
            return
        if current_speaker != speaker:
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend([f"## {speaker}", ""])
            current_speaker = speaker
        lines.extend([message, ""])

    for record in records:
        if not _record_after(record, after):
            continue
        payload = record.get("payload", {})
        user_message = _visible_user_message(record)
        if user_message:
            append_message("You", user_message)
        elif (
            record.get("type") == "event_msg"
            and payload.get("type") == "agent_message"
        ):
            append_message("Codex", payload.get("message", ""))
        elif (
            not has_agent_events
            and record.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
        ):
            append_message("Codex", _response_text(payload))

    # Transcript text is quoted content, never a vault edge. Left raw, any
    # [[...]] it contains becomes an unresolved ghost node in the graph.
    return neutralize_wikilinks("\n".join(lines).strip()) + "\n"


def _transcript_paths():
    seen = set()
    for folder in SESSION_DIRS:
        if not folder.exists():
            continue
        for path in folder.rglob("*.jsonl"):
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                yield path


def _write_session(records, path, activity, titles, state=None):
    session_id = _session_id(records, path)
    title = _session_title(records, path, titles)
    model = _session_model(records)
    project = _session_project(records)
    date = activity.strftime("%Y-%m-%d")
    revision = state.revision + 1 if state else 1
    body = render_messages(records, after=state.until if state else None)
    if state:
        body = f"> Continuation of [[{state.path.stem}]].\n\n" + body
    frontmatter = [
        "---",
        f"date: {date}",
        "source: codex",
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
    stem = f"{date}-codex-{_slug(title)}"
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

    states = capture_states(VAULT, "codex")
    titles = _thread_titles()
    settle_before = now - timedelta(hours=settle_hours)
    eligible = []
    captured = []

    for path in sorted(_transcript_paths()):
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
            dest = _write_session(records, path, activity, titles, state=state)
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
    parser.add_argument("--dry-run", action="store_true", help="show eligible chats without writing")
    parser.add_argument("--settle-hours", type=float, default=DEFAULT_SETTLE_HOURS)
    parser.add_argument("--min-turns", type=int, default=DEFAULT_MIN_TURNS)
    args = parser.parse_args()

    if args.init:
        watermark, created = initialize_watermark()
        state = "Initialized" if created else "Already initialized"
        print(f"{state} Codex capture at {_iso(watermark)}")
        return

    result = sweep(settle_hours=args.settle_hours, min_turns=args.min_turns,
                   dry_run=args.dry_run)
    if result["would_initialize"]:
        print(f"DRY RUN — Codex watermark missing; a normal run would initialize at {_iso(_utc_now())}.")
    elif result["initialized"]:
        print("Initialized Codex capture — no past chats were imported.")
    elif args.dry_run:
        print(f"DRY RUN — {len(result['eligible'])} settled Codex chat(s) eligible.")
        for path in result["eligible"]:
            print(f"  {path.name}")
    else:
        print(f"Codex capture — {len(result['captured'])} new chat(s) saved.")
        for path in result["captured"]:
            print(f"  {path.name}")


if __name__ == "__main__":
    main()
