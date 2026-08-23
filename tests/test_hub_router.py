import tempfile
import unittest
from pathlib import Path

from scripts import hub_router
from scripts.analyze_inbox import add_hub_link


def capture(tags=(), title="", summary="", project="", body="Body.", links=()):
    front = ["---", "title: {}".format(title), "summary: {}".format(summary),
             "tags: [{}]".format(", ".join(tags))]
    if project:
        front.append('project: "{}"'.format(project))
    front.append("---")
    text = "\n".join(front) + "\n" + body + "\n"
    for link in links:
        text += "- [[{}]]\n".format(link)
    return text


class VaultFixture(unittest.TestCase):
    """A small synthetic vault: four hubs and three notes of tag history."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.vault = Path(self.tempdir.name)
        for folder in ("01-conversations", "02-knowledge", "03-projects", "05-context"):
            (self.vault / folder).mkdir(parents=True)

        (self.vault / "02-knowledge" / "nutrition-and-training.md").write_text(
            "---\ntags: [food]\n---\nProtein macros and lifting.\n")
        (self.vault / "02-knowledge" / "unrouted-captures.md").write_text(
            "---\ntags: [triage]\n---\nHolding hub.\n")
        (self.vault / "02-knowledge" / "mcp-server-management.md").write_text(
            "---\ntags: [mcp]\n---\n" + "mcp servers manifest sync mcp mcp\n" * 4)
        (self.vault / "03-projects" / "obsidian-brain.md").write_text(
            "---\ntags: [vault]\n---\nThe vault pipeline.\n")

        # History: three filed notes tie the `protein` tag to the nutrition hub.
        for i in range(3):
            (self.vault / "01-conversations" / "hist-{}.md".format(i)).write_text(
                capture(tags=["protein"], links=["nutrition-and-training"]))

        self.router = hub_router.Router(self.vault)

    def tearDown(self):
        self.tempdir.cleanup()


class HubRouterTest(VaultFixture):
    def test_history_tier_routes_a_known_tag(self):
        hub, _, tier = self.router.route(["protein"])
        self.assertEqual(hub, "nutrition-and-training")
        self.assertEqual(tier, "history")

    def test_project_frontmatter_routes_when_it_names_a_real_hub(self):
        hub, _, tier = self.router.route(["whatever"], project="obsidian-brain")
        self.assertEqual(hub, "obsidian-brain")
        self.assertEqual(tier, "project")

    def test_project_naming_a_git_repo_does_not_route(self):
        """`project:` is usually a repo name ("dev", "memory"), not a vault hub."""
        hub, _, _ = self.router.route([], project="dev")
        self.assertEqual(hub, hub_router.FLOOR_HUB)

    def test_mention_tier_handles_brand_new_tags(self):
        """Cold start: no tag history, so the hub's own vocabulary decides.

        Takes several matching terms to clear MIN_SCORE, which is deliberate —
        one loose word matching one hub is not evidence. Real captures carry
        3-6 tags, which is what this mirrors.
        """
        hub, _, tier = self.router.route(["mcp", "servers", "manifest", "sync"])
        self.assertEqual(hub, "mcp-server-management")
        self.assertEqual(tier, "mention")

    def test_a_single_loose_term_is_not_enough_to_commit(self):
        hub, _, tier = self.router.route(["mcp"])
        self.assertEqual(hub, hub_router.FLOOR_HUB)

    def test_untagged_note_goes_to_the_floor_not_a_guess(self):
        hub, confidence, tier = self.router.route(
            [], title="some words", summary="more prose here")
        self.assertEqual(hub, hub_router.FLOOR_HUB)
        self.assertEqual(tier, "floor")
        self.assertEqual(confidence, 0.0)

    def test_unknown_tag_goes_to_the_floor(self):
        hub, _, tier = self.router.route(["zzz-nothing-matches-this"])
        self.assertEqual(hub, hub_router.FLOOR_HUB)
        self.assertEqual(tier, "floor")

    def test_router_never_returns_a_hub_that_does_not_exist(self):
        for tags in ([], ["protein"], ["mcp"], ["unknown"]):
            hub, _, _ = self.router.route(tags)
            self.assertIn(hub, self.router.hubs)


class AddHubLinkTest(VaultFixture):
    def test_appends_a_links_section(self):
        text, hub, tier = add_hub_link(capture(tags=["protein"]), self.router)
        self.assertEqual(hub, "nutrition-and-training")
        self.assertIn("## Links", text)
        self.assertIn("[[nutrition-and-training]]", text)
        self.assertIn("<!-- routed: history", text)

    def test_curated_link_is_never_overwritten(self):
        original = capture(tags=["protein"], links=["obsidian-brain"])
        text, hub, tier = add_hub_link(original, self.router)
        self.assertIsNone(hub)
        self.assertEqual(text, original)

    def test_is_idempotent(self):
        once, _, _ = add_hub_link(capture(tags=["protein"]), self.router)
        twice, hub, _ = add_hub_link(once, self.router)
        self.assertIsNone(hub)
        self.assertEqual(once, twice)

    def test_quoted_wikilink_does_not_count_as_a_link(self):
        """A capture quoting `[[obsidian-brain]]` in prose is still unlinked."""
        text, hub, _ = add_hub_link(
            capture(tags=["protein"], body="It said `[[obsidian-brain]]` once."),
            self.router)
        self.assertEqual(hub, "nutrition-and-training")

    def test_floor_link_still_connects_the_note(self):
        text, hub, tier = add_hub_link(capture(tags=["nothing-known"]), self.router)
        self.assertEqual(tier, "floor")
        self.assertIn("[[{}]]".format(hub_router.FLOOR_HUB), text)


if __name__ == "__main__":
    unittest.main()
