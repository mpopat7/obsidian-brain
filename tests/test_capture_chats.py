import unittest

from scripts import capture_chats


class FakeCapture:
    def __init__(self):
        self.calls = []

    def sweep(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "initialized": False,
            "would_initialize": False,
            "captured": [],
            "eligible": [],
        }


class CombinedCaptureTests(unittest.TestCase):
    def test_runner_applies_same_thresholds_to_both_sources(self):
        first = FakeCapture()
        second = FakeCapture()
        original = capture_chats.CAPTURES
        capture_chats.CAPTURES = (("First", first), ("Second", second))
        try:
            results = capture_chats.run(dry_run=True, settle_hours=4, min_turns=3)
        finally:
            capture_chats.CAPTURES = original

        expected = {"dry_run": True, "settle_hours": 4, "min_turns": 3}
        self.assertEqual([expected], first.calls)
        self.assertEqual([expected], second.calls)
        self.assertEqual({"First", "Second"}, set(results))


if __name__ == "__main__":
    unittest.main()
