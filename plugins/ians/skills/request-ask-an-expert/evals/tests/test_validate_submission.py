#!/usr/bin/env python3
"""Unit tests for scripts/validate_submission.py.

Covers the required-field gate, including the DAAS-167/168/169 additions:
  - list-shape and sub-labelled question acceptance + counting,
  - canonical + alias guidance acceptance with a normalization warning,
  - placeholder_unfilled rejection on driver / question items / guidance / deadline.

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import pathlib
import sys
import unittest
from datetime import date

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aae_common import GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL  # noqa: E402
from validate_submission import validate  # noqa: E402

TODAY = date(2026, 6, 1)
WHOAMI = {"user": {"email": "dparizher@iansresearch.com"}}
EM = "\u2014"


def base_phone_payload(**overrides):
    payload = {
        "resolution": "Phone",
        "driver": "The board wants a defensible position on nation-state risk before the next meeting.",
        "question": ["What is our exposure?", "How do we prioritize?", "How do we report it?"],
        "guidance": [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL],
        "expedite_request": False,
    }
    payload.update(overrides)
    return payload


def codes(result, field=None):
    return [
        e["code"]
        for e in result["errors"]
        if field is None or e["field"] == field
    ]


class ValidPayloadTest(unittest.TestCase):
    def test_canonical_phone_payload_is_valid(self):
        result = validate(base_phone_payload(), WHOAMI, TODAY)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_list_shape_question_counts_correctly(self):
        # 3 list items satisfy the Phone 3-5 range (DAAS-167).
        result = validate(base_phone_payload(), WHOAMI, TODAY)
        self.assertNotIn("too_few", codes(result, "question"))
        self.assertNotIn("too_many", codes(result, "question"))

    def test_sublabelled_string_question_counts_after_canonicalization(self):
        raw = (
            f"1. Cyberattacks {EM} What is our exposure?\n"
            f"2. Energy {EM} How do we prioritize?\n"
            f"3. Reporting {EM} How do we report it?"
        )
        result = validate(base_phone_payload(question=raw), WHOAMI, TODAY)
        self.assertTrue(result["valid"], result["errors"])


class QuestionCountTest(unittest.TestCase):
    def test_too_few_for_phone(self):
        result = validate(
            base_phone_payload(question=["Only one?", "Two?"]), WHOAMI, TODAY
        )
        self.assertIn("too_few", codes(result, "question"))

    def test_too_many_for_phone(self):
        result = validate(
            base_phone_payload(question=[f"Q{i}?" for i in range(6)]), WHOAMI, TODAY
        )
        self.assertIn("too_many", codes(result, "question"))

    def test_faculty_poll_one_to_three(self):
        payload = {
            "resolution": "Faculty Poll",
            "driver": "Quick read on how peers handle this.",
            "question": ["How common is this approach among peers?"],
            "expedite_request": False,
        }
        result = validate(payload, WHOAMI, TODAY)
        self.assertTrue(result["valid"], result["errors"])


class GuidanceTest(unittest.TestCase):
    def test_short_form_accepted_with_normalization_warning(self):
        result = validate(base_phone_payload(guidance=["Strategic"]), WHOAMI, TODAY)
        self.assertTrue(result["valid"], result["errors"])
        warn_codes = [w["code"] for w in result["warnings"] if w["field"] == "guidance"]
        self.assertIn("normalized", warn_codes)

    def test_canonical_form_has_no_normalization_warning(self):
        result = validate(base_phone_payload(), WHOAMI, TODAY)
        warn_codes = [w["code"] for w in result["warnings"] if w["field"] == "guidance"]
        self.assertNotIn("normalized", warn_codes)

    def test_unknown_guidance_value_rejected(self):
        result = validate(base_phone_payload(guidance=["Bogus"]), WHOAMI, TODAY)
        self.assertIn("invalid_value", codes(result, "guidance"))

    def test_missing_guidance_for_phone(self):
        result = validate(base_phone_payload(guidance=[]), WHOAMI, TODAY)
        self.assertIn("missing", codes(result, "guidance"))

    def test_guidance_forbidden_for_faculty_poll(self):
        payload = {
            "resolution": "Faculty Poll",
            "driver": "Peer read.",
            "question": ["How common is this?"],
            "guidance": [GUIDANCE_STRATEGIC],
            "expedite_request": False,
        }
        result = validate(payload, WHOAMI, TODAY)
        self.assertIn("not_allowed", codes(result, "guidance"))


class PlaceholderUnfilledTest(unittest.TestCase):
    def test_driver_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                driver="[needs your input \u2014 what's driving this for you right now?]"
            ),
            WHOAMI,
            TODAY,
        )
        self.assertFalse(result["valid"])
        self.assertIn("placeholder_unfilled", codes(result, "driver"))

    def test_question_list_item_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                question=[
                    "What is our exposure?",
                    "[needs your input \u2014 what 3-5 specific questions...]",
                    "How do we report it?",
                ]
            ),
            WHOAMI,
            TODAY,
        )
        self.assertFalse(result["valid"])
        self.assertIn("placeholder_unfilled", codes(result, "question"))

    def test_whole_question_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                question="[needs your input \u2014 what 3-5 specific questions...]"
            ),
            WHOAMI,
            TODAY,
        )
        self.assertIn("placeholder_unfilled", codes(result, "question"))

    def test_guidance_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                guidance=["[needs your input \u2014 pick Strategic, Technical, or both]"]
            ),
            WHOAMI,
            TODAY,
        )
        self.assertIn("placeholder_unfilled", codes(result, "guidance"))

    def test_deadline_placeholder_rejected_when_expedited(self):
        result = validate(
            base_phone_payload(expedite_request=True, deadline="[needs your input]"),
            WHOAMI,
            TODAY,
        )
        self.assertIn("placeholder_unfilled", codes(result, "deadline"))

    def test_details_placeholder_treated_as_empty(self):
        # An "[optional ...]" placeholder in details must not be an error.
        result = validate(
            base_phone_payload(
                details="[optional \u2014 team size, current tools, policies]"
            ),
            WHOAMI,
            TODAY,
        )
        self.assertEqual(codes(result, "details"), [])


class DeadlineTest(unittest.TestCase):
    def test_past_deadline_rejected(self):
        result = validate(
            base_phone_payload(expedite_request=True, deadline="2020-01-01"),
            WHOAMI,
            TODAY,
        )
        self.assertIn("in_past", codes(result, "deadline"))

    def test_tight_deadline_warns_not_errors(self):
        result = validate(
            base_phone_payload(expedite_request=True, deadline="2026-06-03"),
            WHOAMI,
            TODAY,
        )
        self.assertTrue(result["valid"], result["errors"])
        warn_codes = [w["code"] for w in result["warnings"] if w["field"] == "deadline"]
        self.assertIn("tight_turnaround", warn_codes)


if __name__ == "__main__":
    unittest.main()
