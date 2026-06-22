#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Resolution Recommender

Suggests a resolution type (Phone | Faculty Poll | Undecided) for an AAE
request based on the conversation context. Returns reasoning so the calling
skill can show the user *why* a recommendation was made — recommendations
without reasoning aren't trustworthy.

Usage:
    python recommend_resolution.py --input <path> [--threshold 0.20]

Input JSON shape (single freeform field, since heuristics work on text):
{
  "transcript": "<the user-side conversation text, joined>"
}

Output JSON to stdout:
{
  "recommendation": "Phone | Faculty Poll | Undecided",
  "confidence": 0.0..1.0,
  "scores": {"phone": 0.0..1.0, "faculty_poll": 0.0..1.0},
  "reasoning": "<one-line human-readable rationale>",
  "matched_signals": {
    "phone": ["..."],
    "faculty_poll": ["..."]
  }
}

Heuristics are intentionally simple keyword + weak-NLU scoring. The skill
reads the score and reasoning and presents a recommendation; the user
confirms or overrides. We are not trying to be smart here — we are trying
to give the user a sensible default they can react to.

Confidence interpretation:
  >= 0.20 (default threshold) — recommend the higher-scoring side.
  <  0.20 — recommend "Undecided" with the suggestion to ask one
            clarifying question first.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Phrases that point toward a 1:1 Phone call. Bias: nuance, multi-stakeholder
# challenges, real-time discussion needs, strategic problems with no clean
# yes/no answer.
PHONE_SIGNALS = [
    # Stakeholder/audience cues
    (r"\bboard\b", "board involvement"),
    (r"\bc-?suite\b|\bcfo\b|\bceo\b|\bcio\b|\bcoo\b", "C-suite involvement"),
    (r"\bhostile\b|\bdifficult conversation\b", "difficult dynamics"),
    (r"\bstakeholders?\b", "stakeholder coordination"),
    # Conversation/depth cues
    (r"\binteractive\b|\bback[- ]?and[- ]?forth\b|\bdiscuss(ion|ed)?\b", "interactive discussion"),
    (r"\btalk through\b|\bthink through\b|\bwalk me through\b", "thinking-out-loud need"),
    (r"\bnuance(d|s)?\b|\bcomplicated\b|\bcomplex\b", "nuanced challenge"),
    # Decision/architecture cues
    (r"\barchitect(ure|ing|ural)?\b", "architecture decision"),
    (r"\bstrateg(y|ic|ies)\b", "strategic problem"),
    (r"\bm&a\b|\bmerger\b|\backquisition\b", "M&A context"),
    (r"\bpost[- ]incident\b|\bbreach\b|\bretrospective\b", "post-incident review"),
    (r"\blitigation\b|\blegal\b", "legal exposure"),
    # Live-help cues
    (r"\bcall\b|\bphone\b|\b1[:-]?1\b|\bone[- ]on[- ]one\b", "explicit call request"),
]

# Phrases that point toward a Faculty Poll. Bias: comparative perspectives,
# peer benchmarks, short topical scans, "what do others do" framing.
FACULTY_POLL_SIGNALS = [
    # Comparison/benchmark cues
    (r"\bpeer(s|ed)?\b|\bother (cisos?|companies|firms|organizations)\b", "peer comparison"),
    (r"\bbenchmark(s|ing|ed)?\b", "benchmarking"),
    (r"\bhow do (others|peers|other cisos)\b", "how do others framing"),
    (r"\bis (this|x|that) common\b|\bhow common\b", "prevalence question"),
    (r"\bindustry (norm|standard|practice)\b", "industry norms question"),
    (r"\bsurvey\b", "survey framing"),
    # Multiple-perspective cues
    (r"\bmultiple (perspectives?|opinions?|views?|takes?)\b", "multiple perspectives"),
    (r"\bdiffering (views?|opinions?)\b", "differing views"),
    (r"\bquick (poll|read|sense)\b", "quick poll"),
    # Written/short cues
    (r"\bwritten (response|deliverable|answer)\b", "written response request"),
    (r"\bshort (answer|response|read)\b", "short response request"),
    (r"\bpoll\b|\bfaculty poll\b", "explicit poll request"),
    # Scanning topical cues
    (r"\bare (.{0,30}) (using|adopting|moving)\b", "adoption scan"),
]


