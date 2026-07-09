"""
skills/diff.py

Semantic diff of a generated CSV against a concept-skill-map.
Used by the Eval Agent for Check 2.

The concept-skill-map now contains two flat lists:
    concepts: ["Sound", "Propagation of Sound", ...]
    skills:   ["Identify sources of sound", "Calculate speed of sound", ...]

The Eval Agent diffs all CSV concepts against the concepts list,
and all CSV skills against the skills list — independently.

Pure string matching is insufficient — "Identify types of friction" and
"Identify friction types" are semantically the same. The LLM judges coverage.

Coverage runs in two passes:
  Pass 1 — an LLM judges which expected items are covered, mapping each to the
           one OR MORE actual items that cover it (1:N union coverage).
  Pass 2 — whenever pass 1 leaves any "missing" items, a focused reconciliation
           LLM call re-checks them against the FULL pool of leftover ("extra")
           actual items. This catches single-pass recall misses (e.g. "Medians of
           a triangle" vs "Median of a triangle", imperative-vs-gerund phrasing,
           or a skill split across several actual items). A token-containment
           score is computed only to rank/surface candidate extras in the audit
           trail — it does NOT gate what the LLM sees, so lexically-distant but
           semantically-equivalent phrasings are still recovered. The LLM has
           final say and is told not to over-merge genuinely different items.
"""

import json
import re
from skills.csv_utils import parse_csv
from skills.llm import call_llm, add_usage
from skills.pricing import cost_usd


SYSTEM_PROMPT = """You are a curriculum coverage auditor.

You will be given:
1. EXPECTED — two flat lists: all concepts and all skills from a chapter map
2. ACTUAL — all concepts and all skills present in a generated CSV

Your job is to:
1. Identify which expected concepts and skills are NOT adequately covered in the actual CSV.
2. For each expected concept/skill that IS covered, identify which actual item(s) cover it.

Rules:
- Two concepts are equivalent if they refer to the same topic, even if worded differently.
  Example: "Types of friction" and "Friction types" are equivalent.
- A skill is covered if the CSV contains a skill with the same intent, even if phrased differently.
  Example: "Calculate frictional force" and "Compute friction force" are equivalent.
- Ignore surface differences in wording. Singular/plural and minor truncations are equivalent.
  Example: "Medians of a triangle" and "Median of a triangle" are equivalent.
- An expected item may be covered by ONE OR MORE actual items COLLECTIVELY. If a single
  expected skill is split across several actual skills that together address its full intent,
  it is COVERED — list all of the covering actual items.
  Example: expected "Classify triangles by sides as scalene, isosceles, or equilateral" is
  covered by actual ["Classify triangles by sides as scalene", "...as isosceles", "...as equilateral"].
- Do NOT flag minor wording differences, truncations, or splits as missing — only flag genuinely
  absent concepts or skills.
- Do NOT merge genuinely different items. "Properties of equilateral triangles" and
  "Properties of isosceles triangles" are DIFFERENT concepts.
- In matched_concepts/matched_skills, use the exact strings from the expected and actual lists.

Respond ONLY with a valid JSON object. No explanation, no markdown, no preamble.

Format:
{
  "missing_concepts": ["concept as it appears in expected list"],
  "missing_skills": ["skill as it appears in expected list"],
  "matched_concepts": {"expected concept": ["actual concept(s) that cover it"]},
  "matched_skills": {"expected skill": ["actual skill(s) that cover it"]},
  "reasoning": "one sentence explaining your decision"
}"""


