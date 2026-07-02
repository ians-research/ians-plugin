#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Submission Validator

Enforces the platform AAE form's required-field rules on the canonical
payload BEFORE the skill calls ians_request_aae.
The connector validates server-side but only after we've already
told the user it was sent. This script is the client-side gate.

The required-field matrix mirrors the platform AAE form:

  resolution         required, in {Phone, Faculty Poll, Undecided}
  driver             required, non-empty after trim, not an unfilled
                     placeholder, len ≤ resolution cap
  question           required, accepts list[str] or a (sub-label-stripped)
                     string; 1-3 items (Faculty Poll) or 3-5 items
                     (Phone/Undecided); no item may be an unfilled placeholder;
                     total len ≤ resolution cap
  details            optional; if present, len ≤ 500. Forbidden for Faculty Poll.
  guidance           required for Phone/Undecided, ≥1 of the canonical picklist
                     values {"Strategic / Executive", "Technical / Tactical"}.
                     Short-form aliases ("Strategic") are accepted with a
                     normalization warning. Forbidden for Faculty Poll.
  email_address      OPTIONAL reply-to override only. The connector populates the
                     email server-side from the authenticated session, so this is
                     never required client-side and is never sourced from
                     ians_whoami. When present, must look like an email.
  expedite_request   required boolean (defaults to False if absent)
  deadline           required iff expedite_request=True; must be ISO date ≥ today
  availability       optional; forbidden for Faculty Poll
  calendarlink       optional; forbidden for Faculty Poll

Usage:
    python validate_submission.py --payload <path-to-canonical-payload-json>
        [--today YYYY-MM-DD]    # for tests; defaults to system today

Output JSON to stdout:
{
  "valid": true | false,
  "errors": [
    {"field": "question", "code": "too_few", "message": "..."},
    ...
  ],
  "warnings": [...]
}

Exit code 0 if valid, 1 if invalid (so the skill can branch in shell).

Errors block submission; warnings surface to the user but don't block.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from aae_common import (
    CANONICAL_GUIDANCE,
    canonicalize_questions,
    count_questions,
    guidance_to_list,
    is_placeholder,
    normalize_guidance,
)

PHONE_DRIVER_CAP = 1000
PHONE_QUESTION_CAP = 1000
DETAILS_CAP = 500
FACULTY_POLL_CAP = 750
TOPIC_SEED_LEN = 60
PHONE_MIN_TURNAROUND_DAYS = 8
FP_MIN_TURNAROUND_DAYS = 4
PHONE_MAX_TURNAROUND_DAYS = 12
FP_MAX_TURNAROUND_DAYS = 6

PHONE_QUESTION_COUNT = (3, 5)
FP_QUESTION_COUNT = (1, 3)

VALID_RESOLUTIONS = {"Phone", "Faculty Poll", "Undecided"}
VALID_GUIDANCE = set(CANONICAL_GUIDANCE)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Issue = dict  # {"field": str, "code": str, "message": str}


def _resolve_resolution(payload: dict) -> tuple[str, list[Issue], list[Issue]]:
    """Normalize the resolution field and surface any wrong-key warnings.

    Args:
        payload: The canonical AAE payload.

    Returns:
        A tuple of (resolution, errors, warnings). The resolution defaults
        to "Phone" when the payload's value is missing/invalid so the rest
        of validation can run.
    """
    errors: list[Issue] = []
    warnings: list[Issue] = []
    resolution = payload.get("resolution")
    if resolution is None and payload.get("resolution_type") is not None:
        resolution = payload.get("resolution_type")
        warnings.append({
            "field": "resolution",
            "code": "wrong_key",
            "message": (
                "Payload uses `resolution_type`; canonical key is `resolution`. "
                "The platform AAE form expects `resolution` — rename before submission."
            ),
        })
    if resolution not in VALID_RESOLUTIONS:
        errors.append({
            "field": "resolution",
            "code": "invalid",
            "message": f"resolution must be one of {sorted(VALID_RESOLUTIONS)}; got {resolution!r}",
        })
        # Default downstream to Phone so the user still sees all errors.
        resolution = "Phone"
    return resolution, errors, warnings


