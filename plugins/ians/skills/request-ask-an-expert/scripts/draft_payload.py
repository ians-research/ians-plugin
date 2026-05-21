#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Payload Drafter

Extracts Driver / Question / Details from a conversation transcript so the
calling skill can present a draft for user review. This is heuristic
extraction with deliberate limits — the user reviews and edits before
anything gets locked in. Garbage-in is fine; the user catches it at review.

Usage:
    python draft_payload.py --input <path>

Input JSON shape:
{
  "transcript": "<the user-side conversation text>",
  "resolution": "Phone | Faculty Poll | Undecided"
}

Output JSON to stdout:
{
  "driver": "<text or null>",
  "question": "<numbered list as a single string, or null>",
  "details": "<text or null, only for Phone/Undecided>",
  "must_ask": ["driver", "question", ...],
  "low_confidence": ["driver", ...],
  "trimmed_fields": ["details", ...],
  "char_counts": {"driver": 412, "question": 587, "details": 0},
  "caps": {"driver": 1000, "question": 1000, "details": 500},
  "question_count_hint": "1-3 questions" | "3-5 questions"
}

Field shaping:
  - Phone / Undecided: driver+question caps 1000, details cap 500, 3-5 questions.
  - Faculty Poll: driver+question caps 750, no details, 1-3 questions.

Extraction strategy:
  - Driver: sentences with why-now language ("audit deadline", "board ask",
    "incident", "we need", "because", "since", "after").
  - Question: sentences ending in "?" or starting with question words.
    Numbered into a list; trimmed to the resolution-specific count.
  - Details: factual context — team size, tools, regulatory, AWS/Azure/GCP,
    "we use X", "we're on Y".

Fallback for terse requests: if no driver-pattern sentence is found, the
script looks for a topic-phrase signal — "ask an expert is about X",
"AAE is about X", "topic is X", "I want to discuss X" — and seeds the
driver field with "Topic: X.", marked in `low_confidence`. The calling
skill should render the seed verbatim and prompt the user to expand on
it; this gives the user something to react to rather than a blank field
without putting words in their mouth.

