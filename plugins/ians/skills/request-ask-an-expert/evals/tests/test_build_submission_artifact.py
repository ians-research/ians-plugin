#!/usr/bin/env python3
"""Unit tests for scripts/build_submission_artifact.py.

Covers the form-submission shape plus the DAAS-167/168 additions:
  - question canonicalization from a list[str] or sub-labelled string,
  - guidance emitted as the canonical semicolon-delimited picklist labels.

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_submission_artifact import transform_to_form_submission  # noqa: E402

EM = "\u2014"
WHOAMI = {"user": {"email": "dparizher@iansresearch.com"}}

EXPECTED_KEYS = {
    "resolution",
    "driver",
    "question",
    "details",
    "guidance",
    "expedite_request",
    "deadline",
    "preferred_method",
    "email_address",
    "phone_number",
    "alt_phone_number",
    "availability",
    "calendarlink",
    "expectedCallLength",
    "isUndecided",
    "origin",
    "ask_ians_id",
}


def phone_payload(**overrides):
    payload = {
        "resolution": "Phone",
        "driver": "Board wants a position on nation-state risk.",
        "question": ["What is our exposure?", "How do we prioritize?", "How do we report?"],
        "guidance": ["Strategic", "Technical"],
        "expedite_request": True,
        "deadline": "2026-06-24",
        "details": "Team of 8, AWS-primary.",
        "availability": "Tue/Thu afternoons ET",
        "calendarlink": "https://calendly.com/dparizher",
    }
    payload.update(overrides)
    return payload


class ArtifactShapeTest(unittest.TestCase):
    def test_top_level_keys_match_form(self):
        out = transform_to_form_submission(phone_payload(), "Claude", WHOAMI)
        self.assertEqual(set(out.keys()), EXPECTED_KEYS)

    def test_phone_variant_fields(self):
        out = transform_to_form_submission(phone_payload(), "Claude", WHOAMI)
        self.assertEqual(out["preferred_method"], "Phone")
        self.assertEqual(out["expectedCallLength"], "60 Minutes")
        self.assertFalse(out["isUndecided"])
        self.assertEqual(out["origin"], "IANS MCP Claude")
        self.assertEqual(out["email_address"], "dparizher@iansresearch.com")
        self.assertIsNone(out["phone_number"])
        self.assertIsNone(out["alt_phone_number"])

    def test_faculty_poll_empties_are_empty_strings(self):
        out = transform_to_form_submission(
            phone_payload(resolution="Faculty Poll", guidance=["Strategic"]),
            "Claude",
            WHOAMI,
        )
        self.assertEqual(out["details"], "")
        self.assertEqual(out["guidance"], "")
        self.assertEqual(out["availability"], "")
        self.assertEqual(out["calendarlink"], "")
        self.assertEqual(out["preferred_method"], "Email")
        self.assertIsNone(out["expectedCallLength"])


class QuestionCanonicalizationTest(unittest.TestCase):
    def test_list_question_serialized_canonically(self):
        out = transform_to_form_submission(phone_payload(), "Claude", WHOAMI)
        self.assertEqual(
            out["question"],
            "1. What is our exposure?\n2. How do we prioritize?\n3. How do we report?",
        )

    def test_sublabels_stripped_in_artifact(self):
        raw = [
            f"Cyberattacks {EM} What is our exposure?",
            "Energy & Supply Chain: How do we prioritize?",
        ]
        out = transform_to_form_submission(phone_payload(question=raw), "Claude", WHOAMI)
        self.assertEqual(
            out["question"],
            "1. What is our exposure?\n2. How do we prioritize?",
        )


class GuidanceCanonicalizationTest(unittest.TestCase):
    def test_short_form_normalized_to_canonical(self):
        out = transform_to_form_submission(phone_payload(), "Claude", WHOAMI)
        self.assertEqual(out["guidance"], "Strategic / Executive;Technical / Tactical")

    def test_canonical_form_round_trips(self):
        out = transform_to_form_submission(
            phone_payload(guidance=["Technical / Tactical"]), "Claude", WHOAMI
        )
        self.assertEqual(out["guidance"], "Technical / Tactical")


if __name__ == "__main__":
    unittest.main()