def _check_driver(payload: dict, driver_cap: int, resolution: str) -> list[Issue]:
    errors: list[Issue] = []
    driver = (payload.get("driver") or "").strip()
    if not driver:
        errors.append({
            "field": "driver",
            "code": "missing",
            "message": "Driver and context is required.",
        })
    elif is_placeholder(driver):
        errors.append({
            "field": "driver",
            "code": "placeholder_unfilled",
            "message": (
                "Driver still holds the review placeholder text — it was never "
                "filled in. Ask the user what's driving this request before "
                "submission."
            ),
        })
    elif driver.startswith("Topic:") and len(driver) < TOPIC_SEED_LEN:
        errors.append({
            "field": "driver",
            "code": "topic_seed_only",
            "message": (
                "Driver looks like an unexpanded topic seed (e.g. 'Topic: X.'). "
                "The user needs to expand on what's driving this request "
                "before submission."
            ),
        })
    elif len(driver) > driver_cap:
        errors.append({
            "field": "driver",
            "code": "too_long",
            "message": f"Driver is {len(driver)} chars; cap is {driver_cap} for {resolution}.",
        })
    return errors


def _raw_question_value(payload: dict) -> object:
    # Prefer the canonical `question` key; fall back to a `questions` list.
    value = payload.get("question")
    if value in (None, "", []) and isinstance(payload.get("questions"), list):
        return payload.get("questions")
    return value


def _question_has_placeholder(value: object) -> bool:
    if isinstance(value, (list, tuple)):
        return any(is_placeholder(item) for item in value)
    return is_placeholder(value)


def _check_question(
    payload: dict, question_cap: int, count_range: tuple[int, int], resolution: str,
) -> list[Issue]:
    errors: list[Issue] = []
    raw_value = _raw_question_value(payload)

    # An unfilled placeholder is never valid content — check before normalizing.
    # List-form fields are checked item by item, not just the container.
    if _question_has_placeholder(raw_value):
        errors.append({
            "field": "question",
            "code": "placeholder_unfilled",
            "message": (
                "Specific questions still hold the review placeholder text — "
                "the field was never filled in. The user must provide their "
                "questions before submission."
            ),
        })
        return errors

    question, question_count = canonicalize_questions(raw_value), count_questions(raw_value)
    if not question:
        errors.append({
            "field": "question",
            "code": "missing",
            "message": "Specific questions are required.",
        })
        return errors

    min_q, max_q = count_range
    if question_count < min_q:
        errors.append({
            "field": "question",
            "code": "too_few",
            "message": (
                f"{resolution} requires {min_q}-{max_q} questions; "
                f"found {question_count}."
            ),
        })
    elif question_count > max_q:
        errors.append({
            "field": "question",
            "code": "too_many",
            "message": (
                f"{resolution} accepts {min_q}-{max_q} questions; "
                f"found {question_count}. Drop the extras or move them "
                f"into details."
            ),
        })
    if len(question) > question_cap:
        errors.append({
            "field": "question",
            "code": "too_long",
            "message": (
                f"Questions total {len(question)} chars; cap is "
                f"{question_cap} for {resolution}."
            ),
        })
    return errors


def _check_details(payload: dict, is_fp: bool) -> list[Issue]:  # noqa: FBT001
    errors: list[Issue] = []
    details = (payload.get("details") or "").strip()
    # Details is optional; an unfilled "[optional — …]" placeholder counts as
    # empty, not as submittable content.
    if not details or is_placeholder(details):
        return errors
    if is_fp:
        errors.append({
            "field": "details",
            "code": "not_allowed",
            "message": "Faculty Poll does not collect a details field; remove it.",
        })
    elif len(details) > DETAILS_CAP:
        errors.append({
            "field": "details",
            "code": "too_long",
            "message": f"Details is {len(details)} chars; cap is {DETAILS_CAP}.",
        })
    return errors


