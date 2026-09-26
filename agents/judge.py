"""
agents/judge.py

Judge Agent.
Chooses the single best CSV among SEVERAL candidates that have all already passed
both quality checks (universal rules + full CSM coverage). Runs once at the end of a
run when ≥2 passing candidates exist.

Because every candidate is already correct, the judge ranks on faithfulness and
pedagogical quality (not size), per the rubric in prompts/judge_prompt.md.

Input:  candidates, concept_skill_map, universal_rules, board, subject, grade, chapter
Output: dict {"chosen_id", "rationale", "candidates": [{id, verdict, note, strengths, concerns}]}

With an evaluation model (skills.evaluate.is_evaluation_model) each candidate is scored
independently on the judge prompt's priority criteria (one rubric question each), the
weighted mean picks the winner, and rationale/strengths/concerns are assembled from
those scores — no free text is generated.

Skills used:
    llm      — call_llm (chat models)
    evaluate — evaluate_many (evaluation models)
"""

import json
import os
from skills.llm import call_llm, add_usage, DEFAULT_MODEL
from skills import evaluate

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "judge_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def _parse_llm_json(raw: str) -> dict | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[judge] LLM returned invalid JSON. Error: {e}\nRaw:\n{raw[:500]}")
        return None


def _fallback_choice(candidates: list[dict], reason: str, usage: dict, cost_usd: float) -> dict:
    """Deterministic pick when the LLM output is unusable: prefer a generated
    candidate, else the earliest by cycle. `usage`/`cost_usd` still reflect whatever
    was spent by the LLM attempts before falling back."""
    generated = [c for c in candidates if c.get("source") == "generated"]
    pool = generated or candidates
    chosen = min(pool, key=lambda c: c.get("cycle", 0))
    return {
        "chosen_id": chosen["id"],
        "rationale": f"(fallback) {reason}",
        "candidates": [
            {
                "id":        c["id"],
                "verdict":   "chosen" if c["id"] == chosen["id"] else "rejected",
                "note":      "Selected by deterministic fallback." if c["id"] == chosen["id"] else "",
                "strengths": [],
                "concerns":  [],
            }
            for c in candidates
        ],
        "usage": usage,
        "cost_usd": cost_usd,
    }


# Criteria in prompts/judge_prompt.md priority order: (key, label, weight, question, levels).
_RUBRIC = [
    ("coverage", "faithful CSM coverage", 0.4,
     "How faithfully does `candidate_csv` cover every concept and skill in "
     "`expected_concept_skill_map`, without over-decomposition, duplication or padding?",
     ["poor: expected items missing, or heavy duplication/padding",
      "fair: covered, but with noticeable over-decomposition or duplicated rows",
      "good: covered with only minor redundancy",
      "excellent: every expected item covered once, with no padding"]),
    ("boundaries", "concept boundaries", 0.3,
     "Do the concepts in `candidate_csv` match the intent of the expected concepts, "
     "without merging distinct concepts into buckets or splitting one concept into several?",
     ["poor: many merged buckets or artificial splits",
      "fair: several boundary problems",
      "good: one or two boundary problems",
      "excellent: concept boundaries match the expected map"]),
    ("skill_quality", "skill quality", 0.2,
     "Are the skills in `candidate_csv` concrete, distinct and pedagogically meaningful, "
     "with any skill beyond the expected map clearly justified?",
     ["poor: vague, overlapping or unjustified skills",
      "fair: many skills vague or unjustified",
      "good: mostly concrete and distinct",
      "excellent: every skill concrete, distinct and justified"]),
    ("focus", "no extraneous content", 0.1,
     "Is `candidate_csv` free of off-syllabus or filler rows?",
     ["poor: many filler or off-syllabus rows",
      "fair: several filler rows",
      "good: one or two filler rows",
      "excellent: no filler or off-syllabus rows"]),
]
_MAX_SCORE = len(_RUBRIC[0][4]) - 1
# Weighted means closer than this count as a tie, broken by the judge prompt's tie-breaker
# (generated over doctored), then earliest cycle.
_TIE_MARGIN = 0.05


