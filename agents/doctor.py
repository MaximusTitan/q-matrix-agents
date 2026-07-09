"""
agents/doctor.py

Doctor Agent.
Surgically patches a curriculum CSV that PASSED Check 1 (universal rules) but
FAILED Check 2 (concept-skill-map coverage), instead of regenerating from scratch.

It consumes the Check-2 coverage analysis (matched / missing / extra / reconciliation)
and applies the judgement rules in prompts/doctor_prompt.md:
    - keep a faithful umbrella CSV concept; split a lossy over-generalization back
      into the distinct expected concepts
    - add missing concepts/skills
    - decide per-extra whether to keep or drop

The orchestrator re-verifies the doctored CSV through BOTH checks afterwards.

Input:  failing_csv, check2, concept_skill_map, universal_rules, board, subject, grade, chapter
Output: {"csv": str, "rows": list} on success, or {"csv": None, "error": str} on failure

Skills used:
    llm        — call_llm_structured
    csv_utils  — CONCEPT_SKILL_ROWS_TOOL, rows_from_pairs, validate_rows, csv_to_text
"""

import json
import os
from skills.llm import call_llm_structured, add_usage
from skills.pricing import cost_usd
from skills.csv_utils import CONCEPT_SKILL_ROWS_TOOL, rows_from_pairs, validate_rows, csv_to_text

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "doctor_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def _format_coverage(check2: dict) -> str:
    """Render the Check-2 coverage analysis as a compact, LLM-readable block."""
    return json.dumps(
        {
            "matched_concepts":  check2.get("matched_concepts",  {}),
            "matched_skills":    check2.get("matched_skills",    {}),
            "missing_concepts":  check2.get("missing_concepts",  []),
            "missing_skills":    check2.get("missing_skills",    []),
            "extra_concepts":    check2.get("extra_concepts",    []),
            "extra_skills":      check2.get("extra_skills",      []),
            "reconciliation":    check2.get("reconciliation",    {}),
        },
        indent=2,
        ensure_ascii=False,
    )


def run(
    failing_csv: str,
    check2: dict,
    concept_skill_map: dict,
    universal_rules: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
) -> dict:
    """
    Surgically patch a CSV that passed Check 1 but failed Check 2 (CSM coverage).

    Unlike a full regeneration, this preserves correct rows and only applies the
    edits the coverage analysis requires (keep faithful umbrella concepts, split
    lossy buckets back into expected concepts, add missing items, prune off-syllabus
    extras). See prompts/doctor_prompt.md for the judgement rules.

    Args:
        failing_csv:       The CSV that failed Check 2 (already valid vs universal rules).
        check2:            The full check2 dict from eval (matched/missing/extra/reconciliation).
        concept_skill_map: Expected concepts and skills for this chapter.
        universal_rules:   Universal (+ grade) rules text, so the patch stays compliant.
        board, subject, grade, chapter: The four fixed identifier columns (constants).

    Returns:
        On success: {"csv": corrected_csv, "rows": [parsed rows]}
        On failure (the LLM submitted invalid rows twice — e.g. an empty rows list or an
        empty concept/skill):
            {"csv": None, "error": <message>}
    """
    print(f"[doctor] Doctoring CSV — {board}/{subject}/{grade}/{chapter}")

    expected_concepts = concept_skill_map.get("concepts", [])
    expected_skills   = concept_skill_map.get("skills",   [])

    base_user_content = f"""board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- FAILING CSV ---
{failing_csv}

--- EXPECTED CONCEPT-SKILL-MAP ---
concepts:
{json.dumps(expected_concepts, indent=2, ensure_ascii=False)}
skills:
{json.dumps(expected_skills, indent=2, ensure_ascii=False)}

--- COVERAGE ANALYSIS ---
{_format_coverage(check2)}

--- UNIVERSAL RULES ---
{universal_rules}"""

    correction = ""
    last_error = None
    usage_total = {}
    for attempt in range(2):
        print(f"[doctor] Calling LLM (attempt {attempt + 1}/2)...")
        result, usage = call_llm_structured(
            SYSTEM_PROMPT, base_user_content + correction, CONCEPT_SKILL_ROWS_TOOL
        )
        usage_total = add_usage(usage_total, usage)
        rows = rows_from_pairs(board, subject, grade, chapter, result.get("rows", []))

        try:
            validate_rows(rows)
        except ValueError as e:
            last_error = str(e)
            print(f"[doctor] Doctored rows invalid (attempt {attempt + 1}/2): {e}")
            # Echo the rejected rows back so the model can see and fix the exact
            # offending one, instead of resubmitting the whole set blind.
            correction = (
                "\n\n--- IMPORTANT ---\n"
                f"Your previous submission was rejected: {last_error}\n\n"
                "--- YOUR PREVIOUS ROWS ---\n"
                f"{json.dumps(result.get('rows', []), indent=2, ensure_ascii=False)}\n"
                "--- END PREVIOUS ROWS ---\n\n"
                "Call the tool again with the corrected, COMPLETE list of rows."
            )
            continue

        print(f"[doctor] Doctored CSV produced ({len(rows)} rows)")
        return {
            "csv": csv_to_text(rows), "rows": rows,
            "usage": usage_total, "cost_usd": cost_usd(usage_total),
        }

    print("[doctor] Doctoring failed — rows invalid after retry")
    return {
        "csv": None, "error": last_error,
        "usage": usage_total, "cost_usd": cost_usd(usage_total),
    }