def _check_guidance(
    payload: dict,
    is_fp: bool,  # noqa: FBT001
    resolution: str,
) -> tuple[list[Issue], list[Issue]]:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    raw = guidance_to_list(payload.get("guidance"))

    if is_fp:
        if raw:
            errors.append({
                "field": "guidance",
                "code": "not_allowed",
                "message": "Faculty Poll does not collect guidance; remove it.",
            })
        return errors, warnings

    # An unfilled placeholder is not a guidance selection.
    if any(is_placeholder(item) for item in raw):
        errors.append({
            "field": "guidance",
            "code": "placeholder_unfilled",
            "message": (
                "Guidance still holds the review placeholder — pick "
                f"{sorted(VALID_GUIDANCE)} before submission."
            ),
        })
        return errors, warnings

    if not raw:
        errors.append({
            "field": "guidance",
            "code": "missing",
            "message": f"{resolution} requires at least one of {sorted(VALID_GUIDANCE)}.",
        })
        return errors, warnings

    # Accept short-form aliases ("Strategic") but normalize to the canonical
    # picklist values and warn so the skill can rewrite the payload
    # before submission.
    canonical, normalized_from_alias, unknown = normalize_guidance(raw)
    if unknown:
        errors.append({
            "field": "guidance",
            "code": "invalid_value",
            "message": f"Unknown guidance values: {unknown}. Allowed: {sorted(VALID_GUIDANCE)}.",
        })
    if normalized_from_alias:
        warnings.append({
            "field": "guidance",
            "code": "normalized",
            "message": (
                "Guidance uses short-form values; canonical picklist "
                f"labels are {list(canonical)}. Rewrite the payload to the "
                "canonical form before submission."
            ),
        })
    return errors, warnings


def _check_email(payload: dict) -> list[Issue]:
    """Validate an optional reply-to email override.

    Email is NOT a client-side required field: the connector populates it
    server-side from the authenticated session, and `ians_whoami` does not
    expose the user's email. Only validate the format when the
    payload carries an explicit override; never require it, never read whoami.
    """
    errors: list[Issue] = []
    email = (payload.get("email") or payload.get("email_address") or "").strip()
    if email and not EMAIL_RE.match(email):
        errors.append({
            "field": "email_address",
            "code": "invalid",
            "message": f"Email {email!r} doesn't look like a valid address.",
        })
    return errors


def _check_deadline_value(
    deadline: object, today: date, is_fp: bool,  # noqa: FBT001
) -> tuple[list[Issue], list[Issue]]:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    if not ISO_DATE_RE.match(str(deadline)):
        errors.append({
            "field": "deadline",
            "code": "invalid_format",
            "message": f"Deadline must be YYYY-MM-DD; got {deadline!r}.",
        })
        return errors, warnings
    try:
        parsed = date.fromisoformat(str(deadline))
    except ValueError:
        errors.append({
            "field": "deadline",
            "code": "invalid_date",
            "message": f"Deadline {deadline!r} is not a real date.",
        })
        return errors, warnings
    if parsed < today:
        errors.append({
            "field": "deadline",
            "code": "in_past",
            "message": f"Deadline {deadline} is before today ({today.isoformat()}).",
        })
        return errors, warnings
    days = (parsed - today).days
    min_turnaround = FP_MIN_TURNAROUND_DAYS if is_fp else PHONE_MIN_TURNAROUND_DAYS
    max_turnaround = FP_MAX_TURNAROUND_DAYS if is_fp else PHONE_MAX_TURNAROUND_DAYS
    if days < min_turnaround:
        warnings.append({
            "field": "deadline",
            "code": "tight_turnaround",
            "message": (
                f"Deadline is {days} calendar days out. "
                f"Standard turnaround is {min_turnaround}-"
                f"{max_turnaround} business days. "
                f"Expedite flag prioritizes, but it may still be tight."
            ),
        })
    return errors, warnings


