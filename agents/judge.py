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

Skills used:
    llm — call_llm
"""

import json
import os
from skills.llm import call_llm

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


def _fallback_choice(candidates: list[dict], reason: str) -> dict:
    """Deterministic pick when the LLM output is unusable: prefer a generated
    candidate, else the earliest by cycle."""
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
    }


def run(
    candidates: list[dict],
    concept_skill_map: dict,
    universal_rules: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    model: str = None,
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

    usage_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
    }
    result = None
    for attempt in range(2):
        raw, usage = call_llm(SYSTEM_PROMPT, user_content, model=model)
        usage_totals = {
            "prompt_tokens": usage_totals["prompt_tokens"] + usage.get("prompt_tokens", 0),
            "completion_tokens": usage_totals["completion_tokens"] + usage.get("completion_tokens", 0),
            "total_tokens": usage_totals["total_tokens"] + usage.get("total_tokens", 0),
            "cost": usage_totals["cost"] + usage.get("cost", 0.0),
        }
        result = _parse_llm_json(raw)
        if result is not None and result.get("chosen_id") in valid_ids:
            break
        print(f"[judge] Retrying — invalid/unusable output ({attempt + 1}/2)")
        result = None

    if result is None:
        print("[judge] LLM output unusable after retry — falling back deterministically")
        fallback = _fallback_choice(candidates, "judge output unparseable")
        fallback["usage"] = usage_totals
        return fallback

    print(f"[judge] Chose {result['chosen_id']}")
    result["usage"] = usage_totals
    return result
