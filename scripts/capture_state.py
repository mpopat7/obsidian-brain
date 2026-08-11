"""Shared vault-backed state for resumable chat capture."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class CaptureState:
    revision: int
    until: datetime
    path: Path


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def migrate_state_file(legacy_path, current_path):
    """Move one legacy vault-state note without replacing current state."""
    if current_path.exists() or not legacy_path.exists():
        return False
    current_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.replace(current_path)
    return True


def _scalar(value):
    value = value.strip()
    if value[:1] in ('"', "'"):
        try:
            return str(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value.strip("\"'")
    return value


def _frontmatter(path):
    try:
        text = path.read_text(errors="replace")[:6000]
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fields = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = _scalar(value)
    return fields


def capture_states(vault, source):
    """Return the newest capture cursor for each session of one source."""
    states = {}
    if not vault.exists():
        return states
    for path in vault.rglob("*.md"):
        fields = _frontmatter(path)
        if fields.get("source") != source or not fields.get("session_id"):
            continue
        until = parse_time(fields.get("capture_until"))
        if until is None:
            # Pre-cursor captures existed briefly during rollout. Their file mtime is
            # the safest available boundary: it prevents a full duplicate while still
            # allowing messages written after that note to become continuations.
            try:
                until = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
        try:
            revision = max(1, int(fields.get("capture_revision", "1")))
        except ValueError:
            revision = 1
        session_id = fields["session_id"]
        candidate = CaptureState(revision=revision, until=until, path=path)
        previous = states.get(session_id)
        if previous is None or (candidate.until, candidate.revision) > (
            previous.until,
            previous.revision,
        ):
            states[session_id] = candidate
    return states
