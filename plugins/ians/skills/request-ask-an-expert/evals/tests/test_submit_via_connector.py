#!/usr/bin/env python3
"""Unit tests for scripts/submit_via_connector.py.

Covers connector payload canonicalization (DAAS-167/168) and graceful
connector-unavailable handling (DAAS-194).

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import json
import os
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
    shape_success,
)

FIXTURES = SKILL_ROOT / "evals" / "fixtures"

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

    def test_unknown_error_code_overrides_caller_original_error_code(self):
        out = shape_error(
            "contract_version_mismatch",
            "idem-8",
            {"original_error_code": "spoofed", "field": "x"},
        )
        self.assertEqual(out["details"]["original_error_code"], "contract_version_mismatch")
        self.assertEqual(out["details"]["field"], "x")

    def test_unknown_error_code_wraps_non_dict_details(self):
        out = shape_error("contract_version_mismatch", "idem-9", "bad payload")
        self.assertEqual(out["details"]["original_error_code"], "contract_version_mismatch")
        self.assertEqual(out["details"]["raw_details"], "bad payload")


class ShapeSuccessTest(unittest.TestCase):
    """DAAS-306: skill aligns to the connector's integration_request_id and
    drops the Salesforce case number / tracking URL it never returned."""

    def _payload(self, resolution: str = "Phone") -> dict:
        return {
            "resolution": resolution,
            "driver": "Board ask.",
            "question": ["Q1?", "Q2?", "Q3?"],
            "guidance": ["Strategic"],
            "expedite_request": False,
        }

    def test_surfaces_integration_request_id(self):
        connector_response = {
            "status": "submitted",
            "integration_request_id": "INTREQ-00012345",
            "connector_failures": [],
            "response": {"salesforceCaseConnector": {"isSuccess": True}},
        }
        out = shape_success(connector_response, "idem-success", self._payload())
        self.assertEqual(out["status"], "submitted")
        self.assertEqual(out["integration_request_id"], "INTREQ-00012345")
        self.assertEqual(out["idempotency_key"], "idem-success")

    def test_drops_case_id_and_tracking_url(self):
        # Even if a stale connector echoed these, the skill no longer surfaces them.
        connector_response = {
            "integration_request_id": "INTREQ-1",
            "case_id": "00012345",
            "tracking_url": "https://example.invalid/cases/00012345",
        }
        out = shape_success(connector_response, "idem-1", self._payload())
        self.assertNotIn("case_id", out)
        self.assertNotIn("tracking_url", out)

    def test_response_window_computed_client_side_when_absent(self):
        out = shape_success({"integration_request_id": "x"}, "idem-2", self._payload("Faculty Poll"))
        self.assertEqual(out["expected_response_window"]["resolution"], "Faculty Poll")
        self.assertEqual(out["expected_response_window"]["business_days_min"], 4)
        self.assertEqual(out["expected_response_window"]["business_days_max"], 6)

    def test_null_integration_request_id_preserved_as_none(self):
        out = shape_success({}, "idem-3", self._payload())
        self.assertIsNone(out["integration_request_id"])


class SubmitViaConnectorCliTest(unittest.TestCase):
    def _run_script(self, *extra_args: str, env: dict | None = None) -> dict:
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
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)

    def test_mock_tool_not_registered_returns_connector_unavailable(self):
        out = self._run_script("--mock-tool-not-registered")
        self.assertEqual(out["status"], "connector_unavailable")
        self.assertEqual(out["options"], GRACEFUL_FAILURE_OPTIONS)

    def test_mock_success_surfaces_integration_request_id(self):
        env = {**os.environ, "IANS_REQUEST_AAE_AVAILABLE": "1"}
        out = self._run_script(
            "--mock-response",
            str(FIXTURES / "mock-connector-success.json"),
            env=env,
        )
        self.assertEqual(out["status"], "submitted")
        self.assertEqual(out["integration_request_id"], "INTREQ-00012345")
        self.assertNotIn("case_id", out)
        self.assertNotIn("tracking_url", out)
        self.assertIn("expected_response_window", out)
        self.assertTrue(out["idempotency_key"])


if __name__ == "__main__":
    unittest.main()
