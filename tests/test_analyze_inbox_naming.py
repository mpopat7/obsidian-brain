import unittest
import tempfile
from pathlib import Path
from unittest import mock

from scripts.analyze_inbox import _filed_name, _summary_slug
from scripts import analyze_inbox


class FiledNameTest(unittest.TestCase):
    """Triage must replace the capture's topic slug, not append a second one."""

    def test_replaces_the_topic_a_converter_already_wrote(self):
        self.assertEqual(
            _filed_name("2026-08-12-claude-code-log-an-application-to-internship-tracker",
                        "log-application-internship-tracker"),
            "2026-08-12-claude-code-log-application-internship-tracker.md",
        )

    def test_appends_when_quickadd_wrote_no_topic(self):
        # QuickAdd names a claude.ai capture "<date>-claude-ai" and nothing more.
        self.assertEqual(
            _filed_name("2026.08.10-14.46.54-claude-ai", "openai-codex-mcp-herdr"),
            "2026.08.10-14.46.54-claude-ai-openai-codex-mcp-herdr.md",
        )

    def test_keeps_the_continuation_marker(self):
        self.assertEqual(
            _filed_name("2026-08-13-claude-code-resume-open-code-setup-continued-2",
                        "opencode-setup-continuation"),
            "2026-08-13-claude-code-opencode-setup-continuation-continued-2.md",
        )

    def test_codex_source_token(self):
        self.assertEqual(
            _filed_name("2026-08-11-codex-lets-continue-with-the-algoverse-project",
                        "algoverse-project-progress"),
            "2026-08-11-codex-algoverse-project-progress.md",
        )

    def test_antigravity_source_token(self):
        self.assertEqual(
            _filed_name("2026-09-02-antigravity-lets-implement-the-business-minor",
                        "business-minor-implementation"),
            "2026-09-02-antigravity-business-minor-implementation.md",
        )

    def test_no_slug_means_no_rename(self):
        self.assertIsNone(_filed_name("2026-08-12-claude-code-anything", ""))

    def test_name_stays_short(self):
        stem = "2026-08-12-claude-code-" + "very-long-original-topic-" * 4
        name = _filed_name(stem, _summary_slug("Log an application to internship tracker"))
        self.assertLess(len(name), 70)


class ContinuationRenameTest(unittest.TestCase):
    def test_filing_parent_repoints_both_child_pointers_only_in_capture_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            vault = Path(folder)
            inbox = vault / "00-inbox"
            conversations = vault / "01-conversations"
            child_folder = conversations / "claude-code"
            decisions = vault / "06-decisions"
            inbox.mkdir()
            child_folder.mkdir(parents=True)
            decisions.mkdir()

            old_stem = "2026-08-20-claude-code-old-topic"
            new_stem = "2026-08-20-claude-code-new-topic"
            parent = inbox / f"{old_stem}.md"
            parent.write_text(
                "---\ndate: 2026-08-20\nsource: claude-code\nmodel: test\n"
                "session_id: session-123\ncapture_revision: 1\n---\nParent body.\n"
            )
            child_text = (
                "---\ndate: 2026-08-21\nsource: claude-code\nmodel: test\n"
                "session_id: session-123\ncapture_revision: 2\n"
                f'continuation_of: "{old_stem}"\n---\n'
                f"> Continuation of [[{old_stem}]].\n\nChild body.\n"
            )
            child = child_folder / "child-continued-2.md"
            child.write_text(child_text)
            decision = decisions / "history.md"
            decision.write_text(child_text)

            originals = (analyze_inbox.VAULT, analyze_inbox.INBOX,
                         analyze_inbox.CONVERSATIONS)
            analyze_inbox.VAULT = vault
            analyze_inbox.INBOX = inbox
            analyze_inbox.CONVERSATIONS = conversations
            try:
                with mock.patch.object(analyze_inbox, "analyze", return_value={
                    "title": "New Topic", "summary": "Summary", "tags": ["test"]
                }):
                    result = analyze_inbox.analyze_inbox()
            finally:
                (analyze_inbox.VAULT, analyze_inbox.INBOX,
                 analyze_inbox.CONVERSATIONS) = originals

            filed = child_folder / f"{new_stem}.md"
            self.assertTrue(filed.exists())
            self.assertIn('continuation_of: "{}"'.format(new_stem), child.read_text())
            self.assertIn("> Continuation of [[{}]].".format(new_stem), child.read_text())
            self.assertEqual(child_text, decision.read_text())
            # Filing now also routes the note to a hub, so the outcome line
            # carries the chosen hub and tier after the destination path.
            self.assertTrue(
                result[parent.name].startswith(
                    "ANALYZED -> claude-code/{}.md".format(new_stem)),
                result[parent.name],
            )


if __name__ == "__main__":
    unittest.main()
