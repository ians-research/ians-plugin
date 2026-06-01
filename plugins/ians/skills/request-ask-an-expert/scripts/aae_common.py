#!/usr/bin/env python3
"""
IANS Request Ask-an-Expert — Shared payload helpers.

Single source of truth for the three places the AAE skill scripts have to
agree on the *shape* of a locked payload:

  1. Question serialization (DAAS-167). The `question` field can arrive as a
     ``list[str]`` (per-question items the model drafted) or as a
     pre-serialized string ("1. Q\\n2. Q"). Faculty read these verbatim, so the
     skill emits ONE canonical form — a newline-joined, 1-indexed numbered list
     with any leading category sub-label (em-dash or colon style) stripped:

         ["Cyberattacks — How exposed are we?", "Energy — How do we respond?"]
         "1. Cyberattacks — How exposed are we?\\n2. Energy — How do we respond?"

     both canonicalize to:

         "1. How exposed are we?\\n2. How do we respond?"

  2. Guidance values (DAAS-168). The platform AAE form / Salesforce picklist
     stores the long labels "Strategic / Executive" and "Technical / Tactical"
     (spaces around the slash). The skill historically emitted the short form
     ("Strategic"), which Salesforce silently drops. We canonicalize to the
     long form and accept the short form as an alias on input.

  3. Placeholder detection (DAAS-169). The form-shaped review renders editor
     placeholders like "[needs your input — ...]". If one of those survives
     into the locked payload, the field is unfilled and must NOT submit.

These helpers are imported by ``validate_submission.py``,
``build_submission_artifact.py``, and ``infer_guidance.py``. They are pure
functions with no third-party dependencies so the scripts stay runnable in a
bare ``python3`` with nothing installed.
"""

from __future__ import annotations

import re

# --- Guidance canonicalization (DAAS-168) -----------------------------------

GUIDANCE_STRATEGIC = "Strategic / Executive"
GUIDANCE_TECHNICAL = "Technical / Tactical"

#: Canonical Salesforce picklist values for the Guidance Type field.
CANONICAL_GUIDANCE = (GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL)

#: Accepted short-form / variant spellings → canonical value. Keys are matched
#: case-insensitively with internal whitespace collapsed (see ``_guidance_key``).
GUIDANCE_ALIASES = {
    "strategic": GUIDANCE_STRATEGIC,
    "strategic / executive": GUIDANCE_STRATEGIC,
    "strategic/executive": GUIDANCE_STRATEGIC,
    "executive": GUIDANCE_STRATEGIC,
    "strategic executive": GUIDANCE_STRATEGIC,
    "technical": GUIDANCE_TECHNICAL,
    "technical / tactical": GUIDANCE_TECHNICAL,
    "technical/tactical": GUIDANCE_TECHNICAL,
    "tactical": GUIDANCE_TECHNICAL,
    "technical tactical": GUIDANCE_TECHNICAL,
}