RECONCILE_PROMPT = """You are a curriculum coverage auditor performing a focused second review.

An earlier pass marked some expected items as MISSING. You are now given those missing
expected items together with the FULL pool of leftover ("extra") actual items from the CSV
that were not yet matched to anything. (A similarity score 0-1 is provided only as a hint to
rank likely matches — judge by MEANING, not by the score.)

Decide, for each missing expected item, whether it is actually COVERED by one OR MORE of the
extra actual items COLLECTIVELY.

Rules:
- Judge by intent, not surface wording. The CSV often phrases skills as gerunds or verbose
  descriptions while the expected list uses imperatives — these are equivalent:
    "State the properties of an equilateral triangle including side lengths and angle measures"
    == "Stating that all three sides of an equilateral triangle are equal and all three angles measure 60 degrees"
    "Drawing all three medians..." == "Draw medians of a triangle and state how many medians a triangle has"
- Singular/plural and minor truncations are equivalent ("Medians of a triangle" == "Median of a triangle").
- A single expected skill split across several actual skills that together address its full
  intent is COVERED — list all of the covering actual items.
- An expected item is COVERED only if the actual item(s) address its FULL intent. If the
  expected item asks for several things and the extras cover only some, it is NOT covered.
  Example: "Identify the exterior angle AND its two interior opposite angles" is NOT covered by
  an extra that only defines the exterior angle.
- Do NOT merge genuinely different items. "Properties of equilateral triangles" and
  "Properties of isosceles triangles" are DIFFERENT — lexical similarity alone is not enough.

Respond ONLY with a valid JSON object. No explanation, no markdown, no preamble.

Format:
{
  "now_covered_concepts": {"expected concept": ["covering actual concept(s)"]},
  "now_covered_skills": {"expected skill": ["covering actual skill(s)"]}
}
Include only items you are reclassifying as covered. Use the exact strings given to you."""


# Similarity is a display/ranking HINT, not a recall gate — the reconciliation LLM
# always sees the full extras pool. These only control what's surfaced as a
# candidate in the audit trail (and how many), so it stays readable.
_CAND_DISPLAY_FLOOR = 0.0   # 0 = list every extra as a candidate (no floor)
_CAND_TOP_K         = None  # None = no cap; show all extras, ranked by score


