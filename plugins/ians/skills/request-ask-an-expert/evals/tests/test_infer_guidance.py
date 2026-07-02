#!/usr/bin/env python3
"""Unit tests for scripts/infer_guidance.py.

Verifies the inference emits the canonical picklist labels rather
than the short form, and still returns an empty array when ambiguous.

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aae_common import GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL  # noqa: E402
from infer_guidance import infer  # noqa: E402


class InferGuidanceTest(unittest.TestCase):
    def test_strategic_signal_returns_canonical_label(self):
        result = infer("How do I present our security budget to the board and CFO?")
        self.assertEqual(result["guidance"], [GUIDANCE_STRATEGIC])

    def test_technical_signal_returns_canonical_label(self):
        result = infer("How should we configure our SIEM detection rules and tune EDR?")
        self.assertEqual(result["guidance"], [GUIDANCE_TECHNICAL])

    def test_both_signals_return_both_canonical_labels(self):
        result = infer(
            "We're selecting a SIEM and need to align the budget with the board's "
            "risk appetite while designing the detection architecture."
        )
        self.assertEqual(result["guidance"], [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL])

    def test_ambiguous_returns_empty_array(self):
        result = infer("Tell me about cybersecurity.")
        self.assertEqual(result["guidance"], [])

    def test_no_short_form_leaks(self):
        result = infer("Board budget and SIEM configuration architecture.")
        for value in result["guidance"]:
            self.assertIn(value, (GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL))
            self.assertIn("/", value)


if __name__ == "__main__":
    unittest.main()