def _score(text: str, signals: list[tuple[str, str]]) -> tuple[float, list[str]]:
    """Score *text* against a list of (regex, label) signals.

    Args:
        text: The conversation text to scan.
        signals: A list of (regex_pattern, label) tuples.

    Returns:
        A tuple of (score, matched_labels). Score is the fraction of unique
        signal labels fired, capped at 1.0.
    """
    text_lc = text.lower()
    matched: list[str] = []
    seen_labels: set[str] = set()
    for pattern, label in signals:
        if label in seen_labels:
            continue
        if re.search(pattern, text_lc):
            matched.append(label)
            seen_labels.add(label)
    # Soft normalization: 4+ unique matches saturates to 1.0.
    score = min(len(matched) / 4.0, 1.0)
    return score, matched


def recommend(transcript: str, threshold: float = 0.20) -> dict:
    if not isinstance(transcript, str) or not transcript.strip():
        return {
            "recommendation": "Undecided",
            "confidence": 0.0,
            "scores": {"phone": 0.0, "faculty_poll": 0.0},
            "reasoning": "No conversation context provided — ask the user one clarifying question before recommending.",
            "matched_signals": {"phone": [], "faculty_poll": []},
        }

    phone_score, phone_matches = _score(transcript, PHONE_SIGNALS)
    fp_score, fp_matches = _score(transcript, FACULTY_POLL_SIGNALS)

    delta = abs(phone_score - fp_score)
    if delta < threshold:
        # Genuinely ambiguous — recommend Undecided and tell the caller
        # to ask one clarifying question.
        if phone_score == 0.0 and fp_score == 0.0:
            reasoning = (
                "No clear signals for either resolution type. Ask one "
                "clarifying question before recommending."
            )
        else:
            reasoning = (
                f"Signals are mixed (phone={phone_score:.2f}, faculty_poll={fp_score:.2f}). "
                "Either could fit — ask the user to pick or surface the "
                "tradeoff."
            )
        return {
            "recommendation": "Undecided",
            "confidence": delta,
            "scores": {"phone": phone_score, "faculty_poll": fp_score},
            "reasoning": reasoning,
            "matched_signals": {"phone": phone_matches, "faculty_poll": fp_matches},
        }

    if phone_score > fp_score:
        top_signals = ", ".join(phone_matches[:3]) or "general nuance signals"
        reasoning = (
            f"Phone fits because the conversation shows {top_signals}. Faculty Poll "
            "would also work if the user prefers short comparative "
            "perspectives over a 1:1 discussion."
        )
        return {
            "recommendation": "Phone",
            "confidence": delta,
            "scores": {"phone": phone_score, "faculty_poll": fp_score},
            "reasoning": reasoning,
            "matched_signals": {"phone": phone_matches, "faculty_poll": fp_matches},
        }

    top_signals = ", ".join(fp_matches[:3]) or "general comparison signals"
    reasoning = (
        f"Faculty Poll fits because the conversation shows {top_signals}. Phone would "
        "also work if the user wants an interactive 1:1 discussion."
    )
    return {
        "recommendation": "Faculty Poll",
        "confidence": delta,
        "scores": {"phone": phone_score, "faculty_poll": fp_score},
        "reasoning": reasoning,
        "matched_signals": {"phone": phone_matches, "faculty_poll": fp_matches},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recommend an AAE resolution from conversation context",
    )
    parser.add_argument("--input", required=True, help="Path to input JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.20,
        help="Minimum score delta for a confident recommendation (default 0.20)",
    )
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
    result = recommend(transcript, threshold=args.threshold)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