If a field's extraction yields nothing usable, list it in `must_ask` so the
calling skill knows to ask the user a targeted question rather than presenting
an empty field as a draft.
"""

import argparse
import json
import re
import sys
from pathlib import Path

PHONE_DRIVER_CAP = 1000
PHONE_QUESTION_CAP = 1000
DETAILS_CAP = 500
FACULTY_POLL_CAP = 750

PHONE_QUESTION_COUNT = (3, 5)
FP_QUESTION_COUNT = (1, 3)

# Sentence-splitting that's permissive about ?, !, and . without being fooled
# by abbreviations. Good enough for AAE conversations; if it misses an edge
# case, the user catches it at review.
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\d])")

# "Why now" markers — language that signals causation, urgency, drivers.
DRIVER_PATTERNS = [
    r"\bbecause\b",
    r"\bsince\b",
    r"\bdue to\b",
    r"\bafter\b",
    r"\bbefore\b",
    r"\bdeadline\b",
    r"\baudit\b",
    r"\bincident\b",
    r"\bbreach\b",
    r"\bboard (asked|wants|expects|requested)\b",
    r"\bwe (need|have to|must)\b",
    r"\b(in|by|before) (next|this) (week|month|quarter)\b",
    r"\bregulator(s|y)\b",
    r"\bcompliance\b",
    r"\b(M&A|merger|acquisition)\b",
    r"\b(upcoming|approaching)\b",
]

# Topic-phrase fallback patterns. Used only when no DRIVER_PATTERNS match.
# Captures the topic after the cue phrase so the skill can seed the driver
# field with "Topic: <phrase>" rather than leaving it null.
TOPIC_FALLBACK_PATTERNS = [
    re.compile(
        r"(?:ask[- ]?an[- ]?expert|aae)\s+(?:is\s+)?about\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(r"\btopic\s+is\s+(.+?)(?:[.!?]|$)", re.IGNORECASE),
    re.compile(
        r"\b(?:want|need|would like)\s+to\s+(?:discuss|talk about|cover)\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my\s+)?(?:question|request)\s+is\s+about\s+(.+?)(?:[.!?]|$)",
        re.IGNORECASE,
    ),
]

# Detail markers — factual context useful to a faculty matcher.
DETAIL_PATTERNS = [
    r"\bteam (of|size)\b",
    r"\b\d+ (people|engineers|analysts|fte)\b",
    r"\bwe (use|run|have|are on|deployed)\b",
    r"\b(aws|azure|gcp|google cloud|on[- ]prem)\b",
    r"\b(siem|edr|xdr|iam|pam|cnapp|cspm|sspm|soar|grc|mdr)\b",
    r"\b(splunk|crowdstrike|sentinel|wiz|okta|cyberark)\b",
    r"\b(financial services|healthcare|retail|saas|public sector)\b",
    r"\b(hipaa|pci|sox|gdpr|nydfs|nist|iso ?27001|fedramp|cmmc)\b",
    r"\b(small|mid|large|enterprise)[- ](size|sized)?\b",
]

QUESTION_STARTERS = (
    "what",
    "how",
    "why",
    "when",
    "where",
    "who",
    "should",
    "can",
    "could",
    "would",
    "is",
    "are",
    "do ",
    "does ",
    "did ",
)


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _trim_to_cap(text: str, cap: int) -> tuple[str, bool]:
    """Trim a string to cap, ending at sentence/word boundary if possible.

    Args:
        text: The text to trim.
        cap: The maximum length of the text.

    Returns:
        A tuple of the trimmed text and a boolean indicating if the text was trimmed.
    """
    if len(text) <= cap:
        return text, False
    # Aim for ~80% of cap and find a clean breakpoint.
    target = int(cap * 0.95)
    snippet = text[:cap]
    # Prefer sentence-end break.
    for end in [". ", "? ", "! "]:
        idx = snippet.rfind(end, target)
        if idx != -1:
            return snippet[: idx + 1].strip(), True
    # Fall back to word break.
    idx = snippet.rfind(" ", target)
    if idx != -1:
        return snippet[:idx].strip() + "…", True
    return snippet.rstrip() + "…", True


def _matches_any(text: str, patterns: list[str]) -> bool:
    text_lc = text.lower()
    return any(re.search(p, text_lc) for p in patterns)


def _is_question(sentence: str) -> bool:
    s = sentence.strip()
    if s.endswith("?"):
        return True
    s_lc = s.lower()
    return any(s_lc.startswith(starter) for starter in QUESTION_STARTERS)


def extract_driver(
    sentences: list[str],
    cap: int,
    full_transcript: str,
) -> tuple[str, bool, bool]:
    """Extract the driver from the sentences.

    Args:
        sentences: The sentences to extract the driver from.
        cap: The maximum length of the driver.
        full_transcript: The full transcript of the conversation.

    Returns:
        A tuple of the driver, a boolean indicating if the driver was trimmed, and a boolean indicating if the driver is low confidence.
    """
    candidates = [s for s in sentences if _matches_any(s, DRIVER_PATTERNS)]
    if candidates:
        text = " ".join(candidates)
        trimmed, was_trimmed = _trim_to_cap(text, cap)
        return trimmed, was_trimmed, False
    # Fallback: topic-phrase capture from the full transcript.
    for pattern in TOPIC_FALLBACK_PATTERNS:
        m = pattern.search(full_transcript)
        if m:
            topic = m.group(1).strip().rstrip(",;:")
            if topic and len(topic) >= 3:
                seeded = f"Topic: {topic}."
                trimmed, was_trimmed = _trim_to_cap(seeded, cap)
                return trimmed, was_trimmed, True
    return "", False, False


def extract_questions(
    sentences: list[str],
    cap: int,
    count_range: tuple[int, int],
) -> tuple[str, bool]:
    """Extract the questions from the sentences.

    Args:
        sentences: The sentences to extract the questions from.
        cap: The maximum length of the questions.
        count_range: The range of question counts.

    Returns:
        A tuple of the questions and a boolean indicating if the questions were trimmed.
    """
    _min_q, max_q = count_range
    candidates = [s for s in sentences if _is_question(s)]
    if not candidates:
        return "", False
    # Take up to max_q. We deliberately don't pad to min_q — if the user only
    # raised 2 questions in a Phone-resolution conversation, the skill will
    # ask them to add 1 more rather than fabricating a third.
    selected = candidates[:max_q]
    numbered = "\n".join(f"{i + 1}. {q.rstrip('?')}?" for i, q in enumerate(selected))
    trimmed, was_trimmed = _trim_to_cap(numbered, cap)
    return trimmed, was_trimmed


def extract_details(sentences: list[str], cap: int) -> tuple[str, bool]:
    """Extract the details from the sentences.

    Args:
        sentences: The sentences to extract the details from.
        cap: The maximum length of the details.

    Returns:
        A tuple of the details and a boolean indicating if the details were trimmed.
    """
    candidates = [s for s in sentences if _matches_any(s, DETAIL_PATTERNS)]
    if not candidates:
        return "", False
    # Dedupe: drop any that already appear in driver candidates by being
    # very similar — naive equality check is enough.
    seen = set()
    unique = []
    for s in candidates:
        key = s.lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(s)
    text = " ".join(unique)
    trimmed, was_trimmed = _trim_to_cap(text, cap)
    return trimmed, was_trimmed


def draft(transcript: str, resolution: str) -> dict:
    """Draft the payload from the transcript.

    Args:
        transcript: The transcript of the conversation.
        resolution: The resolution of the conversation.

    Returns:
        The draft payload.
    """
    is_fp = resolution == "Faculty Poll"
    driver_cap = FACULTY_POLL_CAP if is_fp else PHONE_DRIVER_CAP
    question_cap = FACULTY_POLL_CAP if is_fp else PHONE_QUESTION_CAP
    count_range = FP_QUESTION_COUNT if is_fp else PHONE_QUESTION_COUNT

    sentences = _split_sentences(transcript)

    driver, driver_trimmed, driver_low_conf = extract_driver(
        sentences,
        driver_cap,
        transcript,
    )
    question, question_trimmed = extract_questions(
        sentences,
        question_cap,
        count_range,
    )
    if is_fp:
        details, details_trimmed = "", False
    else:
        details, details_trimmed = extract_details(sentences, DETAILS_CAP)

    must_ask = []
    if driver is None:
        must_ask.append("driver")
    if question is None:
        must_ask.append("question")
    # Details is optional — never put it in must_ask.

    low_confidence = []
    if driver_low_conf:
        low_confidence.append("driver")

    trimmed_fields = []
    if driver_trimmed:
        trimmed_fields.append("driver")
    if question_trimmed:
        trimmed_fields.append("question")
    if details_trimmed:
        trimmed_fields.append("details")

    return {
        "driver": driver,
        "question": question,
        "details": details,
        "must_ask": must_ask,
        "low_confidence": low_confidence,
        "trimmed_fields": trimmed_fields,
        "char_counts": {
            "driver": len(driver) if driver else 0,
            "question": len(question) if question else 0,
            "details": len(details) if details else 0,
        },
        "caps": {
            "driver": driver_cap,
            "question": question_cap,
            "details": DETAILS_CAP if not is_fp else 0,
        },
        "question_count_hint": (f"{count_range[0]}-{count_range[1]} questions"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draft AAE payload fields from conversation context",
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

    transcript = payload.get("transcript", "")
    resolution = payload.get("resolution", "Phone")
    if resolution not in {"Phone", "Faculty Poll", "Undecided"}:
        print(
            json.dumps({"error": f"Invalid resolution: {resolution}"}),
            file=sys.stderr,
        )
        sys.exit(2)

    result = draft(transcript, resolution)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
