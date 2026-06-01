#!/usr/bin/env python3
"""Unit tests for scripts/submit_via_connector.py.

Covers connector payload canonicalization (DAAS-167/168) and graceful
connector-unavailable handling (DAAS-194).

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
SKILL_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from aae_common import GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL  # noqa: E402
from submit_via_connector import (  # noqa: E402
    GRACEFUL_FAILURE_OPTIONS,
    build_connector_payload,
    shape_connector_unavailable,
    shape_error,
)

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


class GracefulFailureTest(unittest.TestCase):
    def test_shape_connector_unavailable_includes_options(self):
        out = shape_connector_unavailable("tool missing", "idem-4")
        self.assertEqual(out["status"], "connector_unavailable")
        self.assertEqual(out["options"], GRACEFUL_FAILURE_OPTIONS)
        self.assertTrue(out["retryable"])
        self.assertIn("user_message", out)

    def test_server_error_maps_to_connector_unavailable(self):
        out = shape_error("server_error", "idem-5")
        self.assertEqual(out["status"], "connector_unavailable")
        self.assertEqual(out["options"], GRACEFUL_FAILURE_OPTIONS)

    def test_validation_failed_stays_error(self):
        out = shape_error("validation_failed", "idem-6", {"driver": "too long"})
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], "validation_failed")

    def test_unknown_error_code_stays_error_not_unavailable(self):
        out = shape_error("contract_version_mismatch", "idem-7", {"field": "x"})
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["error_code"], "contract_version_mismatch")
        self.assertFalse(out["retryable"])
        self.assertEqual(out["details"]["original_error_code"], "contract_version_mismatch")
        self.assertEqual(out["details"]["field"], "x")
        self.assertNotIn("options", out)


class SubmitViaConnectorCliTest(unittest.TestCase):
    def _run_script(self, *extra_args: str) -> dict:
        payload = {
            "resolution": "Phone",
            "driver": "Board ask.",
            "question": ["Q1?", "Q2?", "Q3?"],
            "guidance": ["Strategic"],
            "expedite_request": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = pathlib.Path(tmp) / "payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            cmd = [
                sys.executable,
                str(SCRIPTS / "submit_via_connector.py"),
                "--payload",
                str(payload_path),
                *extra_args,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)

    def test_mock_tool_not_registered_returns_connector_unavailable(self):
        out = self._run_script("--mock-tool-not-registered")
        self.assertEqual(out["status"], "connector_unavailable")
        self.assertEqual(out["options"], GRACEFUL_FAILURE_OPTIONS)


if __name__ == "__main__":
    unittest.main()
