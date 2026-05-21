#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Connector Submission Wrapper (Option A)

Wraps the `ians_request_aae` MCP tool. While that tool's write path is not yet
wired through to this skill's runtime, this script's primary role is to:

  1. Detect tool registration. If the tool isn't available, return a marker
     {status: "tool_not_registered"} so the calling skill falls back to
     Option B (JSON submission artifact via build_submission_artifact.py).

  2. Define the contract between the skill and the connector — exactly what
     payload is sent, what response shape is expected, how errors are mapped.

  3. Provide a deterministic mock path for testing (--mock-response) so we can
     exercise success and error cases without a live connector.

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

Output JSON to stdout (tool not registered — fall back to Option B):
{
  "status": "tool_not_registered",
  "fallback": "option_b",
  "reason": "ians_request_aae is not registered with the MCP client.",
  "idempotency_key": "<UUID>"
}

Output JSON to stdout (error from connector):
{
  "status": "error",
  "error_code": "entitlement_missing | validation_failed | rate_limited | server_error",
  "user_message": "...",
  "retryable": true | false,
  "details": { ... per-field details for validation_failed ... },
  "idempotency_key": "<UUID>"
}

Why a separate script for what's effectively one MCP tool call:
  - Idempotency key generation lives here so retries don't double-submit.
  - Error mapping lives here so the skill prose doesn't have to enumerate
    error codes; it just shows user_message.
  - Mock injection lets us test the full skill flow before the connector ships.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Standard turnaround windows by resolution. Used to populate the
# expected_response_window in mock and real responses.
RESPONSE_WINDOWS = {
    "Phone": {"business_days_min": 8, "business_days_max": 12},
    "Undecided": {"business_days_min": 8, "business_days_max": 12},
    "Faculty Poll": {"business_days_min": 4, "business_days_max": 6},
}


# Error code → user-facing message used by the skill prose. Skill prose
# echoes these verbatim or tweaks for context.
ERROR_USER_MESSAGES = {
    "entitlement_missing": (
        "Your IANS subscription doesn't currently include Ask-an-Expert. "
        "Contact your account manager to add it. (You can still produce "
        "a scoping doc to hand off via the scope mode.)"
    ),
    "validation_failed": (
        "Some fields on your request didn't pass IANS validation. See "
        "details below; revise the draft and try again."
    ),
    "rate_limited": (
        "You've hit the AAE submission rate limit. Try again in a bit, or "
        "contact your account manager if you need urgent help."
    ),
    "server_error": (
        "IANS Research had a temporary problem accepting your request. "
        "We can fall back to producing a submission artifact (.json) you "
        "can hand to IANS instead."
    ),
}


# Whether each error type is retryable from the user's perspective.
ERROR_RETRYABLE = {
    "entitlement_missing": False,
    "validation_failed": True,  # user revises and resubmits
    "rate_limited": True,  # eventually
    "server_error": True,  # transient
}


def detect_tool_registered() -> bool:
    """Detect whether ians_request_aae is registered with the MCP client.

    In a real MCP client environment, the script would query the MCP
    runtime to list registered tools and check for `ians_request_aae`.
    The MCP runtime API for this isn't standardized at the script level
    (it's an LLM-driven flow inside the skill), so this script's behavior
    is governed by either:

      (a) the --mock-tool-not-registered flag (deterministic test path),
      (b) the absence of an environment variable IANS_REQUEST_AAE_AVAILABLE
          set to "1" (the runtime convention we're proposing).

    When the connector ships and the MCP client exposes a stable
    tool-discovery API, this function gets a third branch that queries
    that API. The skill calling this script is responsible for setting
    IANS_REQUEST_AAE_AVAILABLE based on what it sees in the MCP tool list
    at session start.

    Returns:
        True when the env var IANS_REQUEST_AAE_AVAILABLE is "1", else False.
    """
    return os.environ.get("IANS_REQUEST_AAE_AVAILABLE") == "1"


def build_connector_payload(payload: dict, idempotency_key: str) -> dict:
    """Shape the AAE payload for the connector input.

    Strips fields that are server-populated (origin, submitter) per the
    contract proposal.

    Args:
        payload: The canonical AAE payload built by the skill.
        idempotency_key: Stable idempotency key for the submission.

    Returns:
        The dict to send as the connector tool's input.
    """
    context = payload.get("context") or {}
    return {
        "schemaVersion": payload.get("schemaVersion", "1.0"),
        "resolution": payload.get("resolution"),
        "driver": payload.get("driver"),
        "question": payload.get("question"),
        "details": payload.get("details"),
        "guidance": payload.get("guidance") or [],
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
    """Shape the connector's success response for the skill.

    Fills in expected_response_window from the resolution if the connector
    didn't provide it (defensive for v1 connector responses).

    Args:
        connector_response: The raw response dict from the connector tool.
        idempotency_key: Idempotency key that was sent on the request.
        payload: The original AAE payload (used for the fallback window).

    Returns:
        A normalized success response dict for the skill to display.
    """
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


def shape_error(
    error_code: str, idempotency_key: str, details: dict | None = None,
) -> dict:
    """Shape an error response. Unknown error codes degrade to server_error.

    Args:
        error_code: The error code returned by the connector.
        idempotency_key: Idempotency key that was sent on the request.
        details: Optional details bag to forward to the skill.

    Returns:
        A normalized error response dict for the skill to display.
    """
    if error_code not in ERROR_USER_MESSAGES:
        details = {"original_error_code": error_code, **(details or {})}
        error_code = "server_error"
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
        help="Force the tool-not-registered path for tests.",
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

    # Tool-not-registered branch.
    if args.mock_tool_not_registered or not detect_tool_registered():
        result = {
            "status": "tool_not_registered",
            "fallback": "submission_artifact",
            "reason": (
                "ians_request_aae is not registered with the MCP client. "
                "Skill should call build_submission_artifact.py to produce "
                "a JSON artifact in the platform AAE form's submission "
                "shape; the user hands that file to IANS for ingestion."
            ),
            "idempotency_key": idempotency_key,
        }
        print(json.dumps(result, indent=2))
        sys.exit(0)

    # Mock-response branch — used in tests to exercise success/error paths.
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

        # Mock can be either a success-shaped object (has case_id) or an
        # error-shaped object (has error_code).
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

    # Real-connector branch. Today, this branch is unreachable because the
    # tool isn't registered (detect_tool_registered returns False). When the
    # connector ships, the skill harness will set IANS_REQUEST_AAE_AVAILABLE=1
    # and inject the actual MCP tool call before invoking this script — or
    # this script gets refactored to call the tool directly. For now we
    # explicitly fail closed to make the missing piece visible:
    print(
        json.dumps({
            "error": (
                "Real connector path is not yet implemented. The connector "
                "tool ians_request_aae is not yet shipped. Use --mock-response "
                "for tests, or check that IANS_REQUEST_AAE_AVAILABLE is unset "
                "(which is the expected pre-Option-A state). When the connector "
                "team ships the tool, this script will call it directly."
            ),
        }),
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
