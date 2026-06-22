#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Urgency Parser

Reads the conversation transcript (or an explicit user phrase) and decides:
  - Is this AAE request expedited? (boolean)
  - If yes, what's the deadline? (ISO date)

The platform AAE form models urgency as `expedite_request` + `deadline`. The
deadline picker has minDate=today; we enforce the same rule here so the skill
never produces an invalid date.

Usage:
    python parse_urgency.py --input <path> [--today YYYY-MM-DD]

If --today is omitted, system date is used. Tests should always pass --today
for determinism.

Input JSON shape:
{
  "transcript": "<conversation text — used for cue detection>",
  "phrase": "<optional explicit phrase to parse, e.g., 'next Friday'>"
}

Output JSON to stdout:
{
  "expedite_request": false,
  "deadline": "YYYY-MM-DD" | null,
  "matched_phrase": "<the substring that triggered the parse>" | null,
  "reasoning": "<one-line rationale>",
  "warnings": ["<flag if deadline tight given standard turnaround>", ...]
}

Heuristic strategy:
  1. Look for explicit calendar dates ("June 12", "6/12", "2026-06-12").
  2. Look for relative phrases ("next Friday", "tomorrow", "in two weeks").
  3. Look for urgency adjectives ("ASAP", "urgent", "immediately") which
     imply expedite=true even without a date — caller asks the user for the
     date if no date can be inferred.
  4. "No rush", "whenever you can" → expedite_request=false.

Standard AAE turnaround:
  - Phone: 8-12 business days.
  - Faculty Poll: 4-6 business days.
We don't know the resolution here (this script is resolution-agnostic), so
we surface a generic warning when the parsed deadline is fewer than 14
calendar days out, so the skill can flag the tradeoff to the user.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SHORT_TURNAROUND_DAYS = 14
TWO_DIGIT_YEAR_LEN = 4
APPROX_MONTH_DAYS = 30

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

URGENCY_ADJECTIVES = re.compile(
    r"\b(asap|urgent|urgently|immediately|right away|critical|"
    r"as soon as possible|time[- ]sensitive)\b",
    re.IGNORECASE,
)

NO_RUSH = re.compile(
    r"\b(no rush|no hurry|whenever (you can|works)|take your time|"
    r"not urgent|not time[- ]sensitive)\b",
    re.IGNORECASE,
)

# "in N days/weeks/months"
RELATIVE_DURATION = re.compile(
    r"\b(in|within)\s+(?:a\s+|an\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(day|week|month)s?\b",
    re.IGNORECASE,
)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a": 1, "an": 1,
}

# "next Friday", "this Tuesday", "by Friday", "before Monday"
RELATIVE_DAY = re.compile(
    r"\b(next|this|coming|by|before|on)\s+("
    + "|".join(WEEKDAYS.keys())
    + r")\b",
    re.IGNORECASE,
)

# "Tomorrow"
TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)

# Calendar dates: "June 12, 2026" / "June 12" / "6/12/2026" / "6/12" /
# "2026-06-12" / "before June 24". Order matters — most specific first.
ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
MONTH_DAY_YEAR = re.compile(
    r"\b(" + "|".join(MONTHS.keys()) + r")\s+(\d{1,2})(?:,?\s+(\d{4}))?\b",
    re.IGNORECASE,
)

# "the audit is in two weeks", "we have a board meeting on June 12"
DEADLINE_CONTEXT = re.compile(
    r"\b(deadline|due|board meeting|audit|presentation|review|approval|"
    r"steering committee|cutover|launch|go[- ]?live)\b",
    re.IGNORECASE,
)


def _resolve_iso(match: re.Match[str], _today: date) -> tuple[date | None, str | None]:
    try:
        y = int(match.group(1))
        m = int(match.group(2))
        d = int(match.group(3))
        return date(y, m, d), match.group(0)
    except (ValueError, TypeError):
        return None, None