def _tokens(s: str) -> set:
    """Lowercased alphanumeric word tokens of a string."""
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _containment(a: str, b: str) -> float:
    """
    Token containment coefficient: |A ∩ B| / |smaller set|.

    Chosen over a plain ratio because the failure modes here are lexical subsets:
    a truncated/split actual item is a strict token-subset of the expected item
    (scores ~1.0), and plural/singular differences barely move the score.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _matched_values_lower(matched: dict) -> set:
    """Flatten all actual items referenced by a matched_* map, lowercased.

    Tolerates both the new list-valued shape and a legacy bare-string value.
    """
    out = set()
    for v in matched.values():
        items = v if isinstance(v, list) else [v]
        for item in items:
            if item:
                out.add(item.strip().lower())
    return out


def _compute_extras(actual: list, matched: dict) -> list:
    """Actual items not referenced by any matched_* value (case-insensitive)."""
    used = _matched_values_lower(matched)
    return [a for a in actual if a.strip().lower() not in used]


def _strip_fences(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()
    return cleaned


def _normalize_matched(matched: dict) -> dict:
    """Coerce a matched_* map to list-valued form (LLM may emit a bare string)."""
    out = {}
    for k, v in matched.items():
        if isinstance(v, list):
            out[k] = [str(x) for x in v if x]
        elif v:
            out[k] = [str(v)]
        else:
            out[k] = []
    return out


def _reconcile(
    missing_concepts: list,
    missing_skills: list,
    extra_concepts: list,
    extra_skills: list,
) -> dict:
    """
    Second pass — re-check every still-missing item against the FULL pool of
    leftover ("extra") actual items, and ask the LLM which are actually covered
    (possibly by a union of extras).

    Similarity is NOT used to gate what reaches the LLM — the LLM sees all extras,
    so semantically-equivalent but lexically-different phrasings are still caught.
    Similarity only ranks/limits the candidates surfaced in the audit trail.

    Returns reclassification maps {expected: [covering actual, ...]} for concepts
    and skills, plus a per-item audit `detail`. Makes at most one LLM call.
    """

    def ranked_candidates(missing_items, extras):
        # All extras per missing item, ranked by similarity, for display only.
        out = {}
        for m in missing_items:
            hits = sorted(
                ((e, round(_containment(m, e), 3)) for e in extras),
                key=lambda p: p[1],
                reverse=True,
            )
            shown = [{"actual": e, "score": s} for e, s in hits if s >= _CAND_DISPLAY_FLOOR][:_CAND_TOP_K]
            if shown:
                out[m] = shown
        return out

    def build_detail(missing_items, cands, extras, now_covered):
        # One audit entry per missing item that either has a lexically-similar
        # candidate OR was recovered by the LLM (so it carries a visible reason).
        detail = {}
        for m in missing_items:
            covered_by = now_covered.get(m, [])
            shown = list(cands.get(m, []))
            # Ensure any LLM-confirmed cover is shown even if it ranked below the floor.
            shown_actuals = {c["actual"].lower() for c in shown}
            for cb in covered_by:
                if cb.lower() not in shown_actuals:
                    shown.append({"actual": cb, "score": round(_containment(m, cb), 3)})
            if not shown and not covered_by:
                continue
            detail[m] = {
                "outcome":    "recovered" if covered_by else "rejected",
                "candidates": shown,        # [{"actual": ..., "score": ...}]
                "covered_by": covered_by,   # subset confirmed by the LLM ([] if rejected)
            }
        return detail

    empty = {
        "now_covered_concepts": {},
        "now_covered_skills": {},
        "detail": {"concepts": {}, "skills": {}},
        "usage": {},
    }

    # Only worth a call if some missing item has a same-kind pool to match against.
    if not ((missing_concepts and extra_concepts) or (missing_skills and extra_skills)):
        return empty

    concept_cands = ranked_candidates(missing_concepts, extra_concepts)
    skill_cands   = ranked_candidates(missing_skills,   extra_skills)

    # The LLM sees the FULL extras pool — similarity hints are attached only where
    # available so it can rank, but recall is never gated by the score.
    user_content = (
        "MISSING CONCEPTS (re-check for coverage):\n"
        + json.dumps(missing_concepts, indent=2)
        + "\n\nMISSING SKILLS (re-check for coverage):\n"
        + json.dumps(missing_skills, indent=2)
        + "\n\nFULL POOL OF EXTRA (unmatched) ACTUAL CONCEPTS:\n"
        + json.dumps(extra_concepts, indent=2)
        + "\n\nFULL POOL OF EXTRA (unmatched) ACTUAL SKILLS:\n"
        + json.dumps(extra_skills, indent=2)
        + "\n\nSIMILARITY HINTS (expected -> [most lexically-similar extras], score 0-1):\n"
        + json.dumps({"concepts": concept_cands, "skills": skill_cands}, indent=2)
    )

    raw, usage = call_llm(RECONCILE_PROMPT, user_content)
    try:
        result = json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        # Best-effort — on parse failure change nothing, but keep the audit trail.
        return {
            "now_covered_concepts": {},
            "now_covered_skills": {},
            "detail": {
                "concepts": build_detail(missing_concepts, concept_cands, extra_concepts, {}),
                "skills":   build_detail(missing_skills,   skill_cands,   extra_skills,   {}),
            },
            "usage": usage,
        }

    now_covered_concepts = _normalize_matched(result.get("now_covered_concepts", {}))
    now_covered_skills   = _normalize_matched(result.get("now_covered_skills",   {}))

    return {
        "now_covered_concepts": now_covered_concepts,
        "now_covered_skills":   now_covered_skills,
        "detail": {
            "concepts": build_detail(missing_concepts, concept_cands, extra_concepts, now_covered_concepts),
            "skills":   build_detail(missing_skills,   skill_cands,   extra_skills,   now_covered_skills),
        },
        "usage": usage,
    }


def diff_full(raw_csv: str, concept_skill_map: dict) -> dict:
    """
    Semantically diff a generated CSV against a concept-skill-map.
    Uses the LLM to judge coverage rather than exact string matching, then a
    focused reconciliation pass that re-checks any leftover "missing" items
    against the full pool of unmatched actual items to recover near-misses.

    Args:
        raw_csv:           Raw CSV string from the Generator Agent.
        concept_skill_map: Parsed concept-skill-map dict from the KB.
                           Expected keys: "concepts" (list), "skills" (list)

    Returns:
        Dict with keys:
            passed           (bool)  — True if no semantic gaps found
            missing_concepts (list)  — Concepts not covered in CSV
            missing_skills   (list)  — Skills not covered in CSV
            matched_concepts (dict)  — {expected concept: [covering actual concept(s)]}
            matched_skills   (dict)  — {expected skill: [covering actual skill(s)]}
            extra_concepts   (list)  — Actual concepts not covering any expected concept
            extra_skills     (list)  — Actual skills not covering any expected skill
            reconciliation   (dict)  — Pass-2 audit trail, keyed by "concepts"/"skills":
                                       {expected item: {outcome: "recovered"|"rejected",
                                        candidates: [{actual, score}], covered_by: [...]}}
            feedback         (list)  — Human-readable summary strings
            reasoning        (str)   — LLM's one-line reasoning
    """
    rows = parse_csv(raw_csv)

    # Extract flat lists from the new map structure
    expected_concepts = concept_skill_map.get("concepts", [])
    expected_skills   = concept_skill_map.get("skills",   [])

    # Extract flat lists from CSV
    actual_concepts = list({row["concept"].strip() for row in rows})
    actual_skills   = list({row["skill"].strip()   for row in rows})

    user_content = f"""EXPECTED (from chapter map):
