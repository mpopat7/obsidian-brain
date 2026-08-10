import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import analyze_inbox
from scripts import convert_codex as capture


UTC = timezone.utc


class CodexCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.vault = self.root / "vault"
        self.codex = self.root / "codex"
        self.inbox = self.vault / "00-inbox"
        self.sessions = self.codex / "sessions"
        self.archive = self.codex / "archived_sessions"
        self.inbox.mkdir(parents=True)
        self.sessions.mkdir(parents=True)
        self.archive.mkdir()

        self.originals = (
            capture.VAULT,
            capture.INBOX,
            capture.CODEX_DATA,
            capture.SESSION_DIRS,
            capture.SESSION_INDEX,
            capture.WATERMARK_PATH,
        )
        capture.VAULT = self.vault
        capture.INBOX = self.inbox
        capture.CODEX_DATA = self.codex
        capture.SESSION_DIRS = (self.sessions, self.archive)
        capture.SESSION_INDEX = self.codex / "session_index.jsonl"
        capture.WATERMARK_PATH = self.inbox / "_codex-capture.md"

    def tearDown(self):
        (
            capture.VAULT,
            capture.INBOX,
            capture.CODEX_DATA,
            capture.SESSION_DIRS,
            capture.SESSION_INDEX,
            capture.WATERMARK_PATH,
        ) = self.originals
        self.tempdir.cleanup()

    def _write_session(self, session_id, timestamps, archived=False):
        records = [
            {
                "timestamp": timestamps[0],
                "type": "session_meta",
                "payload": {
                    "type": "session_meta",
                    "session_id": session_id,
                    "cwd": "/tmp/codex-project",
                },
            },
            {
                "timestamp": timestamps[0],
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "private instructions"}],
                },
            },
            {
                "timestamp": timestamps[0],
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "First question"},
            },
            {
                "timestamp": timestamps[0],
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "Working on it", "phase": "commentary"},
            },
            {
                "timestamp": timestamps[0],
                "type": "response_item",
                "payload": {"type": "custom_tool_call_output", "output": "secret tool output"},
            },
            {
                "timestamp": timestamps[0],
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "First answer", "phase": "final_answer"},
            },
            {
                "timestamp": timestamps[1],
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Second question"},
            },
            {
                "timestamp": timestamps[1],
                "type": "event_msg",
                "payload": {
                    "type": "thread_settings_applied",
                    "thread_settings": {"model": "gpt-test"},
                },
            },
            {
                "timestamp": timestamps[1],
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "Second answer", "phase": "final_answer"},
            },
        ]
        folder = self.archive if archived else self.sessions
        path = folder / f"rollout-{session_id}.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        old = datetime(2026, 8, 10, 10, 0, tzinfo=UTC).timestamp()
        os.utime(path, (old, old))
        return path

    def test_first_run_initializes_without_backfill(self):
        self._write_session("old", ("2026-08-09T08:00:00Z", "2026-08-09T09:00:00Z"))
        now = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)

        result = capture.sweep(now=now)

        self.assertTrue(result["initialized"])
        self.assertEqual([], result["captured"])
        self.assertEqual(now, capture.read_watermark())

    def test_capture_uses_visible_messages_and_deduplicates(self):
        capture.initialize_watermark(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
        self._write_session("codex-new", ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"), archived=True)
        capture.SESSION_INDEX.write_text(
            json.dumps({"id": "codex-new", "thread_name": "Codex capture test", "updated_at": ""}) + "\n"
        )
        now = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)

        first = capture.sweep(now=now)
        second = capture.sweep(now=now)

        self.assertEqual(1, len(first["captured"]))
        self.assertEqual([], second["captured"])
        note = first["captured"][0].read_text()
        self.assertIn("source: codex", note)
        self.assertIn('model: "gpt-test"', note)
        self.assertIn('title: "Codex capture test"', note)
        self.assertIn('session_id: "codex-new"', note)
        self.assertIn("## You", note)
        self.assertIn("## Codex", note)
        self.assertIn("Working on it", note)
        self.assertIn("Second answer", note)
        self.assertNotIn("private instructions", note)
        self.assertNotIn("secret tool output", note)

    def test_analyzer_routes_codex(self):
        self.assertEqual("codex", analyze_inbox.SOURCE_DEST["codex"])

    def test_resumed_chat_creates_delta_continuation(self):
        capture.initialize_watermark(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
        transcript = self._write_session(
            "codex-resumed",
            ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"),
        )
        first = capture.sweep(now=datetime(2026, 8, 10, 20, 0, tzinfo=UTC))
        filed = self.vault / "01-conversations" / "codex" / "filed-codex.md"
        filed.parent.mkdir(parents=True)
        first["captured"][0].rename(filed)

        resumed = [
            {
                "timestamp": "2026-08-11T08:00:00Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Resumed Codex question"},
            },
            {
                "timestamp": "2026-08-11T08:01:00Z",
                "type": "event_msg",
                "payload": {"type": "agent_message", "message": "Resumed Codex answer", "phase": "final_answer"},
            },
        ]
        with transcript.open("a") as handle:
            handle.write("\n".join(json.dumps(record) for record in resumed) + "\n")
        old = datetime(2026, 8, 11, 9, 0, tzinfo=UTC).timestamp()
        os.utime(transcript, (old, old))

        second = capture.sweep(now=datetime(2026, 8, 11, 14, 0, tzinfo=UTC))

        self.assertEqual(1, len(second["captured"]))
        note = second["captured"][0].read_text()
        body = note.split("\n---\n", 1)[1]
        self.assertIn("capture_revision: 2", note)
        self.assertIn('continuation_of: "filed-codex"', note)
        self.assertIn("[[filed-codex]]", body)
        self.assertIn("Resumed Codex question", body)
        self.assertIn("Resumed Codex answer", body)
        self.assertNotIn("First question", body)
        self.assertNotIn("First answer", body)

    def test_older_schema_uses_assistant_response_items(self):
        records = [
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Question one"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Legacy answer"}],
                },
            },
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Question two"},
            },
        ]

        rendered = capture.render_messages(records)

        self.assertIn("Question one", rendered)
        self.assertIn("Legacy answer", rendered)
        self.assertIn("Question two", rendered)


if __name__ == "__main__":
    unittest.main()
