import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.repair_continuations import find_repairs


SCRIPT = Path(__file__).parents[1] / "scripts" / "repair_continuations.py"


def capture_text(session_id, revision, continuation=None):
    lines = [
        "---",
        'session_id: "{}"'.format(session_id),
        "capture_revision: {}".format(revision),
    ]
    if continuation:
        lines.append('continuation_of: "{}"'.format(continuation))
    lines.append("---")
    if continuation:
        lines.extend(["> Continuation of [[{}]].".format(continuation), ""])
    lines.extend(["Body.", ""])
    return "\n".join(lines)


class RepairContinuationsTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.vault = Path(self.tempdir.name)
        self.captures = self.vault / "01-conversations" / "claude-code"
        self.captures.mkdir(parents=True)
        self.parent = self.captures / "filed-parent.md"
        self.parent.write_text(capture_text("session-123", 1))
        self.child = self.captures / "child-continued-2.md"
        self.child.write_text(capture_text("session-123", 2, "stale-parent"))

    def tearDown(self):
        self.tempdir.cleanup()

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.vault), *args],
            text=True, capture_output=True, check=False,
        )

    def test_default_is_dry_run_and_apply_is_idempotent(self):
        original = self.child.read_text()

        dry_run = self.run_script()

        self.assertEqual(0, dry_run.returncode, dry_run.stderr)
        self.assertIn("would repair 1 broken continuation capture(s); 0 unresolved",
                      dry_run.stdout)
        self.assertEqual(original, self.child.read_text())

        applied = self.run_script("--apply")
        self.assertEqual(0, applied.returncode, applied.stderr)
        self.assertIn("repaired 1 broken continuation capture(s); 0 unresolved",
                      applied.stdout)
        repaired = self.child.read_text()
        self.assertIn('continuation_of: "filed-parent"', repaired)
        self.assertIn("> Continuation of [[filed-parent]].\n\nBody.", repaired)

        second = self.run_script("--apply")
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertIn("repaired 0 broken continuation capture(s); 0 unresolved",
                      second.stdout)
        self.assertEqual(repaired, self.child.read_text())

    def test_only_conversation_captures_are_candidates(self):
        decision = self.vault / "06-decisions" / "append-only.md"
        curated = self.vault / "02-knowledge" / "curated.md"
        decision.parent.mkdir()
        curated.parent.mkdir()
        decision.write_text(capture_text("decision-session", 2, "missing"))
        curated.write_text(capture_text("curated-session", 2, "missing"))

        repairs, unresolved = find_repairs(self.vault)

        self.assertEqual([self.child], [repair.child.path for repair in repairs])
        self.assertEqual([], unresolved)
        self.assertIn("missing", decision.read_text())
        self.assertIn("missing", curated.read_text())


if __name__ == "__main__":
    unittest.main()
