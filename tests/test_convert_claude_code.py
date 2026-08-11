import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import convert_claude_code as capture
from scripts import analyze_inbox


UTC = timezone.utc


class ClaudeCodeCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.vault = self.root / "vault"
        self.transcripts = self.root / "projects"
        self.inbox = self.vault / "00-inbox"
        self.inbox.mkdir(parents=True)
        self.transcripts.mkdir()

        self.originals = (
            capture.VAULT,
            capture.INBOX,
            capture.TRANSCRIPT_ROOT,
            capture.WATERMARK_PATH,
            analyze_inbox.VAULT,
            analyze_inbox.INBOX,
            analyze_inbox.CONVERSATIONS,
        )
        capture.VAULT = self.vault
        capture.INBOX = self.inbox
        capture.TRANSCRIPT_ROOT = self.transcripts
        capture.WATERMARK_PATH = (
            self.vault / "99-archive" / "system" / "capture-state" / "claude-code.md"
        )
        analyze_inbox.VAULT = self.vault
        analyze_inbox.INBOX = self.inbox
        analyze_inbox.CONVERSATIONS = self.vault / "01-conversations"

    def tearDown(self):
        (
            capture.VAULT,
            capture.INBOX,
            capture.TRANSCRIPT_ROOT,
            capture.WATERMARK_PATH,
            analyze_inbox.VAULT,
            analyze_inbox.INBOX,
            analyze_inbox.CONVERSATIONS,
        ) = self.originals
        self.tempdir.cleanup()

    def _write_session(self, session_id, timestamps, title="Capture test"):
        records = [
            {"type": "ai-title", "sessionId": session_id, "aiTitle": title},
            {
                "type": "user",
                "sessionId": session_id,
                "timestamp": timestamps[0],
                "cwd": "/tmp/sample-project",
                "message": {"role": "user", "content": [{"type": "text", "text": "First prompt"}]},
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "timestamp": timestamps[0],
                "cwd": "/tmp/sample-project",
                "message": {
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [
                        {"type": "thinking", "thinking": "hidden"},
                        {"type": "text", "text": "First answer"},
                        {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "x"}},
                    ],
                },
            },
            {
                "type": "user",
                "sessionId": session_id,
                "timestamp": timestamps[0],
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "x" * 2000}],
                },
            },
            {
                "type": "user",
                "sessionId": session_id,
                "timestamp": timestamps[1],
                "cwd": "/tmp/sample-project",
                "message": {"role": "user", "content": [{"type": "text", "text": "Second prompt"}]},
            },
        ]
        path = self.transcripts / f"{session_id}.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        old = datetime(2026, 8, 10, 10, 0, tzinfo=UTC).timestamp()
        os.utime(path, (old, old))
        return path

    def test_first_run_initializes_without_backfill(self):
        self._write_session("old-session", ("2026-08-09T08:00:00Z", "2026-08-09T09:00:00Z"))
        now = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)

        result = capture.sweep(now=now)

        self.assertTrue(result["initialized"])
        self.assertEqual([], result["captured"])
        self.assertEqual(now, capture.read_watermark())
        self.assertEqual([], list(self.inbox.glob("20*.md")))

    def test_existing_inbox_watermark_moves_to_system_state(self):
        legacy = self.inbox / capture.LEGACY_WATERMARK_NAME
        legacy.write_text(
            "---\nwatermark: 2026-08-10T12:00:00Z\n---\nLegacy capture state.\n"
        )

        capture.sweep(now=datetime(2026, 8, 10, 15, 0, tzinfo=UTC))

        self.assertFalse(legacy.exists())
        self.assertTrue(capture.WATERMARK_PATH.exists())
        self.assertEqual(
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC), capture.read_watermark()
        )

    def test_capture_is_settled_deduplicated_and_readable(self):
        capture.initialize_watermark(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
        self._write_session("new-session", ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"))
        now = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)

        first = capture.sweep(now=now)
        second = capture.sweep(now=now)

        self.assertEqual(1, len(first["captured"]))
        self.assertEqual([], second["captured"])
        note = first["captured"][0].read_text()
        self.assertIn('session_id: "new-session"', note)
        self.assertIn("source: claude-code", note)
        self.assertIn("## You", note)
        self.assertIn("## Claude Code", note)
        self.assertIn("**Tool — Read:**", note)
        self.assertNotIn("hidden", note)
        self.assertLess(len(note), 2500)

    def test_analyzer_preserves_session_id_and_routes_source(self):
        rebuilt = analyze_inbox.rebuild(
            {
                "date": "2026-08-10",
                "source": "claude-code",
                "model": "claude-test",
                "session_id": "session-123",
                "capture_revision": "2",
                "capture_until": "2026-08-10T18:00:00Z",
                "continuation_of": '"prior-note"',
            },
            {"title": "Test", "summary": "Summary", "tags": ["test"]},
            "\nBody\n",
        )

        self.assertEqual("claude-code", analyze_inbox.SOURCE_DEST["claude-code"])
        self.assertIn("session_id: session-123", rebuilt)
        self.assertIn("capture_revision: 2", rebuilt)
        self.assertIn("capture_until: 2026-08-10T18:00:00Z", rebuilt)
        self.assertIn('continuation_of: "prior-note"', rebuilt)

    def test_resumed_session_creates_delta_continuation(self):
        capture.initialize_watermark(datetime(2026, 8, 10, 12, 0, tzinfo=UTC))
        transcript = self._write_session(
            "resumed-session",
            ("2026-08-10T13:00:00Z", "2026-08-10T14:00:00Z"),
        )
        first = capture.sweep(now=datetime(2026, 8, 10, 20, 0, tzinfo=UTC))
        filed = self.vault / "01-conversations" / "claude-code" / "filed-original.md"
        filed.parent.mkdir(parents=True)
        first["captured"][0].rename(filed)

        resumed = [
            {
                "type": "user",
                "sessionId": "resumed-session",
                "timestamp": "2026-08-11T08:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "Resumed prompt"}]},
            },
            {
                "type": "assistant",
                "sessionId": "resumed-session",
                "timestamp": "2026-08-11T08:01:00Z",
                "message": {"role": "assistant", "model": "claude-test", "content": [{"type": "text", "text": "Resumed answer"}]},
            },
        ]
        with transcript.open("a") as handle:
            handle.write("\n".join(json.dumps(record) for record in resumed) + "\n")
        old = datetime(2026, 8, 11, 9, 0, tzinfo=UTC).timestamp()
        os.utime(transcript, (old, old))

        second = capture.sweep(now=datetime(2026, 8, 11, 14, 0, tzinfo=UTC))

        self.assertEqual(1, len(second["captured"]))
        note = second["captured"][0].read_text()
        self.assertIn("capture_revision: 2", note)
        self.assertIn('continuation_of: "filed-original"', note)
        self.assertIn("[[filed-original]]", note)
        self.assertIn("Resumed prompt", note)
        self.assertIn("Resumed answer", note)
        self.assertNotIn("First prompt", note)
        self.assertNotIn("First answer", note)


if __name__ == "__main__":
    unittest.main()
