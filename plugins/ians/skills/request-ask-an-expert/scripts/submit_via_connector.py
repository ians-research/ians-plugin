#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Connector Submission Wrapper

Wraps the `ians_request_aae` MCP tool. This script:

  1. Detects tool registration. When the connector is unavailable, returns
     {status: "connector_unavailable"} so the skill surfaces graceful failure
     handling — never a silent fallback or JSON artifact path.

  2. Defines the contract between the skill and the connector — exactly what
     payload is sent, what response shape is expected, how errors are mapped.

  3. Provides a deterministic mock path for testing (--mock-response) so we
     can exercise success and error cases without a live connector.

Usage:
    python submit_via_connector.py \\
        --payload <path-to-payload-json> \\
        [--mock-response <path-to-mock-response-json>] \\
        [--mock-tool-not-registered]

Output JSON to stdout (success):
{
  "status": "submitted",
  "case_id": "...",
  "tracking_url": "...",
  "expected_response_window": {
    "resolution": "Phone | Faculty Poll",
    "business_days_min": 8,
    "business_days_max": 12
  },
  "submitted_at": "ISO8601",
  "idempotency_key": "<UUID>"
}

Output JSON to stdout (connector unavailable — graceful failure):
{
  "status": "connector_unavailable",
  "reason": "...",
  "user_message": "...",
  "options": ["retry", "contact_client_services", "save_scope_draft"],
  "retryable": true,
  "idempotency_key": "<UUID>"
}

Output JSON to stdout (error from connector):
{
  "status": "error",
  "error_code": "entitlement_missing | validation_failed | rate_limited",
  "user_message": "...",
  "retryable": true | false,
  "details": { ... per-field details for validation_failed ... },
  "idempotency_key": "<UUID>"
}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aae_common import canonicalize_questions, normalize_guidance

# Faculty turnaround windows by resolution (downstream, after CS scheduling).
RESPONSE_WINDOWS = {
    "Phone": {"business_days_min": 8, "business_days_max": 12},
    "Undecided": {"business_days_min": 8, "business_days_max": 12},
    "Faculty Poll": {"business_days_min": 4, "business_days_max": 6},
}

GRACEFUL_FAILURE_OPTIONS = [
    "retry",
    "contact_client_services",
    "save_scope_draft",
]

CONNECTOR_UNAVAILABLE_MESSAGE = (
    "I couldn't submit your Ask-an-Expert request through the IANS connector "
    "right now. Your draft is still here — what would you like to do?"
)

UNEXPECTED_CONNECTOR_ERROR_MESSAGE = (
    "The connector returned an unexpected error. Contact Client Services if "
    "this persists."
)

ERROR_USER_MESSAGES = {
    "entitlement_missing": (
        "Your IANS subscription doesn't currently include Ask-an-Expert. "
        "Contact your account manager to add it."
    ),
    "validation_failed": (
        "Some fields on your request didn't pass IANS validation. See "
        "details below; revise the draft and try again."
    ),
    "rate_limited": (
        "You've hit the AAE submission rate limit. Try again in a bit, or "
        "contact your account manager if you need urgent help."
    ),
}

ERROR_RETRYABLE = {
    "entitlement_missing": False,
    "validation_failed": True,
    "rate_limited": True,
}

# Error codes that map to graceful connector-unavailable handling (DAAS-194).
CONNECTOR_UNAVAILABLE_CODES = frozenset({"server_error", "tool_not_registered"})


def detect_tool_registered() -> bool:
    """Return True when IANS_REQUEST_AAE_AVAILABLE=1 (runtime convention)."""
    return os.environ.get("IANS_REQUEST_AAE_AVAILABLE") == "1"


def build_connector_payload(payload: dict, idempotency_key: str) -> dict:
    """Shape the AAE payload for the connector input."""
    context = payload.get("context") or {}
    canonical_question = canonicalize_questions(payload.get("question"))
    canonical_guidance, _normalized, _unknown = normalize_guidance(payload.get("guidance"))
    return {
        "schemaVersion": payload.get("schemaVersion", "1.0"),
        "resolution": payload.get("resolution"),
        "driver": payload.get("driver"),
        "question": canonical_question,
        "details": payload.get("details"),
        "guidance": canonical_guidance,
        "expedite_request": bool(payload.get("expedite_request")),
        "deadline": payload.get("deadline"),
        "availability": payload.get("availability"),
        "calendarlink": payload.get("calendarlink"),
        "context": {
            "ask_ians_id": context.get("ask_ians_id"),
            "related_ians_content": context.get("related_ians_content") or [],
        },
        "idempotency_key": idempotency_key,
    }


