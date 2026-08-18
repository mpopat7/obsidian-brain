import unittest

from scripts.analyze_inbox import _filed_name, _summary_slug


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

    def test_no_slug_means_no_rename(self):
        self.assertIsNone(_filed_name("2026-08-12-claude-code-anything", ""))

    def test_name_stays_short(self):
        stem = "2026-08-12-claude-code-" + "very-long-original-topic-" * 4
        name = _filed_name(stem, _summary_slug("Log an application to internship tracker"))
        self.assertLess(len(name), 70)


if __name__ == "__main__":
    unittest.main()
