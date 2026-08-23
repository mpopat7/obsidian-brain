import tempfile
import unittest
from pathlib import Path

from scripts import satellites


def note(*links, body="Body."):
    text = ["---", "tags: [x]", "---", body]
    text.extend("- [[{}]]".format(l) for l in links)
    return "\n".join(text) + "\n"


class SatellitesTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.vault = Path(self.tempdir.name)
        for folder in ("01-conversations", "02-knowledge", "99-archive",
                       "04-templates", "00-inbox"):
            (self.vault / folder).mkdir(parents=True)
        # A connected main component: hub <- two conversations.
        (self.vault / "02-knowledge" / "hub.md").write_text(note("other-hub"))
        (self.vault / "02-knowledge" / "other-hub.md").write_text(note())
        (self.vault / "01-conversations" / "linked-a.md").write_text(note("hub"))
        (self.vault / "01-conversations" / "linked-b.md").write_text(note("hub"))

    def tearDown(self):
        self.tempdir.cleanup()

    def find(self, **kw):
        return satellites.find(vault=self.vault, **kw)

    def test_clean_vault_has_no_satellites(self):
        _, clusters, offenders = self.find()
        self.assertEqual(offenders, [])
        self.assertEqual(clusters, [])

    def test_lone_unlinked_conversation_is_a_satellite(self):
        (self.vault / "01-conversations" / "lonely.md").write_text(note())
        _, _, offenders = self.find()
        self.assertEqual(offenders, ["lonely"])

    def test_pair_linked_only_to_each_other_is_a_satellite(self):
        """The two-dot cluster: a capture and its continuation, orbiting nothing."""
        (self.vault / "01-conversations" / "parent.md").write_text(note("child"))
        (self.vault / "01-conversations" / "child.md").write_text(note("parent"))
        _, clusters, offenders = self.find()
        self.assertEqual(sorted(offenders), ["child", "parent"])
        self.assertEqual([len(c) for c in clusters], [2])

    def test_exempt_sectors_are_not_satellites(self):
        (self.vault / "99-archive" / "retired.md").write_text(note())
        (self.vault / "04-templates" / "scaffold.md").write_text(note())
        _, clusters, offenders = self.find()
        self.assertEqual(offenders, [])
        self.assertEqual(len(clusters), 2)   # still off-graph, just not defects

    def test_underscore_notes_are_exempt(self):
        (self.vault / "01-conversations" / "_about.md").write_text(note())
        _, _, offenders = self.find()
        self.assertEqual(offenders, [])

    def test_inbox_is_transient_unless_strict(self):
        (self.vault / "00-inbox" / "fresh.md").write_text(note())
        self.assertEqual(self.find()[2], [])
        self.assertEqual(self.find(strict=True)[2], ["fresh"])

    def test_wikilink_in_code_span_is_not_an_edge(self):
        """The 2026-08-18 ghost-link fix depends on this staying true."""
        (self.vault / "01-conversations" / "quoting.md").write_text(
            note(body="A shell test: `[[ -n \"$x\" ]]` and a quoted `[[hub]]`."))
        _, _, offenders = self.find()
        self.assertEqual(offenders, ["quoting"])

    def test_link_into_an_exempt_sector_still_connects(self):
        (self.vault / "99-archive" / "retired.md").write_text(note("hub"))
        (self.vault / "01-conversations" / "via-archive.md").write_text(note("retired"))
        _, _, offenders = self.find()
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
