#!/usr/bin/env python3
"""Unit tests for scripts/submit_via_connector.py.

Verifies the connector (Option A) input is built in the same canonical shape as
the Option B artifact: a canonical question string (DAAS-167) and canonical
guidance picklist values (DAAS-168), so both submit paths agree.

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aae_common import GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL  # noqa: E402
from submit_via_connector import build_connector_payload  # noqa: E402

EM = "\u2014"


class BuildConnectorPayloadTest(unittest.TestCase):
    def test_list_question_canonicalized_to_string(self):
        payload = {
            "resolution": "Phone",
            "driver": "Board ask.",
            "question": [
                f"Cyberattacks {EM} What is our exposure?",
                "Reporting: How do we frame the risk?",
            ],
            "guidance": ["Strategic", "Technical"],
            "expedite_request": False,
        }
        out = build_connector_payload(payload, "idem-1")
        self.assertEqual(
            out["question"],
            "1. What is our exposure?\n2. How do we frame the risk?",
        )
        self.assertIsInstance(out["question"], str)

    def test_guidance_normalized_to_canonical_array(self):
        payload = {
            "resolution": "Phone",
            "driver": "Board ask.",
            "question": ["Q1?", "Q2?", "Q3?"],
            "guidance": ["Strategic", "Technical"],
            "expedite_request": False,
        }
        out = build_connector_payload(payload, "idem-2")
        self.assertEqual(out["guidance"], [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL])

    def test_idempotency_key_passed_through(self):
        payload = {
            "resolution": "Phone",
            "driver": "Board ask.",
            "question": ["Q1?", "Q2?", "Q3?"],
            "guidance": ["Strategic"],
            "expedite_request": False,
        }
        out = build_connector_payload(payload, "idem-3")
        self.assertEqual(out["idempotency_key"], "idem-3")


if __name__ == "__main__":
    unittest.main()
