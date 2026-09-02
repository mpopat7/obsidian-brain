#!/usr/bin/env python3
"""Capture settled Antigravity sessions into the Obsidian inbox.

The first run creates a vault-synced watermark and deliberately captures
nothing. Later runs only consider sessions with activity after that watermark.
Deduplication is derived from ``session_id`` frontmatter already in the vault,
so there is no machine-local capture database to drift.
"""

import argparse
import json
import os
import re
import sqlite3
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
ANTIGRAVITY_DATA = Path(
    os.environ.get("ANTIGRAVITY_DATA_DIR", Path.home() / ".gemini" / "antigravity-cli")
)
TRANSCRIPT_ROOT = ANTIGRAVITY_DATA / "brain"
SUMMARY_DB = ANTIGRAVITY_DATA / "conversation_summaries.db"
WATERMARK_PATH = VAULT / "99-archive" / "system" / "capture-state" / "antigravity.md"
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
    return json.dumps(str(value), ensure_ascii=False)


def read_watermark():
    if not WATERMARK_PATH.exists():
        return None
    match = re.search(
        r"^watermark:\s*[\"']?([^\n\"']+)",
        WATERMARK_PATH.read_text(errors="replace"),
        re.MULTILINE,
    )
    return _parse_time(match.group(1).strip()) if match else None


def initialize_watermark(now=None):
    existing = read_watermark()
    if existing:
        return existing, False
    now = now or _utc_now()
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"watermark: {_iso(now)}\n"
        "---\n"
        "Antigravity capture begins at this timestamp. This state is synced by "
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


def _record_after(record, after):
    if after is None:
        return True
    timestamp = _parse_time(record.get("created_at"))
    return timestamp is not None and timestamp > after