def _judge_with_evaluator(candidates, concept_skill_map, model):
    """Score each candidate on _RUBRIC and pick the best. Same return shape as run()."""
    csm = {
        "concepts": (concept_skill_map or {}).get("concepts", []),
        "skills":   (concept_skill_map or {}).get("skills", []),
    }
    requests = [
        (
            {"expected_concept_skill_map": csm, "candidate_csv": c["csv"]},
            {f"{i}_{key}": evaluate.score(question, levels)
             for key, _, _, question, levels in _RUBRIC},
        )
        for i, c in enumerate(candidates)
    ]
    try:
        answers, usage, cost = evaluate.evaluate_many(requests, model)
    except (evaluate.EvaluationError, ValueError) as e:
        print(f"[judge] Evaluation failed ({e}) — falling back deterministically")
        return _fallback_choice(candidates, f"evaluation failed: {e}", {}, 0.0)

    scored = []
    for i, c in enumerate(candidates):
        dims = {key: float(answers[f"{i}_{key}"]["score"]) for key, *_ in _RUBRIC}
        total = sum(weight * dims[key] for key, _, weight, *_ in _RUBRIC)
        scored.append((c, dims, total))

    best_total = max(total for _, _, total in scored)
    contenders = [(c, dims, total) for c, dims, total in scored if best_total - total <= _TIE_MARGIN]
    chosen = min(contenders, key=lambda t: (t[0].get("source") != "generated", t[0].get("cycle", 0)))[0]

    def fmt(label, value):
        return f"{label} {value:.1f}/{_MAX_SCORE}"

    out = []
    for c, dims, total in scored:
        labelled = [(label, dims[key]) for key, label, *_ in _RUBRIC]
        out.append({
            "id":        c["id"],
            "verdict":   "chosen" if c["id"] == chosen["id"] else "rejected",
            "note":      f"Weighted rubric score {total:.2f}/{_MAX_SCORE}.",
            "strengths": [fmt(label, v) for label, v in labelled if v >= _MAX_SCORE - 0.5],
            "concerns":  [fmt(label, v) for label, v in labelled if v < _MAX_SCORE - 1.5],
        })
    totals = ", ".join(f"{c['id']}={total:.2f}" for c, _, total in scored)
    tie_note = " (tie broken: generated over doctored, then earliest cycle)" if len(contenders) > 1 else ""
    print(f"[judge] Chose {chosen['id']}")
    return {
        "chosen_id": chosen["id"],
        "rationale": f"Highest weighted rubric score among passing candidates: {totals}{tie_note}.",
        "candidates": out,
        "usage": usage,
        "cost_usd": cost,
    }


def run(
    candidates: list[dict],
    concept_skill_map: dict,
    universal_rules: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Choose the best CSV among already-passing candidates.

    Args:
        candidates: List of dicts, each with keys:
            id (str), source ("generated"|"doctored"), cycle (int),
            concept_count (int), skill_count (int), csv (str)
        concept_skill_map: Expected concepts and skills (authoritative).
        universal_rules:   Universal (+ grade) rules the CSVs were written against.
        board, subject, grade, chapter: Target identifiers.

    Returns:
        {"chosen_id": str, "rationale": str,
         "candidates": [{"id","verdict","note","strengths","concerns"}]}

        chosen_id is always one of the input candidate ids (falls back
        deterministically if the LLM output is unusable).
    """
    print(f"[judge] Choosing among {len(candidates)} passing candidate(s)")

    if evaluate.is_evaluation_model(model):
        return _judge_with_evaluator(candidates, concept_skill_map, model)

    valid_ids = {c["id"] for c in candidates}

    expected_concepts = concept_skill_map.get("concepts", []) if concept_skill_map else []
    expected_skills   = concept_skill_map.get("skills",   []) if concept_skill_map else []

    candidate_blocks = []
    for c in candidates:
        candidate_blocks.append(
            f"""--- CANDIDATE id={c['id']} (source={c.get('source')}, cycle={c.get('cycle')}, """
            f"""concepts={c.get('concept_count')}, skills={c.get('skill_count')}) ---
{c['csv']}"""
        )

    user_content = f"""board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- EXPECTED CONCEPT-SKILL-MAP ---
concepts:
{json.dumps(expected_concepts, indent=2, ensure_ascii=False)}
skills:
{json.dumps(expected_skills, indent=2, ensure_ascii=False)}

--- UNIVERSAL RULES ---
{universal_rules}

--- CANDIDATES ({len(candidates)}) ---
{chr(10).join(candidate_blocks)}"""

    result = None
    usage_total = {}
    cost_total = 0.0
    for attempt in range(2):
        raw, usage, cost = call_llm(SYSTEM_PROMPT, user_content, model=model)
        usage_total = add_usage(usage_total, usage)
        cost_total += cost
        result = _parse_llm_json(raw)
        if result is not None and result.get("chosen_id") in valid_ids:
            break
        print(f"[judge] Retrying — invalid/unusable output ({attempt + 1}/2)")
        result = None

    if result is None:
        print("[judge] LLM output unusable after retry — falling back deterministically")
        return _fallback_choice(candidates, "judge output unparseable", usage_total, cost_total)

    result["usage"] = usage_total
    result["cost_usd"] = cost_total
    print(f"[judge] Chose {result['chosen_id']}")
    return result
