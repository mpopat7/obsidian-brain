import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_vault


class CheckVaultContinuationTest(unittest.TestCase):
    def test_continuation_banner_must_resolve(self):
        with tempfile.TemporaryDirectory() as folder:
            vault = Path(folder)
            captures = vault / "01-conversations" / "claude-code"
            captures.mkdir(parents=True)
            parent = captures / "current-parent.md"
            child = captures / "child.md"
            parent.write_text("Parent.\n")
            child.write_text("> Continuation of [[current-parent]].\n")

            def walk():
                return list(vault.rglob("*.md"))

            original_vault = check_vault.VAULT
            check_vault.VAULT = str(vault)
            try:
                with mock.patch.object(check_vault.brain_mcp, "_walk", side_effect=walk):
                    self.assertTrue(check_vault.check_ghosts())
                    parent.unlink()
                    self.assertFalse(check_vault.check_ghosts())
            finally:
                check_vault.VAULT = original_vault


if __name__ == "__main__":
    unittest.main()
