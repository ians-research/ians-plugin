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
        result = validate(base_phone_payload(), TODAY)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_list_shape_question_counts_correctly(self):
        # 3 list items satisfy the Phone 3-5 range (DAAS-167).
        result = validate(base_phone_payload(), TODAY)
        self.assertNotIn("too_few", codes(result, "question"))
        self.assertNotIn("too_many", codes(result, "question"))

    def test_sublabelled_string_question_counts_after_canonicalization(self):
        raw = (
            f"1. Cyberattacks {EM} What is our exposure?\n"
            f"2. Energy {EM} How do we prioritize?\n"
            f"3. Reporting {EM} How do we report it?"
        )
        result = validate(base_phone_payload(question=raw), TODAY)
        self.assertTrue(result["valid"], result["errors"])


class QuestionCountTest(unittest.TestCase):
    def test_too_few_for_phone(self):
        result = validate(
            base_phone_payload(question=["Only one?", "Two?"]), TODAY
        )
        self.assertIn("too_few", codes(result, "question"))

    def test_too_many_for_phone(self):
        result = validate(
            base_phone_payload(question=[f"Q{i}?" for i in range(6)]), TODAY
        )
        self.assertIn("too_many", codes(result, "question"))

    def test_faculty_poll_one_to_three(self):
        payload = {
            "resolution": "Faculty Poll",
            "driver": "Quick read on how peers handle this.",
            "question": ["How common is this approach among peers?"],
            "expedite_request": False,
        }
        result = validate(payload, TODAY)
        self.assertTrue(result["valid"], result["errors"])


class GuidanceTest(unittest.TestCase):
    def test_short_form_accepted_with_normalization_warning(self):
        result = validate(base_phone_payload(guidance=["Strategic"]), TODAY)
        self.assertTrue(result["valid"], result["errors"])
        warn_codes = [w["code"] for w in result["warnings"] if w["field"] == "guidance"]
        self.assertIn("normalized", warn_codes)

    def test_canonical_form_has_no_normalization_warning(self):
        result = validate(base_phone_payload(), TODAY)
        warn_codes = [w["code"] for w in result["warnings"] if w["field"] == "guidance"]
        self.assertNotIn("normalized", warn_codes)

    def test_unknown_guidance_value_rejected(self):
        result = validate(base_phone_payload(guidance=["Bogus"]), TODAY)
        self.assertIn("invalid_value", codes(result, "guidance"))

    def test_missing_guidance_for_phone(self):
        result = validate(base_phone_payload(guidance=[]), TODAY)
        self.assertIn("missing", codes(result, "guidance"))

    def test_guidance_forbidden_for_faculty_poll(self):
        payload = {
            "resolution": "Faculty Poll",
            "driver": "Peer read.",
            "question": ["How common is this?"],
            "guidance": [GUIDANCE_STRATEGIC],
            "expedite_request": False,
        }
        result = validate(payload, TODAY)
        self.assertIn("not_allowed", codes(result, "guidance"))


class PlaceholderUnfilledTest(unittest.TestCase):
    def test_driver_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                driver="[needs your input \u2014 what's driving this for you right now?]"
            ),
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
            TODAY,
        )
        self.assertFalse(result["valid"])
        self.assertIn("placeholder_unfilled", codes(result, "question"))

    def test_whole_question_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                question="[needs your input \u2014 what 3-5 specific questions...]"
            ),
            TODAY,
        )
        self.assertIn("placeholder_unfilled", codes(result, "question"))

    def test_guidance_placeholder_rejected(self):
        result = validate(
            base_phone_payload(
                guidance=["[needs your input \u2014 pick Strategic, Technical, or both]"]
            ),
            TODAY,
        )
        self.assertIn("placeholder_unfilled", codes(result, "guidance"))

    def test_deadline_placeholder_rejected_when_expedited(self):
        result = validate(
            base_phone_payload(expedite_request=True, deadline="[needs your input]"),
            TODAY,
        )
        self.assertIn("placeholder_unfilled", codes(result, "deadline"))

    def test_details_placeholder_treated_as_empty(self):
        # An "[optional ...]" placeholder in details must not be an error.
        result = validate(
            base_phone_payload(
                details="[optional \u2014 team size, current tools, policies]"
            ),
            TODAY,
        )
        self.assertEqual(codes(result, "details"), [])


class EmailTest(unittest.TestCase):
    """DAAS-362: email is an optional reply-to override, never required.

    The connector sets the email server-side from the authenticated session and
    ians_whoami does not expose it, so a payload without an email is valid and
    no whoami input is consulted.
    """

    def test_missing_email_is_valid(self):
        payload = base_phone_payload()
        self.assertNotIn("email_address", payload)
        result = validate(payload, TODAY)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(codes(result, "email_address"), [])

    def test_valid_override_email_accepted(self):
        result = validate(
            base_phone_payload(email_address="exec.assistant@example.com"), TODAY
        )
        self.assertTrue(result["valid"], result["errors"])

    def test_malformed_override_email_rejected(self):
        result = validate(base_phone_payload(email_address="not-an-email"), TODAY)
        self.assertIn("invalid", codes(result, "email_address"))


class DeadlineTest(unittest.TestCase):
    def test_past_deadline_rejected(self):
        result = validate(
            base_phone_payload(expedite_request=True, deadline="2020-01-01"),
            TODAY,
        )
        self.assertIn("in_past", codes(result, "deadline"))

    def test_tight_deadline_warns_not_errors(self):
        result = validate(
            base_phone_payload(expedite_request=True, deadline="2026-06-03"),
            TODAY,
        )
        self.assertTrue(result["valid"], result["errors"])
        warn_codes = [w["code"] for w in result["warnings"] if w["field"] == "deadline"]
        self.assertIn("tight_turnaround", warn_codes)


if __name__ == "__main__":
    unittest.main()
