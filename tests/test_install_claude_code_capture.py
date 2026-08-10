import tempfile
import unittest
from pathlib import Path

from scripts import install_claude_code_capture as installer


class CaptureLaunchAgentTests(unittest.TestCase):
    def test_plist_runs_only_capture_runner_hourly(self):
        with tempfile.TemporaryDirectory() as tempdir:
            home = Path(tempdir)
            config = installer.build_plist("/usr/bin/python3", home)

        self.assertEqual(installer.LABEL, config["Label"])
        self.assertEqual(3600, config["StartInterval"])
        self.assertTrue(config["RunAtLoad"])
        self.assertEqual("/usr/bin/python3", config["ProgramArguments"][0])
        self.assertTrue(config["ProgramArguments"][1].endswith("capture_chats.py"))
        self.assertNotIn("analyze_inbox.py", " ".join(config["ProgramArguments"]))
        self.assertTrue(config["StandardOutPath"].endswith("obsidian-brain-claude-code-capture.log"))


if __name__ == "__main__":
    unittest.main()
