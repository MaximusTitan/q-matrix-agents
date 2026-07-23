"""
tests/test_prerequisite_l3.py

Unit-level checks for the pure logic in agents/prerequisite_l3.py and the grade-
ordering helper in skills/kb_access.py — no KB_ROOT or live LLM call required,
since these only exercise the parts of L3 that don't need either (edge key
construction/validation and the empty-candidate-pool short-circuit, which never
calls the LLM at all).

Run from repo root:
    python tests/test_prerequisite_l3.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.prerequisite_l3 import _edge_key, _extract_cross_grade_edges, run
from skills.kb_access import _grade_sort_key

# Test 1 — grade ordering is numeric, not lexical
print("TEST 1: _grade_sort_key numeric ordering")
grades = ["Grade10", "Grade8", "Grade9", "Grade2"]
ordered = sorted(grades, key=_grade_sort_key)
assert ordered == ["Grade2", "Grade8", "Grade9", "Grade10"], ordered
print(f"  ✓ {grades} -> {ordered}")

# Non-numeric grade names must not raise, and sort before any numeric grade.
print("TEST 1b: _grade_sort_key on non-numeric grade name")
mixed = sorted(["Grade8", "Foundation", "Grade1"], key=_grade_sort_key)
assert mixed[0] == "Foundation", mixed
print(f"  ✓ non-numeric grade sorts first (treated as earliest/unknown): {mixed}")

# Test 2 — _edge_key is a stable, distinct composite per (grade, chapter, item)
print("TEST 2: _edge_key composite uniqueness")
k1 = _edge_key("Grade7", "Chapter04_Fractions", "Simplify a fraction")
k2 = _edge_key("Grade8", "Chapter04_Fractions", "Simplify a fraction")
assert k1 != k2, "same chapter name in different grades must not collide"
print(f"  ✓ {k1!r} != {k2!r}")

# Test 3 — _extract_cross_grade_edges keeps only pool-valid (grade, chapter, item)
# triples and drops everything else with a warning, never raising.
print("TEST 3: _extract_cross_grade_edges validation")
target_valid = {"Solve a quadratic equation by factorisation"}
pool_valid = {
    _edge_key("Grade8", "Chapter02_Factorisation", "Factorise a quadratic expression"),
}
parsed = {
    "skill_prerequisites": [
        {
            "skill": "Solve a quadratic equation by factorisation",
            "prerequisites": [
                # Valid — in both target and pool.
                {"grade": "Grade8", "chapter": "Chapter02_Factorisation",
                 "skill": "Factorise a quadratic expression", "reason": "Needs factorisation."},
                # Invalid — not in the screened candidate pool, must be dropped.
                {"grade": "Grade3", "chapter": "Chapter01_Addition",
                 "skill": "Add two-digit numbers", "reason": "Technically uses addition."},
            ],
        },
        # Invalid target — not one of this chapter's own skills, must be dropped.
        {
            "skill": "A skill that does not exist in the target chapter",
            "prerequisites": [],
        },
    ],
}
edges, warnings = _extract_cross_grade_edges(parsed, "skill_prerequisites", "skill", target_valid, pool_valid)
assert list(edges.keys()) == ["Solve a quadratic equation by factorisation"], edges
kept = edges["Solve a quadratic equation by factorisation"]
assert len(kept) == 1, kept
assert kept[0]["grade"] == "Grade8" and kept[0]["chapter"] == "Chapter02_Factorisation"
assert len(warnings) == 2, warnings  # one dropped prereq + one dropped target
print(f"  ✓ kept {len(kept)} valid edge, dropped {len(warnings)} invalid entr(y/ies) with warnings")

# Test 4 — run() with an empty candidate pool short-circuits: no LLM call, empty
# columns, a warning explaining why. If this accidentally called the LLM it would
# raise (no API key / network in this test environment) instead of returning cleanly.
print("TEST 4: run() empty candidate pool short-circuit (no LLM call)")
target_rows = [
    {"board": "CBSE", "subject": "Maths", "grade": "Grade9", "chapter": "Chapter02_Quadratics",
     "concept": "Quadratic Equations", "skill": "Solve a quadratic equation by factorisation"},
]
result = run(
    target_rows=target_rows,
    candidate_pool={},
    sibling_rows_by_grade_chapter={},
    board="CBSE", subject="Maths", grade="Grade9", chapter="Chapter02_Quadratics",
)
assert result["concept_edges"] == {} and result["skill_edges"] == {}, result
assert result["rows"][0]["prereq_concepts_L3_prior_grade"] == []
assert result["rows"][0]["prereq_skills_L3_prior_grade"] == []
assert result["usage"] == {} and result["cost_usd"] == 0.0
assert len(result["warnings"]) == 1
print(f"  ✓ empty pool -> no LLM call, empty columns, warning: {result['warnings'][0]!r}")

print("\nAll tests passed.")
