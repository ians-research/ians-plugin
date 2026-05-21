#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Scheduling Input Parser

Routes a user's combined scheduling answer into the platform form's two fields:
  - availability (text, max 300) — date ranges, time zones, days of the week
  - calendarlink (text, max 250) — Calendly/Bookings URL or EA contact

Strategy: extract URLs first (always go to calendarlink), then route based on
keyword content. Anything ambiguous goes to availability since it's the more
forgiving field.

Usage:
    python parse_scheduling.py --input <path>

Input JSON shape:
{
  "input_text": "<user's freeform scheduling answer>"
}

Output JSON to stdout:
{
  "availability": "..." | null,
  "calendarlink": "..." | null,
  "extracted_urls": ["..."],
  "extracted_emails": ["..."],
  "trimmed_fields": ["availability", "calendarlink"],
  "char_counts": {"availability": 0, "calendarlink": 0}
}

If both fields end up empty (e.g., user said "skip" or sent whitespace),
both fields are null and trimmed_fields is empty. That's fine — the form
treats both as optional.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AVAILABILITY_CAP = 300
CALENDARLINK_CAP = 250

# URL detection — broad but safe. Matches http(s), bare domains for known
# scheduling tools, and standard URLs.
URL_PATTERN = re.compile(
    r"\b(?:https?://|cal\.com/|calendly\.com/|bookings\.|outlook\.office\.com/owa/calendar/)"
    r"[^\s\)\]\,]+",
    re.IGNORECASE,
)

# Email detection — for EA contact ("my EA is jane@example.com").
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)

# Skip phrases — user explicitly opted out.
SKIP_PATTERNS = re.compile(
    r"^\s*(skip|no thanks|nothing|none|n/?a|nope|nah)\s*[\.\!]?\s*$",
    re.IGNORECASE,
)

# Hint that a piece of text is about availability rather than a contact.
AVAILABILITY_KEYWORDS = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"morning|afternoon|evening|am|pm|"
    r"weekday|weekend|"
    r"est|edt|cst|cdt|mst|mdt|pst|pdt|utc|gmt|et|ct|mt|pt|"
    r"prefer|preferably|available|availability|free|busy|"
    r"week of|next week|this week|"
    r"\d{1,2}\s*[/-]\s*\d{1,2}|"
    r"after \d|before \d|between \d)\b",
    re.IGNORECASE,
)


def _trim_to_cap(text: str, cap: int) -> tuple[str, bool]:
    """Trim a string to cap, preferring sentence/word boundaries.

    Args:
        text: The text to trim.
        cap: The maximum length of the text.

    Returns:
        A tuple of the trimmed text and a boolean indicating if the text was trimmed.
    """
    text = text.strip()
    if len(text) <= cap:
        return text, False
    target = int(cap * 0.95)
    snippet = text[:cap]
    for end in [". ", ", ", "; "]:
        idx = snippet.rfind(end, target)
        if idx != -1:
            return snippet[: idx + 1].strip().rstrip(",;"), True
    idx = snippet.rfind(" ", target)
    if idx != -1:
        return snippet[:idx].strip() + "…", True
    return snippet.rstrip() + "…", True


def _strip_extracted(text: str, extractions: list[str]) -> str:
    """Remove extracted substrings from text, then collapse whitespace and leading/trailing punctuation.

    Args:
        text: The text to clean.
        extractions: Substrings already routed to other fields (URLs, emails).

    Returns:
        The remainder text with extractions removed and surrounding noise stripped.
    """
    for x in extractions:
        text = text.replace(x, " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" .,;:")


REMAINDER_MIN_LEN = 20


def _empty_result() -> dict:
    return {
        "availability": None,
        "calendarlink": None,
        "extracted_urls": [],
        "extracted_emails": [],
        "trimmed_fields": [],
        "char_counts": {"availability": 0, "calendarlink": 0},
    }


def _build_calendarlink(urls: list[str], emails: list[str]) -> str | None:
    """Pick the calendarlink value from extracted URLs/emails.

    Returns:
        A URL (or "; "-joined URLs), an "EA: <email>" string, or None.
    """
    if urls:
        return "; ".join(urls) if len(urls) > 1 else urls[0]
    if emails:
        return f"EA: {emails[0]}"
    return None


def _apply_cap(value: str | None, cap: int, label: str, trimmed_fields: list[str]) -> str | None:
    """Trim *value* to *cap* and record the field name if trimming occurred.

    Args:
        value: The value to cap, or None.
        cap: Maximum allowed length.
        label: The field name to append to *trimmed_fields* if trimming happens.
        trimmed_fields: Mutated in place to record which fields were trimmed.

    Returns:
        The capped value, or None if the input was None or trimmed to empty.
    """
    if value is None:
        return None
    capped, was_trimmed = _trim_to_cap(value, cap)
    if was_trimmed:
        trimmed_fields.append(label)
    return capped or None


def parse(input_text: str) -> dict:
    """Parse the scheduling input.

    Args:
        input_text: The input text to parse.

    Returns:
        The parsed scheduling input.
    """
    if not isinstance(input_text, str):
        return _empty_result()

    text = input_text.strip()
    if not text or SKIP_PATTERNS.match(text):
        return _empty_result()

    urls = URL_PATTERN.findall(text)
    emails = EMAIL_PATTERN.findall(text)

    calendarlink = _build_calendarlink(urls, emails)

    remainder = _strip_extracted(text, urls + emails)
    availability: str | None = None
    if remainder and (AVAILABILITY_KEYWORDS.search(remainder) or len(remainder) > REMAINDER_MIN_LEN):
        availability = remainder

    trimmed_fields: list[str] = []
    availability = _apply_cap(availability, AVAILABILITY_CAP, "availability", trimmed_fields)
    calendarlink = _apply_cap(calendarlink, CALENDARLINK_CAP, "calendarlink", trimmed_fields)

    return {
        "availability": availability,
        "calendarlink": calendarlink,
        "extracted_urls": urls,
        "extracted_emails": emails,
        "trimmed_fields": trimmed_fields,
        "char_counts": {
            "availability": len(availability) if availability else 0,
            "calendarlink": len(calendarlink) if calendarlink else 0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse combined scheduling input into availability + calendarlink",
    )
    parser.add_argument("--input", required=True, help="Path to input JSON")
    args = parser.parse_args()

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

    input_text = payload.get("input_text", "")
    result = parse(input_text)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