Concepts: {json.dumps(expected_concepts, indent=2)}
Skills:   {json.dumps(expected_skills, indent=2)}

ACTUAL (from generated CSV):
Concepts: {json.dumps(actual_concepts, indent=2)}
Skills:   {json.dumps(actual_skills, indent=2)}"""

    raw_response, usage_total = call_llm(SYSTEM_PROMPT, user_content)

    try:
        result = json.loads(_strip_fences(raw_response))
    except json.JSONDecodeError:
        return {
            "passed":           False,
            "missing_concepts": [],
            "missing_skills":   [],
            "matched_concepts": {},
            "matched_skills":   {},
            "extra_concepts":   actual_concepts,
            "extra_skills":     actual_skills,
            "reconciliation":   {"concepts": {}, "skills": {}},
            "feedback":         ["Check 2 evaluation failed — LLM returned unparseable output."],
            "reasoning":        "Parse error",
            "usage":            usage_total,
            "cost_usd":         cost_usd(usage_total),
        }

    missing_concepts  = result.get("missing_concepts",  [])
    missing_skills    = result.get("missing_skills",    [])
    matched_concepts  = _normalize_matched(result.get("matched_concepts",  {}))
    matched_skills    = _normalize_matched(result.get("matched_skills",    {}))
    reasoning         = result.get("reasoning",          "")

    # ── Pass 2: similarity-triggered reconciliation of "missing" near-misses ──
    extra_concepts = _compute_extras(actual_concepts, matched_concepts)
    extra_skills   = _compute_extras(actual_skills,   matched_skills)

    reconciliation = {"concepts": {}, "skills": {}}

    if missing_concepts or missing_skills:
        recon = _reconcile(missing_concepts, missing_skills, extra_concepts, extra_skills)
        reconciliation = recon["detail"]
        usage_total = add_usage(usage_total, recon.get("usage") or {})

        for expected, covering in recon["now_covered_concepts"].items():
            if expected in missing_concepts:
                missing_concepts.remove(expected)
                matched_concepts[expected] = covering
        for expected, covering in recon["now_covered_skills"].items():
            if expected in missing_skills:
                missing_skills.remove(expected)
                matched_skills[expected] = covering

        # Recompute extras after any reclassification
        extra_concepts = _compute_extras(actual_concepts, matched_concepts)
        extra_skills   = _compute_extras(actual_skills,   matched_skills)

    feedback = []
    if missing_concepts:
        feedback.append(
            f"{len(missing_concepts)} concept(s) not semantically covered: "
            + ", ".join(missing_concepts)
        )
    if missing_skills:
        feedback.append(
            f"{len(missing_skills)} skill(s) not semantically covered: "
            + ", ".join(missing_skills)
        )

    return {
        "passed":           len(missing_concepts) == 0 and len(missing_skills) == 0,
        "missing_concepts": missing_concepts,
        "missing_skills":   missing_skills,
        "matched_concepts": matched_concepts,
        "matched_skills":   matched_skills,
        "extra_concepts":   extra_concepts,
        "extra_skills":     extra_skills,
        "reconciliation":   reconciliation,
        "feedback":         feedback,
        "reasoning":        reasoning,
        "usage":            usage_total,
        "cost_usd":         cost_usd(usage_total),
    }
