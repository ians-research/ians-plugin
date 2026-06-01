#!/usr/bin/env python3
"""Unit tests for scripts/aae_common.py.

Covers the shared payload helpers behind:
  - DAAS-167 (canonical question serialization),
  - DAAS-168 (guidance canonicalization),
  - DAAS-169 (unfilled-placeholder detection).

Run from the skill root:
    python -m unittest discover -s evals/tests -v
"""

import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aae_common import (  # noqa: E402
    GUIDANCE_STRATEGIC,
    GUIDANCE_TECHNICAL,
    canonicalize_questions,
    count_questions,
    guidance_to_list,
    is_placeholder,
    normalize_guidance,
    question_items,
)

EM = "\u2014"
EN = "\u2013"


class CanonicalizeQuestionsTest(unittest.TestCase):
    def test_list_of_strings_is_numbered(self):
        out = canonicalize_questions(["First?", "Second?", "Third?"])
        self.assertEqual(out, "1. First?\n2. Second?\n3. Third?")

    def test_preserialized_string_renumbered(self):
        out = canonicalize_questions("1. First?\n2. Second?")
        self.assertEqual(out, "1. First?\n2. Second?")

    def test_em_dash_sublabel_stripped(self):
        out = canonicalize_questions(
            [f"Cyberattacks {EM} How exposed are we to spillover?"]
        )
        self.assertEqual(out, "1. How exposed are we to spillover?")

    def test_colon_sublabel_stripped(self):
        out = canonicalize_questions(["Energy & Supply Chain: How do we respond?"])
        self.assertEqual(out, "1. How do we respond?")

    def test_en_dash_sublabel_stripped(self):
        out = canonicalize_questions([f"Board reporting {EN} What is the framing?"])
        self.assertEqual(out, "1. What is the framing?")

    def test_spaced_hyphen_sublabel_stripped(self):
        out = canonicalize_questions(["Vendors - Which one should we pick?"])
        self.assertEqual(out, "1. Which one should we pick?")

    def test_numbered_string_with_inline_sublabels(self):
        raw = (
            f"1. Cyberattacks {EM} How exposed are we?\n"
            f"2. Energy & Supply Chain {EM} How do we prioritize?"
        )
        out = canonicalize_questions(raw)
        self.assertEqual(out, "1. How exposed are we?\n2. How do we prioritize?")

    def test_question_starter_label_not_stripped(self):
        # "Should we map controls to NIST" is the question itself, not a tag.
        out = canonicalize_questions(["Should we map controls to NIST: which version?"])
        self.assertEqual(out, "1. Should we map controls to NIST: which version?")

    def test_long_label_not_stripped(self):
        # A long pre-colon clause is real content, not a short category tag.
        long_clause = "we have been debating this for months across the team"
        out = canonicalize_questions([f"{long_clause}: what should we do?"])
        self.assertEqual(out, f"1. {long_clause}: what should we do?")

    def test_single_line_with_inline_numbering_splits(self):
        out = canonicalize_questions("1. First? 2. Second? 3. Third?")
        self.assertEqual(out, "1. First?\n2. Second?\n3. Third?")

    def test_empty_inputs(self):
        self.assertEqual(canonicalize_questions(None), "")
        self.assertEqual(canonicalize_questions(""), "")
        self.assertEqual(canonicalize_questions([]), "")
        self.assertEqual(canonicalize_questions(["", "  "]), "")

    def test_count_matches_items(self):
        value = ["First?", "Second?", "Third?"]
        self.assertEqual(count_questions(value), 3)
        self.assertEqual(len(question_items(value)), 3)
        self.assertEqual(count_questions("1. a?\n2. b?"), 2)


class GuidanceNormalizationTest(unittest.TestCase):
    def test_short_form_aliases_map_to_canonical(self):
        canonical, normalized, unknown = normalize_guidance(["Strategic", "Technical"])
        self.assertEqual(canonical, [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL])
        self.assertTrue(normalized)
        self.assertEqual(unknown, [])

    def test_canonical_values_pass_through_without_warning(self):
        canonical, normalized, unknown = normalize_guidance(
            [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL]
        )
        self.assertEqual(canonical, [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL])
        self.assertFalse(normalized)
        self.assertEqual(unknown, [])

    def test_semicolon_string_input(self):
        canonical, _normalized, _unknown = normalize_guidance("Strategic;Technical")
        self.assertEqual(canonical, [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL])

    def test_slash_variants(self):
        canonical, _n, _u = normalize_guidance(["Strategic/Executive", "Tactical"])
        self.assertEqual(canonical, [GUIDANCE_STRATEGIC, GUIDANCE_TECHNICAL])

    def test_dedupe_preserves_first_order(self):
        canonical, _n, _u = normalize_guidance(["Technical", "Strategic", "Tactical"])
        self.assertEqual(canonical, [GUIDANCE_TECHNICAL, GUIDANCE_STRATEGIC])

    def test_unknown_values_collected(self):
        canonical, _normalized, unknown = normalize_guidance(["Strategic", "Bogus"])
        self.assertEqual(canonical, [GUIDANCE_STRATEGIC])
        self.assertEqual(unknown, ["Bogus"])

    def test_guidance_to_list_handles_shapes(self):
        self.assertEqual(guidance_to_list(None), [])
        self.assertEqual(guidance_to_list(""), [])
        self.assertEqual(guidance_to_list("A;B; ;C"), ["A", "B", "C"])
        self.assertEqual(guidance_to_list(["A", " B ", ""]), ["A", "B"])


class PlaceholderDetectionTest(unittest.TestCase):
    def test_known_driver_placeholder(self):
        self.assertTrue(
            is_placeholder("[needs your input \u2014 what's driving this for you right now?]")
        )

    def test_known_question_placeholder(self):
        self.assertTrue(
            is_placeholder(
                "[needs your input \u2014 what 3-5 specific questions do you want a "
                "faculty member to answer? (1-3 for Faculty Poll)]"
            )
        )

    def test_optional_placeholder(self):
        self.assertTrue(is_placeholder("[optional]"))
        self.assertTrue(
            is_placeholder("[optional \u2014 team size, current tools, policies]")
        )

    def test_lightly_edited_placeholder_still_caught(self):
        self.assertTrue(is_placeholder("[needs your input - the board ask]"))

    def test_real_content_is_not_a_placeholder(self):
        self.assertFalse(is_placeholder("How should we structure our SOC?"))
        self.assertFalse(is_placeholder("Strategic / Executive"))
        self.assertFalse(is_placeholder(""))
        self.assertFalse(is_placeholder("   "))
        self.assertFalse(is_placeholder(None))
        self.assertFalse(is_placeholder(123))

    def test_bracketed_real_aside_not_flagged(self):
        # A bracketed clause that isn't an editor placeholder should pass.
        self.assertFalse(is_placeholder("[see attached architecture diagram]"))


if __name__ == "__main__":
    unittest.main()
