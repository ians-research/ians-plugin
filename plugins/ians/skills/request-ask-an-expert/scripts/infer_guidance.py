#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Guidance Inference

Infers Guidance Type (Strategic/Executive and/or Technical/Tactical) from the
question text. The platform AAE form requires this field for Phone/Undecided
resolutions and uses it to weight faculty matching.

We return a multi-select array because security questions often span both —
"we're picking a SIEM and need to align selection criteria with the CFO" is
strategic AND technical.

If the inference is genuinely ambiguous (no clear signals on either side, or
the question is purely informational), we return an empty array. The calling
skill treats that as the signal to ask the user directly rather than guessing.

Usage:
    python infer_guidance.py --input <path> [--threshold 0.15]

Input JSON shape:
{
  "question": "<the question text — typically the numbered list from draft_payload>"
}

Output JSON to stdout:
{
  "guidance": ["Strategic", "Technical"] | ["Strategic"] | ["Technical"] | [],
  "scores": {"strategic": 0.0..1.0, "technical": 0.0..1.0},
  "reasoning": "<one-line rationale>",
  "matched_signals": {
    "strategic": ["..."],
    "technical": ["..."]
  }
}
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Strategic / Executive signals — business alignment, governance, leadership,
# org-level prioritization, comms with execs/board.
STRATEGIC_SIGNALS = [
    (
        r"\bboard\b|\bc-?suite\b|\bcfo\b|\bceo\b|\bcio\b|\bcoo\b|\bexecutive\b",
        "exec/board audience",
    ),
    (
        r"\bbudget(s|ing)?\b|\bspend(ing)?\b|\bcost\b|\binvestment\b",
        "budget/investment",
    ),
    (r"\bheadcount\b|\bhiring\b|\bteam (build|structure|size)\b", "org/headcount"),
    (r"\bprioriti[sz](e|ation|ing)\b|\broadmap\b", "prioritization/roadmap"),
    (r"\bgovernance\b|\bpolicy\b|\bpolicies\b|\bcharter\b", "governance/policy"),
    (
        r"\b(business|strategic) (goal|objective|priorit|alignment)\b",
        "business alignment",
    ),
    (r"\bprogram (maturity|growth|expansion|build)\b", "program maturity"),
    (r"\bvendor (selection|strategy|consolidation)\b", "vendor strategy"),
    (r"\b(M&A|merger|acquisition|due diligence)\b", "M&A"),
    (
        r"\b(communicate|present|brief) (the|to) (board|exec|leadership|c-?suite)\b",
        "exec communication",
    ),
    (r"\bnarrative\b|\bstoryline\b|\btalking points?\b", "narrative/comms"),
    (r"\brisk appetite\b|\bbusiness risk\b", "risk appetite"),
    (r"\bkpi\b|\bmetrics for (the )?(board|exec)\b", "exec metrics"),
]

# Technical / Tactical signals — specific tools, configurations, controls,
# architectures, threat detection logic, technical compliance mapping.
TECHNICAL_SIGNALS = [
    (
        r"\b(siem|edr|xdr|iam|pam|cnapp|cspm|sspm|soar|grc|mdr|waf|dlp|casb)\b",
        "specific tool category",
    ),
    (
        r"\b(splunk|crowdstrike|sentinel|wiz|okta|cyberark|sailpoint|rapid7|tenable|qualys|microsoft defender|azure ad|aws iam)\b",
        "specific product",
    ),
    (
        r"\bconfigur(e|ation|ing)\b|\btuning\b|\bdeploy(ed|ing|ment)?\b",
        "configuration/tuning",
    ),
    (
        r"\barchitect(ure|ing|ural)?\b|\btopology\b|\bnetwork (segmentation|design)\b",
        "architecture",
    ),
    (
        r"\bthreat (detection|hunting|model)\b|\bdetection (logic|rule)\b",
        "threat detection logic",
    ),
    (r"\b(use case|sigma rule|kql|spl|yara|snort|suricata)\b", "detection tooling"),
    (
        r"\b(control|controls) (mapping|implementation|design|coverage)\b",
        "control implementation",
    ),
    (
        r"\b(map|mapping) (.{0,20}) (to nist|to iso|to cis|to pci)\b",
        "framework mapping",
    ),
    (
        r"\bencrypt(ion|ed|ing)\b|\bkey management\b|\b(kms|hsm|tls|mtls)\b",
        "encryption/keys",
    ),
    (
        r"\b(api|microservice|kubernetes|k8s|container|serverless|lambda)\b",
        "modern app stack",
    ),
    (r"\b(pen ?test|red team|purple team|tabletop)\b", "pentest/exercise"),
    (r"\b(cve|exploit|vulnerability|patch)\b", "vuln/exploit"),
    (
        r"\b(zero[- ]?trust|microsegmentation|least privilege)\b",
        "zero trust/access controls",
    ),
    (
        r"\b(privacy|data protection) (control|technical)\b",
        "technical privacy controls",
    ),
    (r"\bevidence\b|\baudit (artifact|evidence)\b", "audit evidence"),
]


