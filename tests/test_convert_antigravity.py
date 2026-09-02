import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import convert_antigravity as capture
from scripts import analyze_inbox


UTC = timezone.utc


class AntigravityCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.vault = self.root / "vault"
        self.data_dir = self.root / "antigravity-cli"
        self.transcripts = self.data_dir / "brain"
        self.inbox = self.vault / "00-inbox"
        self.inbox.mkdir(parents=True)
        self.transcripts.mkdir(parents=True)

        self.originals = (
            capture.VAULT,
            capture.INBOX,
            capture.TRANSCRIPT_ROOT,
            capture.SUMMARY_DB,
            capture.WATERMARK_PATH,
            analyze_inbox.VAULT,
            analyze_inbox.INBOX,
            analyze_inbox.CONVERSATIONS,
        )
        capture.VAULT = self.vault
        capture.INBOX = self.inbox
        capture.TRANSCRIPT_ROOT = self.transcripts
        capture.SUMMARY_DB = self.data_dir / "conversation_summaries.db"
        capture.WATERMARK_PATH = (
            self.vault / "99-archive" / "system" / "capture-state" / "antigravity.md"
        )
        analyze_inbox.VAULT = self.vault
        analyze_inbox.INBOX = self.inbox
        analyze_inbox.CONVERSATIONS = self.vault / "01-conversations"

    def tearDown(self):
        (
            capture.VAULT,
            capture.INBOX,
            capture.TRANSCRIPT_ROOT,
            capture.SUMMARY_DB,
            capture.WATERMARK_PATH,
            analyze_inbox.VAULT,
            analyze_inbox.INBOX,
            analyze_inbox.CONVERSATIONS,
        ) = self.originals
        self.tempdir.cleanup()

    def _write_session(self, session_id, timestamps, title="Capture test"):
        session_dir = self.transcripts / session_id / ".system_generated" / "logs"
        session_dir.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": timestamps[0],
                "content": f"<USER_REQUEST>\n{title}\n</USER_REQUEST>",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": timestamps[0],
                "content": "Initial response",
            },
            {
                "step_index": 2,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": timestamps[0],
                "content": "<USER_REQUEST>\nFirst prompt\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime\n</ADDITIONAL_METADATA>",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": timestamps[0],
                "thinking": "hidden reasoning should not appear in note",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {
                            "CommandLine": "echo hello",
                            "Cwd": "/Users/milen/dev",
                        },
                    }
                ],
                "content": "Running the command for you.",
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "status": "DONE",
                "created_at": timestamps[0],
                "content": "Output:\nhello",
            },
            {
                "step_index": 3,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": timestamps[1],
                "content": "<USER_REQUEST>\nSecond prompt\n</USER_REQUEST>",
            },
            {
                "step_index": 4,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": timestamps[1],
                "content": "Here is the second answer.",
            },
        ]
        path = session_dir / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        old = datetime(2026, 9, 2, 10, 0, tzinfo=UTC).timestamp()
        os.utime(path, (old, old))
        return path

    def test_first_run_initializes_without_backfill(self):
        self._write_session("old-session", ("2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"))
        now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)

        result = capture.sweep(now=now)

        self.assertTrue(result["initialized"])
        self.assertEqual([], result["captured"])
        self.assertEqual(now, capture.read_watermark())
        self.assertEqual([], list(self.inbox.glob("20*.md")))

    def test_capture_is_settled_deduplicated_and_readable(self):
        capture.initialize_watermark(datetime(2026, 9, 2, 12, 0, tzinfo=UTC))
        self._write_session("new-session", ("2026-09-02T13:00:00Z", "2026-09-02T14:00:00Z"))
        now = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)

        first = capture.sweep(now=now)
        second = capture.sweep(now=now)

        self.assertEqual(1, len(first["captured"]))
        self.assertEqual([], second["captured"])
        note = first["captured"][0].read_text()
        self.assertIn('session_id: "new-session"', note)
        self.assertIn("source: antigravity", note)
        self.assertIn("## You", note)
        self.assertIn("## Antigravity", note)
        self.assertIn("**Tool — run_command:**", note)
        self.assertIn("**run_command result:**", note)
        self.assertNotIn("hidden reasoning", note)
        self.assertIn("First prompt", note)
        self.assertIn("Second prompt", note)

    def test_analyzer_preserves_session_id_and_routes_source(self):
        rebuilt = analyze_inbox.rebuild(
            {
                "date": "2026-09-02",
                "source": "antigravity",
                "model": "gemini",
                "session_id": "session-123",
                "capture_revision": "2",
                "capture_until": "2026-09-02T18:00:00Z",
                "continuation_of": '"prior-note"',
            },
            {"title": "Test", "summary": "Summary", "tags": ["test"]},
            "\nBody\n",
        )

        self.assertEqual("antigravity", analyze_inbox.SOURCE_DEST["antigravity"])
        self.assertIn("session_id: session-123", rebuilt)
        self.assertIn("capture_revision: 2", rebuilt)
        self.assertIn("capture_until: 2026-09-02T18:00:00Z", rebuilt)
        self.assertIn('continuation_of: "prior-note"', rebuilt)

    def test_resumed_session_creates_delta_continuation(self):
        capture.initialize_watermark(datetime(2026, 9, 2, 12, 0, tzinfo=UTC))
        transcript = self._write_session(
            "resumed-session",
            ("2026-09-02T13:00:00Z", "2026-09-02T14:00:00Z"),
        )
        first = capture.sweep(now=datetime(2026, 9, 2, 20, 0, tzinfo=UTC))
        filed = self.vault / "01-conversations" / "antigravity" / "filed-original.md"
        filed.parent.mkdir(parents=True)
        first["captured"][0].rename(filed)

        resumed = [
            {
                "step_index": 5,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-09-03T08:00:00Z",
                "content": "<USER_REQUEST>\nResumed prompt\n</USER_REQUEST>",
            },
            {
                "step_index": 6,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-09-03T08:01:00Z",
                "content": "Resumed answer",
            },
        ]
        with transcript.open("a") as handle:
            handle.write("\n".join(json.dumps(record) for record in resumed) + "\n")
        old = datetime(2026, 9, 3, 9, 0, tzinfo=UTC).timestamp()
        os.utime(transcript, (old, old))

        second = capture.sweep(now=datetime(2026, 9, 3, 14, 0, tzinfo=UTC))

        self.assertEqual(1, len(second["captured"]))
        note = second["captured"][0].read_text()
        self.assertIn("capture_revision: 2", note)
        self.assertIn('continuation_of: "filed-original"', note)
        self.assertIn("[[filed-original]]", note)
        self.assertIn("Resumed prompt", note)
        self.assertIn("Resumed answer", note)
        self.assertNotIn("First prompt", note)

    def test_body_never_emits_a_live_wikilink(self):
        records = [
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-09-02T13:00:00Z",
                "content": "<USER_REQUEST>\nhello\n</USER_REQUEST>",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "status": "DONE",
                "created_at": "2026-09-02T13:01:00Z",
                "content": "saved to [[resume-grad-date-variants]]",
            },
        ]
        body = capture.render_messages(records)
        self.assertIn("`[[resume-grad-date-variants]]`", body)
        self.assertNotIn(" [[resume-grad-date-variants]]", body)

    def test_title_uses_summary_db_when_available(self):
        db_path = capture.SUMMARY_DB
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE conversation_summaries (conversation_id TEXT PRIMARY KEY, title TEXT, workspace_uris TEXT);"
        )
        cur.execute(
            "INSERT INTO conversation_summaries VALUES ('sess-xyz', 'Custom Database Title', '[\"file:///Users/milen/dev\"]');"
        )
        conn.commit()
        conn.close()

        records = [
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "status": "DONE",
                "created_at": "2026-09-02T13:00:00Z",
                "content": "<USER_REQUEST>\nsome prompt\n</USER_REQUEST>",
            }
        ]
        title = capture._session_title(records, session_id="sess-xyz", db_path=db_path)
        self.assertEqual("Custom Database Title", title)

        project = capture._session_project(records, session_id="sess-xyz", db_path=db_path)
        self.assertEqual("dev", project)


if __name__ == "__main__":
    unittest.main()