def _guidance_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def guidance_to_list(value: object) -> list[str]:
    """Coerce a guidance value (list or ``;``-delimited string) to a list.

    Args:
        value: ``list[str]``, a ``";"``-joined string, ``None``, or anything else.

    Returns:
        A list of raw (un-normalized) guidance tokens, trimmed and non-empty.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(";")
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        return []
    return [str(p).strip() for p in parts if str(p).strip()]


def normalize_guidance(value: object) -> tuple[list[str], bool, list[str]]:
    """Normalize guidance tokens to canonical Salesforce picklist values.

    Short-form aliases ("Strategic", "Technical", "Strategic/Executive") are
    mapped to the canonical long form. Order is preserved and duplicates are
    collapsed (first occurrence wins).

    Args:
        value: A guidance value (list or ``;``-delimited string).

    Returns:
        A ``(canonical, normalized_from_alias, unknown)`` tuple where:
          * ``canonical`` is the de-duplicated list of canonical values,
          * ``normalized_from_alias`` is True if any token was rewritten from a
            non-canonical alias (callers surface a warning),
          * ``unknown`` is the list of tokens that matched no alias.
    """
    canonical: list[str] = []
    normalized_from_alias = False
    unknown: list[str] = []
    for token in guidance_to_list(value):
        mapped = GUIDANCE_ALIASES.get(_guidance_key(token))
        if mapped is None:
            unknown.append(token)
            continue
        if token != mapped:
            normalized_from_alias = True
        if mapped not in canonical:
            canonical.append(mapped)
    return canonical, normalized_from_alias, unknown


# --- Placeholder detection (DAAS-169) ---------------------------------------

#: Literal placeholder strings rendered by the form-shaped review. Kept in sync
#: with the placeholders quoted in SKILL.md Step 3.
PLACEHOLDERS = (
    "[needs your input — what's driving this for you right now?]",
    "[needs your input — what 3-5 specific questions do you want a faculty "
    "member to answer? (1-3 for Faculty Poll)]",
    "[optional — team size, current tools, policies, or anything else that "
    "will help]",
    "[needs your input — pick Strategic, Technical, or both]",
    "[optional]",
    "[needs your input]",
)

# Editorial markers that, *inside a bracketed cue*, mean the field was never
# filled in. Only checked against the bracket interior so ordinary prose that
# merely contains these words ("replace the placeholder logo", "the board needs
# your input") is not flagged.
_PLACEHOLDER_MARKERS = re.compile(
    r"needs your input|\bplaceholder\b",
    re.IGNORECASE,
)


def is_placeholder(value: object) -> bool:
    """Return True when *value* is an unfilled editor placeholder, not content.

    Only a bracketed editorial cue counts — the exact SKILL.md placeholder
    strings, or a ``[optional …]`` / ``[needs your input …]`` / ``[placeholder]``
    shape (so a lightly edited "[needs your input — the board ask]" is still
    caught). Ordinary prose that happens to contain "needs your input" or
    "placeholder" is NOT treated as a placeholder.

    Args:
        value: The field value to inspect.

    Returns:
        True if the trimmed value reads as an unfilled bracketed placeholder.
    """
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s:
        return False
    if s in PLACEHOLDERS:
        return True
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if inner.lower().startswith(("optional", "needs your input")):
            return True
        if _PLACEHOLDER_MARKERS.search(inner):
            return True
    return False


# --- Question canonicalization (DAAS-167) -----------------------------------

_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+\s*[\.\):]\s*")

# Em dash (U+2014) and en dash (U+2013) referenced via escapes so the source
# stays free of confusable unicode characters.
_EM_DASH = "\u2014"
_EN_DASH = "\u2013"
_DASHES = _EM_DASH + _EN_DASH

# Leading "Category — " / "Category: " sub-label to strip from a question.
# label part holds no sentence punctuation and no separator char itself.
_SUBLABEL_DASH_RE = re.compile(
    rf"^\s*(?P<label>[^\n?:{_DASHES}]{{1,50}}?)\s*[{_DASHES}]\s*(?P<rest>\S.*)$",
    re.DOTALL,
)
_SUBLABEL_COLON_RE = re.compile(
    rf"^\s*(?P<label>[^\n?:{_DASHES}]{{1,50}}?):\s+(?P<rest>\S.*)$",
    re.DOTALL,
)
_SUBLABEL_HYPHEN_RE = re.compile(
    rf"^\s*(?P<label>[^\n?:{_DASHES}-]{{1,50}}?)\s+-\s+(?P<rest>\S.*)$",
    re.DOTALL,
)

# A category tag never starts with a question/auxiliary word — if the label
# does, it's the question itself (e.g. "Should we map to NIST: which version?").
_QUESTION_STARTERS = frozenset({
    "what", "what's", "whats", "how", "why", "when", "where", "who", "whom",
    "whose", "which", "should", "can", "could", "would", "will", "is", "are",
    "do", "does", "did", "may", "might", "shall", "if", "given",
})

_INLINE_NUMBER_RE = re.compile(r"(?:^|\s)(\d+)[\.\)]\s+")


def _looks_like_sublabel(label: str, rest: str) -> bool:
    label = label.strip()
    rest = rest.strip()
    if not label or not rest:
        return False
    words = label.split()
    if len(words) > 6 or len(label) > 50:
        return False
    if re.search(r"[.?!]", label):
        return False
    first = words[0].lower().strip(",.:;")
    return first not in _QUESTION_STARTERS


def _strip_sublabel(question: str) -> str:
    for pattern in (_SUBLABEL_DASH_RE, _SUBLABEL_COLON_RE, _SUBLABEL_HYPHEN_RE):
        m = pattern.match(question)
        if m and _looks_like_sublabel(m.group("label"), m.group("rest")):
            return m.group("rest").strip()
    return question.strip()


def _clean_question_item(item: str) -> str:
    item = _NUMBER_PREFIX_RE.sub("", str(item), count=1).strip()
    item = _strip_sublabel(item)
    return item.strip()


def _split_text_to_items(text: str) -> list[str]:
    text = str(text).strip()
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        return lines
    single = lines[0] if lines else ""
    matches = list(_INLINE_NUMBER_RE.finditer(single))
    if len(matches) >= 2:
        items = []
        for idx, m in enumerate(matches):
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(single)
            chunk = single[start:end].strip()
            if chunk:
                items.append(chunk)
        if items:
            return items
    return [single] if single else []


def question_items(value: object) -> list[str]:
    """Return the cleaned, ordered list of questions from *value*.

    Accepts a ``list[str]`` or a serialized string. Each item has its numbering
    and leading category sub-label stripped.

    Args:
        value: ``list[str]``, a serialized string, or ``None``.

    Returns:
        A list of cleaned question strings (no numbering, no sub-labels).
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = [str(v) for v in value]
    else:
        raw_items = _split_text_to_items(str(value))
    cleaned = []
    for raw in raw_items:
        item = _clean_question_item(raw)
        if item:
            cleaned.append(item)
    return cleaned


def canonicalize_questions(value: object) -> str:
    """Serialize *value* to the canonical ``"1. Q\\n2. Q\\n3. Q"`` form.

    Args:
        value: ``list[str]`` or a (possibly messy) serialized question string.

    Returns:
        The canonical newline-joined, 1-indexed numbered string. Empty string
        when *value* yields no questions.
    """
    items = question_items(value)
    return "\n".join(f"{i + 1}. {q}" for i, q in enumerate(items))


def count_questions(value: object) -> int:
    """Count the distinct questions in *value* using the canonical splitter.

    Args:
        value: ``list[str]`` or a serialized question string.

    Returns:
        The number of distinct questions.
    """
    return len(question_items(value))
