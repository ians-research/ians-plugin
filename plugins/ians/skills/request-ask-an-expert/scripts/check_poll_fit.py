#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Faculty Poll fit checker (DAAS-196 / DAAS-208)

Heuristic over drafted questions (and optional driver) to detect when a Faculty
Poll reads more like a Phone discussion: long context, multiple complex
sub-topics, or decision-oriented framing.

Usage:
    python check_poll_fit.py --input <path-to-input-json>

Input JSON:
{
  "questions": "<string or list[str]>",
  "driver": "<optional driver string>"
}

Output JSON:
{
  "suggest_phone": true | false,
  "matched_signals": ["long_context", "multi_topic", "decision_oriented"],
  "nudge": "This reads more like a discussion than a poll — want me to switch to Phone? Faculty can go deeper in a call."
}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from aae_common import question_items

NUDGE_TEXT = (
    "This reads more like a discussion than a poll — want me to switch to "
    "Phone? Faculty can go deeper in a call."
)

# Decision-oriented cues — polls should be scan-style, not open decisions.
DECISION_SIGNALS = [
    (r"\bshould we\b", "decision framing"),
    (r"\bwhich (approach|option|path|strategy)\b", "decision framing"),
    (r"\bhow should we (decide|choose|prioritize)\b", "decision framing"),
    (r"\brecommend\b", "recommendation ask"),
    (r"\btrade[- ]?offs?\b", "trade-off discussion"),
    (r"\bpros and cons\b", "trade-off discussion"),
    (r"\bwalk (me )?through\b", "discussion depth"),
    (r"\bthink through\b", "discussion depth"),
    (r"\bnuanced?\b", "nuanced discussion"),
    (r"\bcomplex\b", "complex topic"),
]

# Category sub-label patterns (em-dash / colon style) suggest multi-topic polls.
_SUBLABEL_RE = re.compile(
    r"^\s*[^\n?:\u2014\u2013-]{1,50}[\u2014\u2013:]\s+\S",
    re.MULTILINE,
)


def _paragraph_count(text: str) -> int:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if len(blocks) >= 3:
        return len(blocks)
    # Single block with many sentences can also read as long context.
    sentences = re.split(r"[.!?]+\s+", text.strip())
    sentences = [s for s in sentences if len(s.split()) > 8]
    return max(len(blocks), len(sentences) // 3)


def _combined_text(questions: object, driver: str | None) -> str:
    items = question_items(questions)
    parts = list(items)
    if driver and driver.strip():
        parts.insert(0, driver.strip())
    return "\n\n".join(parts)


def _raw_question_items(value: object) -> list[str]:
    """Return question strings before sub-label stripping (for multi-topic detection)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines if len(lines) > 1 else [text]


def check_poll_fit(questions: object, driver: str | None = None) -> dict:
    """Return whether to nudge the user toward Phone instead of Faculty Poll."""
    raw_items = _raw_question_items(questions)
    combined = _combined_text(questions, driver)
    matched: list[str] = []

    if _paragraph_count(combined) >= 3:
        matched.append("long_context")

    # Multi-topic: category sub-labels on raw items, or 4+ questions.
    sublabel_count = sum(1 for item in raw_items if _SUBLABEL_RE.match(item))
    if len(raw_items) >= 4 or sublabel_count >= 2:
        matched.append("multi_topic")

    text_lc = combined.lower()
    decision_hits = []
    for pattern, label in DECISION_SIGNALS:
        if re.search(pattern, text_lc):
            decision_hits.append(label)
    if decision_hits:
        matched.append("decision_oriented")

    suggest = bool(matched)
    return {
        "suggest_phone": suggest,
        "matched_signals": matched,
        "nudge": NUDGE_TEXT if suggest else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check whether Faculty Poll questions fit poll scope",
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

    result = check_poll_fit(
        payload.get("questions") or payload.get("question"),
        payload.get("driver"),
    )
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
