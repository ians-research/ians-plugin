#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Submission Artifact Builder (Option B)

Produces a JSON artifact in the exact shape the platform AAE form posts
to the IANS AAE backend. This is what the skill hands the user when:

  - Submit mode is selected, AND
  - The connector tool `ians_request_aae` is not yet registered (Option A
    unavailable).

The artifact is meant to be ingested directly by IANS — by an account
manager handing it off, by a future ingestion endpoint that consumes the
form-submission shape, or by the connector when it ships (it can call its
own write path with this payload, no translation needed).

Field shape mirrors the platform AAE form's submission payload:

  resolution           - Phone | Faculty Poll | Undecided
  driver               - string (trimmed)
  question             - string; canonical "1. Q\\n2. Q" form. Accepts a
                         list[str] or a pre-serialized string on input and
                         strips leading category sub-labels (DAAS-167).
  details              - string (trimmed; '' for Faculty Poll)
  guidance             - semicolon-delimited canonical picklist labels
                         ("Strategic / Executive;Technical / Tactical"); short
                         forms ("Strategic") are normalized. '' for Faculty Poll.
  expedite_request     - boolean
  deadline             - YYYY-MM-DD or null
  preferred_method     - 'Phone' | 'Email' (Phone for Phone/Undecided,
                         Email for Faculty Poll — matches form default)
  email_address        - from ians_whoami; null if not provided
  phone_number         - null (not collected by the skill; IANS contact record)
  alt_phone_number     - null (same)
  availability         - string ('' for Faculty Poll)
  calendarlink         - string ('' for Faculty Poll)
  expectedCallLength   - '60 Minutes' for Phone, null otherwise
  isUndecided          - true only when resolution is Undecided
  origin               - 'IANS MCP {ClientName}' (e.g., 'IANS MCP Claude').
                         Note: when Option A activates, the connector
                         server-populates this field; on this artifact path,
                         the client sets it because there's no server in the
                         loop.
  ask_ians_id          - null (no Ask IANS bridge today)

Usage:
    python build_submission_artifact.py \\
        --payload <path-to-canonical-payload-json> \\
        --output <path-to-output-json> \\
        [--client-name Claude] \\
        [--whoami <path-to-ians-whoami-output-json>]

The canonical payload is the in-memory AAE payload the skill builds during
Steps 3-4 (driver/question/details/guidance/expedite/deadline/availability/
calendarlink/submitter). The whoami output, if passed, supplies email_address.

Output JSON to stdout (status):
{
  "output": "<path to written .json>",
  "fields_omitted": ["phone_number", "alt_phone_number"],
  "origin_value": "IANS MCP Claude"
}

The .json file written at --output is the actual artifact handed to IANS.
Do not embed any other content in it; downstream ingestion expects the
form-submission shape with no wrappers.
"""

import argparse
import json
import sys
from pathlib import Path

from aae_common import canonicalize_questions, normalize_guidance


def transform_to_form_submission(
    payload: dict,
    client_name: str,
    whoami: dict,
) -> dict:
    """Convert the canonical AAE payload to the form-submission shape.

    Args:
        payload: The canonical AAE payload.
        client_name: The name of the client.
        whoami: The whoami output.

    Returns:
        The form-submission shape.
    """
    resolution = payload.get("resolution", "Phone")
    is_fp = resolution == "Faculty Poll"
    is_undecided = resolution == "Undecided"

    # email_address comes from whoami if available; otherwise from the
    # canonical payload's submitter; otherwise null.
    submitter = payload.get("submitter") or {}
    email = (
        (whoami.get("user") or {}).get("email")
        or whoami.get("email")
        or submitter.get("email")
        or None
    )

    # Guidance is stored in Salesforce as a strict picklist; emit the canonical
    # long-form labels ("Strategic / Executive") and accept short-form aliases
    # ("Strategic") on input (DAAS-168).
    canonical_guidance, _normalized, _unknown = normalize_guidance(payload.get("guidance"))
    guidance_str = ";".join(canonical_guidance)

    # Question can arrive as list[str] or a pre-serialized (possibly sub-labelled)
    # string; emit the single canonical "1. Q\n2. Q" form (DAAS-167).
    question_str = canonicalize_questions(payload.get("question"))

    return {
        "resolution": resolution,
        "driver": (payload.get("driver") or "").strip(),
        "question": question_str,
        "details": "" if is_fp else (payload.get("details") or "").strip(),
        "guidance": "" if is_fp else guidance_str,
        "expedite_request": bool(payload.get("expedite_request")),
        "deadline": payload.get("deadline")
        if payload.get("expedite_request")
        else None,
        # The platform form's commented-out preferred contact method block
        # uses these defaults. We follow the same convention so the artifact
        # round-trips into the form's state model.
        "preferred_method": "Email" if is_fp else "Phone",
        "email_address": email,
        # phone_number / alt_phone_number are intentionally null. The skill
        # never collects them; the IANS contact record has them. Future
        # ingestion can merge from the contact record at write-time.
        "phone_number": None,
        "alt_phone_number": None,
        "availability": "" if is_fp else (payload.get("availability") or "").strip(),
        "calendarlink": "" if is_fp else (payload.get("calendarlink") or "").strip(),
        "expectedCallLength": "60 Minutes" if not is_fp else None,
        "isUndecided": is_undecided,
        "origin": f"IANS MCP {client_name}",
        "ask_ians_id": (payload.get("context") or {}).get("ask_ians_id"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build an AAE submission artifact (.json) matching "
            "the platform AAE form's submission payload shape."
        ),
    )
    parser.add_argument(
        "--payload",
        required=True,
        help="Path to the canonical AAE payload JSON (the one built in Steps 3-4).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the form-submission JSON artifact.",
    )
    parser.add_argument(
        "--client-name",
        default="Claude",
        help=(
            "MCP client name for origin attribution. Default 'Claude'. "
            "Format: 'IANS MCP {ClientName}'."
        ),
    )
    parser.add_argument(
        "--whoami",
        help=(
            "Optional path to ians_whoami() output JSON. Supplies email_address "
            "if present. Without this, email_address falls back to the "
            "canonical payload's submitter, then null."
        ),
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

    whoami = {}
    if args.whoami:
        whoami_path = Path(args.whoami)
        if not whoami_path.exists():
            print(
                json.dumps({"error": f"whoami not found: {whoami_path}"}),
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            with whoami_path.open("r", encoding="utf-8") as f:
                whoami = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(
                json.dumps({"error": f"Could not parse whoami: {e}"}),
                file=sys.stderr,
            )
            sys.exit(2)

    submission = transform_to_form_submission(payload, args.client_name, whoami)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2, ensure_ascii=False)

    print(
        json.dumps(
            {
                "output": str(output_path),
                "fields_omitted": ["phone_number", "alt_phone_number"],
                "origin_value": submission["origin"],
            },
            indent=2,
        ),
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
