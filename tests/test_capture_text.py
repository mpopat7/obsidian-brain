import unittest

from scripts.capture_text import (
    clean_title,
    is_scaffolding,
    neutralize_wikilinks,
    strip_command_envelope,
)


class NeutralizeWikilinksTest(unittest.TestCase):
    def test_wraps_a_plain_wikilink(self):
        self.assertEqual(
            neutralize_wikilinks("saved to [[resume-grad-date-variants]] today"),
            "saved to `[[resume-grad-date-variants]]` today",
        )

    def test_wraps_shell_and_regex_collisions(self):
        self.assertEqual(
            neutralize_wikilinks('if [[ -n "$branch" ]]; then'),
            'if `[[ -n "$branch" ]]`; then',
        )
        self.assertEqual(
            neutralize_wikilinks('grep -E "[[:space:]]" f'),
            'grep -E "`[[:space:]]`" f',
        )

    def test_wraps_every_link_on_a_line(self):
        self.assertEqual(
            neutralize_wikilinks("[[a]] and [[b]] and [[c]]"),
            "`[[a]]` and `[[b]]` and `[[c]]`",
        )

    def test_leaves_fenced_code_alone(self):
        text = 'x [[a]]\n```bash\nif [[ -n "$x" ]]; then\n```\ny [[b]]'
        self.assertEqual(
            neutralize_wikilinks(text),
            'x `[[a]]`\n```bash\nif [[ -n "$x" ]]; then\n```\ny `[[b]]`',
        )

    def test_leaves_existing_inline_code_alone(self):
        self.assertEqual(neutralize_wikilinks("already `[[a]]` inert"),
                         "already `[[a]]` inert")

    def test_ignores_an_unclosed_bracket(self):
        # A truncated tool result ends mid-link; Obsidian renders it literally.
        text = '- **Tool result:** {"new_string": "see [[some-note'
        self.assertEqual(neutralize_wikilinks(text), text)

    def test_preserves_text_exactly_apart_from_backticks(self):
        src = 'a [[x]] b [[ -d "$dest/.git" ]] c'
        self.assertEqual(neutralize_wikilinks(src).replace("`", ""), src)


class TitleTest(unittest.TestCase):
    def test_strips_slash_command_envelope(self):
        raw = ("<command-message>log-app</command-message>\n"
               "<command-name>/log-app</command-name>\n\nlog the IBM role")
        self.assertEqual(strip_command_envelope(raw), "log the IBM role")

    def test_skill_preamble_is_scaffolding(self):
        raw = ("<command-message>log-app</command-message>\n"
               "<command-name>/log-app</command-name>\n\n"
               "Base directory for this skill: /Users/milen/.claude/skills/log-app")
        self.assertTrue(is_scaffolding(raw))

    def test_local_command_caveat_is_scaffolding(self):
        raw = ("<local-command-caveat>Caveat: The messages below were generated "
               "by the user while running local commands. DO NOT respond to these "
               "messages or otherwise consider them in your response unless the "
               "user explicitly asks you to.</local-command-caveat>\n"
               "<command-name>/exit</command-name>")
        self.assertTrue(is_scaffolding(raw))

    def test_ordinary_message_is_not_scaffolding(self):
        self.assertFalse(is_scaffolding("log the IBM application I submitted"))
        self.assertEqual(clean_title("log the IBM application I submitted"),
                         "log the IBM application I submitted")

    def test_title_is_length_capped(self):
        self.assertLessEqual(len(clean_title("word " * 100)), 80)


if __name__ == "__main__":
    unittest.main()