def _resolve_slash(match: re.Match[str], today: date) -> tuple[date | None, str | None]:
    try:
        m = int(match.group(1))
        d = int(match.group(2))
        y_str = match.group(3)
        if y_str:
            y = int(y_str) if len(y_str) == TWO_DIGIT_YEAR_LEN else 2000 + int(y_str)
        else:
            # Year omitted — assume current year, but if that's already
            # past, roll forward.
            y = today.year
            candidate = date(y, m, d)
            if candidate < today:
                y += 1
        return date(y, m, d), match.group(0)
    except (ValueError, TypeError):
        return None, None


def _resolve_month_day(match: re.Match[str], today: date) -> tuple[date | None, str | None]:
    try:
        month_name = match.group(1).lower()
        m = MONTHS.get(month_name)
        if not m:
            return None, None
        d = int(match.group(2))
        y_str = match.group(3)
        if y_str:
            y = int(y_str)
        else:
            # Year omitted — current year if month/day still ahead, else
            # next year.
            y = today.year
            try:
                candidate = date(y, m, d)
            except ValueError:
                return None, None
            if candidate < today:
                y += 1
        return date(y, m, d), match.group(0)
    except (ValueError, TypeError):
        return None, None


def _resolve_relative_day(match: re.Match[str], today: date) -> tuple[date | None, str | None]:
    qualifier = match.group(1).lower()
    weekday_name = match.group(2).lower()
    target_idx = WEEKDAYS[weekday_name]
    today_idx = today.weekday()

    delta = (target_idx - today_idx) % 7
    if qualifier == "next" and delta == 0:
        # "next Friday" said on a Friday means the *next* one, not today.
        delta = 7
    elif qualifier in ("this", "coming", "on") and delta == 0:
        # "this Friday" said on Friday → next Friday.
        delta = 7
    elif qualifier in ("by", "before") and delta == 0:
        # "by Friday" / "before Friday" — earliest interpretation is the
        # *upcoming* Friday, never in the past.
        delta = 7
    return today + timedelta(days=delta), match.group(0)


def _resolve_relative_duration(
    match: re.Match[str], today: date,
) -> tuple[date | None, str | None]:
    raw = match.group(2).lower()
    n = NUMBER_WORDS.get(raw)
    if n is None:
        try:
            n = int(raw)
        except ValueError:
            return None, None
    unit = match.group(3).lower()
    if unit == "day":
        return today + timedelta(days=n), match.group(0)
    if unit == "week":
        return today + timedelta(weeks=n), match.group(0)
    if unit == "month":
        # Approximate; faculty matchers don't need calendar-exact months.
        return today + timedelta(days=APPROX_MONTH_DAYS * n), match.group(0)
    return None, None


def _find_date(text: str, today: date) -> tuple[date | None, str | None]:
    """Search *text* for the most specific date expression we can resolve.

    Returns:
        A tuple of (parsed_date, matched_phrase). Both are None if no date
        is found.
    """
    pipeline: list[tuple[re.Pattern[str], object]] = [
        (ISO_DATE, _resolve_iso),
        (MONTH_DAY_YEAR, _resolve_month_day),
        (SLASH_DATE, _resolve_slash),
    ]
    for pattern, resolver in pipeline:
        m = pattern.search(text)
        if m:
            parsed_date, matched_phrase = resolver(m, today)  # type: ignore[operator]
            if parsed_date is not None:
                return parsed_date, matched_phrase

    if TOMORROW.search(text):
        return today + timedelta(days=1), "tomorrow"

    relative_pipeline: list[tuple[re.Pattern[str], object]] = [
        (RELATIVE_DAY, _resolve_relative_day),
        (RELATIVE_DURATION, _resolve_relative_duration),
    ]
    for pattern, resolver in relative_pipeline:
        m = pattern.search(text)
        if m:
            parsed_date, matched_phrase = resolver(m, today)  # type: ignore[operator]
            if parsed_date is not None:
                return parsed_date, matched_phrase

    return None, None