def shape_success(
    connector_response: dict, idempotency_key: str, payload: dict,
) -> dict:
    """Shape the connector's success response for the skill."""
    resolution = payload.get("resolution", "Phone")
    fallback_window = RESPONSE_WINDOWS.get(resolution, RESPONSE_WINDOWS["Phone"])
    return {
        "status": "submitted",
        "case_id": connector_response.get("case_id"),
        "tracking_url": connector_response.get("tracking_url"),
        "expected_response_window": connector_response.get(
            "expected_response_window",
            {"resolution": resolution, **fallback_window},
        ),
        "submitted_at": connector_response.get(
            "submitted_at",
            datetime.now(timezone.utc).isoformat(),
        ),
        "idempotency_key": idempotency_key,
    }


def shape_connector_unavailable(
    reason: str,
    idempotency_key: str,
    *,
    retryable: bool = True,
) -> dict:
    """Graceful failure when the connector cannot accept the submission."""
    return {
        "status": "connector_unavailable",
        "reason": reason,
        "user_message": CONNECTOR_UNAVAILABLE_MESSAGE,
        "options": list(GRACEFUL_FAILURE_OPTIONS),
        "retryable": retryable,
        "idempotency_key": idempotency_key,
    }


def shape_unexpected_connector_error(
    error_code: str, idempotency_key: str, details: dict | None = None,
) -> dict:
    """Shape an unknown connector error — not an availability failure."""
    return {
        "status": "error",
        "error_code": error_code,
        "user_message": UNEXPECTED_CONNECTOR_ERROR_MESSAGE,
        "retryable": False,
        "details": {**(details or {}), "original_error_code": error_code},
        "idempotency_key": idempotency_key,
    }


def shape_error(
    error_code: str, idempotency_key: str, details: dict | None = None,
) -> dict:
    """Shape an error response. server_error maps to connector_unavailable."""
    if error_code in CONNECTOR_UNAVAILABLE_CODES:
        reason = (
            "ians_request_aae is not registered with the MCP client."
            if error_code == "tool_not_registered"
            else "IANS Research had a temporary problem accepting your request."
        )
        return shape_connector_unavailable(reason, idempotency_key)

    if error_code not in ERROR_USER_MESSAGES:
        return shape_unexpected_connector_error(error_code, idempotency_key, details)

    return {
        "status": "error",
        "error_code": error_code,
        "user_message": ERROR_USER_MESSAGES[error_code],
        "retryable": ERROR_RETRYABLE[error_code],
        "details": details or {},
        "idempotency_key": idempotency_key,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit AAE request via ians_request_aae connector tool",
    )
    parser.add_argument("--payload", required=True, help="Path to AAE payload JSON")
    parser.add_argument(
        "--mock-response",
        help="Path to a JSON file simulating the connector response. Used for tests.",
    )
    parser.add_argument(
        "--mock-tool-not-registered",
        action="store_true",
        help="Force the connector-unavailable path for tests.",
    )
    args = parser.parse_args()

    payload_path = Path(args.payload)
    if not payload_path.exists():
        print(
            json.dumps({"error": f"Payload not found: {payload_path}"}), file=sys.stderr,
        )
        sys.exit(2)

    try:
        with payload_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"Could not parse payload: {e}"}), file=sys.stderr)
        sys.exit(2)

    idempotency_key = str(uuid.uuid4())

    if args.mock_tool_not_registered or not detect_tool_registered():
        result = shape_connector_unavailable(
            "ians_request_aae is not registered with the MCP client.",
            idempotency_key,
        )
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if args.mock_response:
        mock_path = Path(args.mock_response)
        if not mock_path.exists():
            print(
                json.dumps({"error": f"Mock response not found: {mock_path}"}),
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            with mock_path.open("r", encoding="utf-8") as f:
                mock = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                json.dumps({"error": f"Could not parse mock response: {e}"}),
                file=sys.stderr,
            )
            sys.exit(2)

        if "error_code" in mock:
            result = shape_error(
                mock["error_code"],
                idempotency_key,
                mock.get("details"),
            )
        else:
            result = shape_success(mock, idempotency_key, payload)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    print(
        json.dumps({
            "error": (
                "Real connector path is not yet implemented in this script. "
                "The skill harness should call ians_request_aae directly, or "
                "use --mock-response for tests with IANS_REQUEST_AAE_AVAILABLE=1."
            ),
        }),
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