def _score(text: str, signals: list[tuple[str, str]]) -> tuple[float, list[str]]:
    text_lc = text.lower()
    matched = []
    seen_labels = set()
    for pattern, label in signals:
        if label in seen_labels:
            continue
        if re.search(pattern, text_lc):
            matched.append(label)
            seen_labels.add(label)
    score = min(len(matched) / 4.0, 1.0)
    return score, matched


def infer(question: str, threshold: float = 0.15) -> dict:
    if not isinstance(question, str) or not question.strip():
        return {
            "guidance": [],
            "scores": {"strategic": 0.0, "technical": 0.0},
            "reasoning": "No question provided — ask the user to pick guidance type.",
            "matched_signals": {"strategic": [], "technical": []},
        }

    s_score, s_matches = _score(question, STRATEGIC_SIGNALS)
    t_score, t_matches = _score(question, TECHNICAL_SIGNALS)

    # Both clearly above threshold → both apply.
    if s_score >= threshold and t_score >= threshold:
        reasoning = (
            "Both apply: question covers exec/governance ({s_top}) and "
            "technical implementation ({t_top})."
        ).format(
            s_top=", ".join(s_matches[:2]) or "strategic signals",
            t_top=", ".join(t_matches[:2]) or "technical signals",
        )
        return {
            "guidance": ["Strategic", "Technical"],
            "scores": {"strategic": s_score, "technical": t_score},
            "reasoning": reasoning,
            "matched_signals": {"strategic": s_matches, "technical": t_matches},
        }

    # One above threshold and the other below → just the one.
    if s_score >= threshold and t_score < threshold:
        reasoning = (
            "Strategic fits because the question shows {sig}. No strong "
            "technical implementation signal."
        ).format(sig=", ".join(s_matches[:2]) or "exec/governance signals")
        return {
            "guidance": ["Strategic"],
            "scores": {"strategic": s_score, "technical": t_score},
            "reasoning": reasoning,
            "matched_signals": {"strategic": s_matches, "technical": t_matches},
        }

    if t_score >= threshold and s_score < threshold:
        reasoning = (
            "Technical fits because the question shows {sig}. No strong "
            "strategic/exec signal."
        ).format(sig=", ".join(t_matches[:2]) or "technical signals")
        return {
            "guidance": ["Technical"],
            "scores": {"strategic": s_score, "technical": t_score},
            "reasoning": reasoning,
            "matched_signals": {"strategic": s_matches, "technical": t_matches},
        }

    # Both below threshold → ambiguous. Empty array signals "ask the user".
    reasoning = (
        "Question is ambiguous — no strong strategic or technical signal "
        f"(strategic={s_score:.2f}, technical={t_score:.2f}). Ask the user directly."
    )
    return {
        "guidance": [],
        "scores": {"strategic": s_score, "technical": t_score},
        "reasoning": reasoning,
        "matched_signals": {"strategic": s_matches, "technical": t_matches},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Infer Guidance Type (Strategic/Technical) from question text",
    )
    parser.add_argument("--input", required=True, help="Path to input JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.15,
        help="Minimum score for a guidance type to apply (default 0.15)",
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

    question = payload.get("question", "")
    result = infer(question, threshold=args.threshold)
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