def _reasoning_for(
    *, has_urgency: bool, parsed_date: date | None, matched_phrase: str | None,
) -> tuple[str, list[str]]:
    """Build the reasoning string + extra warnings for the expedite decision.

    Args:
        has_urgency: Whether an urgency adjective was detected.
        parsed_date: The parsed deadline, if any.
        matched_phrase: The substring that produced *parsed_date*, if any.

    Returns:
        A tuple of (reasoning_string, additional_warnings).
    """
    warnings: list[str] = []
    if has_urgency and parsed_date is None:
        warnings.append("expedite=true but deadline missing — ask the user.")
        return (
            "Urgency adjective detected but no date — set expedite_request=true "
            "and ask the user for a target deadline.",
            warnings,
        )
    if parsed_date is not None and has_urgency:
        return f"Both urgency adjective and deadline detected ({matched_phrase}).", warnings
    if parsed_date is not None:
        return f"Deadline detected ({matched_phrase}) — set expedite_request=true.", warnings
    return "Defaulting to non-expedited.", warnings


def parse(transcript: str, phrase: str, today: date) -> dict:
    """Parse urgency + deadline from a transcript and/or explicit phrase.

    Args:
        transcript: Conversation transcript used for cue detection.
        phrase: Optional explicit phrase to parse first.
        today: Anchor date for relative-date resolution.

    Returns:
        A dict with expedite_request, deadline, matched_phrase, reasoning,
        and warnings.
    """
    text = ((phrase or "") + " " + (transcript or "")).strip()

    if not text:
        return {
            "expedite_request": False,
            "deadline": None,
            "matched_phrase": None,
            "reasoning": "No urgency cues — leave expedite_request=false.",
            "warnings": [],
        }

    # No-rush wins over urgency markers if both present.
    no_rush_match = NO_RUSH.search(text)
    has_urgency = bool(URGENCY_ADJECTIVES.search(text))

    parsed_date, matched_phrase = _find_date(text, today)

    if no_rush_match:
        return {
            "expedite_request": False,
            "deadline": None,
            "matched_phrase": no_rush_match.group(0),
            "reasoning": "User indicated no rush; leave expedite_request=false.",
            "warnings": [],
        }

    if parsed_date is None and not has_urgency:
        return {
            "expedite_request": False,
            "deadline": None,
            "matched_phrase": None,
            "reasoning": "No date or urgency adjective detected; default to non-expedited.",
            "warnings": [],
        }

    # Drop past dates — treat as urgency-only.
    if parsed_date is not None and parsed_date < today:
        parsed_date = None

    deadline_str = parsed_date.isoformat() if parsed_date else None
    expedite = parsed_date is not None or has_urgency

    warnings: list[str] = []
    if parsed_date is not None:
        days_out = (parsed_date - today).days
        if days_out < SHORT_TURNAROUND_DAYS:
            warnings.append(
                f"Deadline is {days_out} calendar days out. Standard AAE "
                "turnaround is 8-12 business days for Phone, 4-6 for Faculty "
                "Poll. Flag the tradeoff to the user.",
            )

    reasoning, extra_warnings = _reasoning_for(
        has_urgency=has_urgency,
        parsed_date=parsed_date,
        matched_phrase=matched_phrase,
    )
    warnings.extend(extra_warnings)

    return {
        "expedite_request": expedite,
        "deadline": deadline_str,
        "matched_phrase": matched_phrase,
        "reasoning": reasoning,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse urgency + deadline from conversation context",
    )
    parser.add_argument("--input", required=True, help="Path to input JSON")
    parser.add_argument(
        "--today",
        help="ISO date to anchor relative parsing (default: system date)",
    )
    args = parser.parse_args()

    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(
                json.dumps({"error": f"Invalid --today: {args.today}"}),
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        today = datetime.now(tz=timezone.utc).date()

    path = Path(args.input)
    if not path.exists():
        print(json.dumps({"error": f"Input file not found: {path}"}), file=sys.stderr)
        sys.exit(2)

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"Could not parse input: {e}"}), file=sys.stderr)
        sys.exit(2)

    transcript = payload.get("transcript", "")
    phrase = payload.get("phrase", "")
    result = parse(transcript, phrase, today)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