def _user_message(record):
    if record.get("type") != "USER_INPUT" or record.get("source") != "USER_EXPLICIT":
        return None
    content = str(record.get("content", ""))
    match = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.DOTALL)
    if match:
        text = match.group(1).strip()
    else:
        text = re.sub(
            r"<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)>.*?</\1>",
            " ",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        text = re.sub(r"</?[a-zA-Z][\w-]*>", " ", text).strip()
    return text or None


def _user_turns(records, after=None):
    return sum(
        1
        for record in records
        if _record_after(record, after) and _user_message(record)
    )


def _last_activity(records, path):
    timestamps = [
        parsed
        for parsed in (_parse_time(record.get("created_at")) for record in records)
        if parsed
    ]
    if timestamps:
        return max(timestamps)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _session_id(records, path):
    # path is .../brain/<session_id>/.system_generated/logs/transcript.jsonl
    if len(path.parents) >= 3:
        return path.parents[2].name
    return path.parent.name


def _db_title(session_id, db_path=SUMMARY_DB):
    if not db_path or not Path(db_path).exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT title FROM conversation_summaries WHERE conversation_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            title = str(row[0]).strip()
            return title or None
    except Exception:
        return None
    return None


def _session_title(records, session_id=None, db_path=SUMMARY_DB):
    if session_id:
        db_title = _db_title(session_id, db_path)
        if db_title:
            return db_title
    for record in records:
        msg = _user_message(record)
        if msg and not is_scaffolding(msg):
            title = clean_title(msg)
            if title:
                return title
    return "Antigravity session"


def _session_model(records):
    for record in reversed(records):
        content = str(record.get("content", ""))
        match = re.search(r"setting `Model Selection` from .*? to ([^\n\.]+)", content)
        if match:
            return match.group(1).strip()
    return "gemini"


def _session_project(records, session_id=None, db_path=SUMMARY_DB):
    for record in reversed(records):
        for tc in record.get("tool_calls", []):
            args = tc.get("args", {})
            if isinstance(args, dict):
                cwd = args.get("Cwd") or args.get("SearchPath") or args.get("DirectoryPath")
                if cwd:
                    cwd = str(cwd).strip("\"'")
                    name = Path(cwd).name
                    if name:
                        return name
    if session_id and db_path and Path(db_path).exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(
                "SELECT workspace_uris FROM conversation_summaries WHERE conversation_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                uris = json.loads(row[0])
                if uris and isinstance(uris, list):
                    uri = uris[0]
                    name = Path(uri.replace("file://", "")).name
                    if name:
                        return name
        except Exception:
            pass
    return ""


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


def render_messages(records, after=None):
    lines = []
    current_speaker = None
    pending_tool_calls = []

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
        source = record.get("source")

        if record_type == "USER_INPUT":
            user_msg = _user_message(record)
            if user_msg:
                speaker("You")
                lines.append(user_msg)
                lines.append("")
            continue

        if record_type == "PLANNER_RESPONSE":
            speaker("Antigravity")
            for tc in record.get("tool_calls", []):
                tool_name = str(tc.get("name") or "tool")
                pending_tool_calls.append(tool_name)
                args = _compact_json(tc.get("args", {}), MAX_TOOL_INPUT_CHARS)
                lines.append(f"- **Tool — {tool_name}:** {args}")
            content = str(record.get("content") or "").strip()
            if content:
                lines.append(content)
                lines.append("")
            continue

        if record_type == "GENERIC" and source == "MODEL":
            speaker("Antigravity")
            content = str(record.get("content") or "").strip()
            tool_name = pending_tool_calls.pop(0) if pending_tool_calls else "Tool"
            truncated = _truncate(content, MAX_TOOL_RESULT_CHARS)
            lines.append(f"- **{tool_name} result:** {truncated or '[empty]'}")
            continue

    return neutralize_wikilinks("\n".join(lines).strip()) + "\n"


def _write_session(records, path, activity, state=None, db_path=SUMMARY_DB):
    session_id = _session_id(records, path)
    title = _session_title(records, session_id=session_id, db_path=db_path)
    model = _session_model(records)
    project = _session_project(records, session_id=session_id, db_path=db_path)
    revision = state.revision + 1 if state else 1
    body = render_messages(records, after=state.until if state else None)
    if state:
        body = f"> Continuation of [[{state.path.stem}]].\n\n" + body
    date = activity.strftime("%Y-%m-%d")
    frontmatter = [
        "---",
        f"date: {date}",
        "source: antigravity",
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
    stem = f"{date}-antigravity-{_slug(title)}"
    if state:
        stem = f"{stem}-continued-{revision}"
    dest = _unique_path(INBOX, stem)
    dest.write_text("\n".join(frontmatter) + body)
    return dest


def _find_transcripts(root):
    if not root.exists():
        return []
    return sorted(root.glob("*/.system_generated/logs/transcript.jsonl"))


def sweep(now=None, settle_hours=DEFAULT_SETTLE_HOURS, min_turns=DEFAULT_MIN_TURNS,
          dry_run=False):
    now = now or _utc_now()
    watermark = read_watermark()
    if watermark is None:
        if dry_run:
            return {"initialized": False, "would_initialize": True, "captured": [], "eligible": []}
        initialize_watermark(now)
        return {"initialized": True, "would_initialize": False, "captured": [], "eligible": []}

    states = capture_states(VAULT, "antigravity")
    settle_before = now - timedelta(hours=settle_hours)
    eligible = []
    captured = []

    for path in _find_transcripts(TRANSCRIPT_ROOT):
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
        print(f"{state} Antigravity capture at {_iso(watermark)}")
        return

    result = sweep(
        settle_hours=args.settle_hours,
        min_turns=args.min_turns,
        dry_run=args.dry_run,
    )
    if result["would_initialize"]:
        print(f"DRY RUN — watermark missing; a normal run would initialize capture at {_iso(_utc_now())}.")
        return
    if result["initialized"]:
        print("Initialized Antigravity capture — no past sessions were imported.")
        return
    if args.dry_run:
        print(f"DRY RUN — {len(result['eligible'])} settled session(s) eligible.")
        for path in result["eligible"]:
            print(f"  {path.name}")
        return
    print(f"Antigravity capture — {len(result['captured'])} new session(s) saved.")
    for path in result["captured"]:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
