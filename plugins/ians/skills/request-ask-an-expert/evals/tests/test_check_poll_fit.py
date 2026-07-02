#!/usr/bin/env python3
"""Unit tests for scripts/check_poll_fit.py.

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_poll_fit import NUDGE_TEXT, check_poll_fit  # noqa: E402

EM = "\u2014"


class PollFitTest(unittest.TestCase):
    def test_short_scan_poll_does_not_nudge(self):
        result = check_poll_fit(
            [
                "How common is MFA enforcement among peers?",
                "What rollout timeline do most firms use?",
            ]
        )
        self.assertFalse(result["suggest_phone"])
        self.assertEqual(result["nudge"], "")

    def test_decision_oriented_questions_nudge(self):
        result = check_poll_fit(
            [
                "Should we adopt a zero-trust architecture this year?",
                "Which approach fits a mid-size financial services firm?",
                "How should we prioritize identity vs network controls?",
            ]
        )
        self.assertTrue(result["suggest_phone"])
        self.assertIn("decision_oriented", result["matched_signals"])
        self.assertEqual(result["nudge"], NUDGE_TEXT)

    def test_multi_topic_sublabels_nudge(self):
        result = check_poll_fit(
            [
                f"Cyberattacks {EM} How exposed are we?",
                f"Supply chain {EM} How do we prioritize vendors?",
                f"Reporting {EM} How do we frame board risk?",
            ]
        )
        self.assertTrue(result["suggest_phone"])
        self.assertIn("multi_topic", result["matched_signals"])

    def test_long_context_in_driver_nudges(self):
        driver = (
            "We are preparing for a board conversation.\n\n"
            "The audit committee wants a defensible position.\n\n"
            "Legal is involved because of prior incidents."
        )
        result = check_poll_fit(["How should we respond?"], driver=driver)
        self.assertTrue(result["suggest_phone"])
        self.assertIn("long_context", result["matched_signals"])


class CheckPollFitCliTest(unittest.TestCase):
    def test_non_object_json_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = pathlib.Path(tmp) / "input.json"
            input_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "check_poll_fit.py"),
                    "--input",
                    str(input_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("must be an object", proc.stderr)


if __name__ == "__main__":
    unittest.main()