def _check_deadline(
    payload: dict, today: date, is_fp: bool,  # noqa: FBT001
) -> tuple[list[Issue], list[Issue]]:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    expedite = bool(payload.get("expedite_request"))
    deadline = payload.get("deadline")
    if expedite:
        if is_placeholder(deadline):
            errors.append({
                "field": "deadline",
                "code": "placeholder_unfilled",
                "message": (
                    "Deadline still holds the review placeholder; provide a real "
                    "YYYY-MM-DD date or clear the expedite flag."
                ),
            })
        elif not deadline:
            errors.append({
                "field": "deadline",
                "code": "missing",
                "message": "Deadline is required when expedite_request is true.",
            })
        else:
            sub_errors, sub_warnings = _check_deadline_value(deadline, today, is_fp)
            errors.extend(sub_errors)
            warnings.extend(sub_warnings)
    elif deadline:
        warnings.append({
            "field": "deadline",
            "code": "deadline_without_expedite",
            "message": (
                "Deadline is set but expedite_request is false. "
                "Either set expedite_request=true or clear deadline."
            ),
        })
    return errors, warnings


def _check_scheduling(payload: dict, is_fp: bool) -> list[Issue]:  # noqa: FBT001
    if not is_fp:
        return []
    return [
        {
            "field": fld,
            "code": "not_allowed",
            "message": f"Faculty Poll does not collect {fld}; remove it.",
        }
        for fld in ("availability", "calendarlink")
        if (payload.get(fld) or "").strip()
    ]


def validate(payload: dict, today: date) -> dict:
    """Validate the canonical AAE payload against the form-required rules.

    Args:
        payload: The canonical AAE payload built by the skill.
        today: Anchor date for past-deadline checks.

    Returns:
        A dict with `valid`, `errors`, and `warnings` keys.
    """
    errors: list[Issue] = []
    warnings: list[Issue] = []

    resolution, res_errors, res_warnings = _resolve_resolution(payload)
    errors.extend(res_errors)
    warnings.extend(res_warnings)

    is_fp = resolution == "Faculty Poll"
    driver_cap = FACULTY_POLL_CAP if is_fp else PHONE_DRIVER_CAP
    question_cap = FACULTY_POLL_CAP if is_fp else PHONE_QUESTION_CAP
    count_range = FP_QUESTION_COUNT if is_fp else PHONE_QUESTION_COUNT

    errors.extend(_check_driver(payload, driver_cap, resolution))
    errors.extend(_check_question(payload, question_cap, count_range, resolution))
    errors.extend(_check_details(payload, is_fp))
    guidance_errors, guidance_warnings = _check_guidance(payload, is_fp, resolution)
    errors.extend(guidance_errors)
    warnings.extend(guidance_warnings)
    errors.extend(_check_email(payload))

    deadline_errors, deadline_warnings = _check_deadline(payload, today, is_fp)
    errors.extend(deadline_errors)
    warnings.extend(deadline_warnings)

    errors.extend(_check_scheduling(payload, is_fp))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the canonical AAE payload against form-required rules",
    )
    parser.add_argument("--payload", required=True, help="Path to canonical AAE payload JSON")
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD) for tests")
    args = parser.parse_args()

    payload_path = Path(args.payload)
    if not payload_path.exists():
        print(json.dumps({"error": f"Payload not found: {payload_path}"}), file=sys.stderr)
        sys.exit(2)

    try:
        with payload_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"Could not parse payload: {e}"}), file=sys.stderr)
        sys.exit(2)

    today = datetime.now(tz=timezone.utc).date()
    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(json.dumps({"error": f"--today must be YYYY-MM-DD; got {args.today!r}"}), file=sys.stderr)
            sys.exit(2)

    result = validate(payload, today)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
