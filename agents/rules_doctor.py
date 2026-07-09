"""
agents/rules_doctor.py

Rules Doctor Agent.
Surgically patches a curriculum CSV that PASSED Check 2 (concept-skill-map coverage)
but FAILED Check 1 (universal rules), instead of regenerating from scratch.

This is the mirror of agents/doctor.py: that agent fixes coverage gaps on a CSV that
already satisfies the rules; this one fixes rule violations on a CSV that already has
full coverage. It consumes the Check-1 violation list and, to avoid breaking coverage,
the expected concept-skill-map plus the Check-2 matched items. The judgement rules live
in prompts/rules_doctor_prompt.md:
    - rephrase vague / non-measurable skills and malformed/ungrounded concepts
    - merge or drop duplicates / malformed rows
    - NEVER drop a row that is the sole cover for an expected concept/skill — rephrase it

The orchestrator re-verifies the doctored CSV through BOTH checks afterwards.

Input:  failing_csv, check1, universal_rules, concept_skill_map, check2,
        board, subject, grade, chapter
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
    "prompts", "rules_doctor_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def _format_violations(check1: dict) -> str:
    """Render the Check-1 rule violations as a compact, LLM-readable block."""
    return json.dumps(
        {"violations": check1.get("feedback", [])},
        indent=2,
        ensure_ascii=False,
    )


def _format_matched(check2: dict) -> str:
    """Render the Check-2 matched items (the rows carrying coverage) for preservation."""
    return json.dumps(
        {
            "matched_concepts": check2.get("matched_concepts", {}),
            "matched_skills":   check2.get("matched_skills",   {}),
        },
        indent=2,
        ensure_ascii=False,
    )


def run(
    failing_csv: str,
    check1: dict,
    universal_rules: str,
    concept_skill_map: dict,
    check2: dict,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
) -> dict:
    """
    Surgically patch a CSV that passed Check 2 but failed Check 1 (universal rules).

    Unlike a full regeneration, this preserves correct rows and only fixes the rows the
    Check-1 violations flag (rephrase vague/non-verb-led skills, ground concepts, drop
    duplicates, fix malformed fields) while keeping the meaning of every row that carries
    coverage so Check 2 stays green. See prompts/rules_doctor_prompt.md for the rules.

    Args:
        failing_csv:       The CSV that failed Check 1 (already covers the CSM).
        check1:            The check1 dict from eval (has "feedback": [violations]).
        universal_rules:   Universal (+ grade) rules text — what the patch must satisfy.
        concept_skill_map: Expected concepts and skills for this chapter (may be None).
        check2:            The passing check2 dict (matched_concepts / matched_skills).
        board, subject, grade, chapter: The four fixed identifier columns (constants).

    Returns:
        On success: {"csv": corrected_csv, "rows": [parsed rows]}
        On failure (the LLM submitted invalid rows twice — e.g. an empty rows list or an
        empty concept/skill):
            {"csv": None, "error": <message>}
    """
    print(f"[rules_doctor] Doctoring CSV — {board}/{subject}/{grade}/{chapter}")

    csm = concept_skill_map or {}
    expected_concepts = csm.get("concepts", [])
    expected_skills   = csm.get("skills",   [])

    base_user_content = f"""board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- FAILING CSV ---
{failing_csv}

--- RULE VIOLATIONS TO FIX ---
{_format_violations(check1)}

--- UNIVERSAL RULES ---
{universal_rules}

--- EXPECTED CONCEPT-SKILL-MAP ---
concepts:
{json.dumps(expected_concepts, indent=2, ensure_ascii=False)}
skills:
{json.dumps(expected_skills, indent=2, ensure_ascii=False)}

--- MATCHED ITEMS (rows carrying coverage — preserve their meaning) ---
{_format_matched(check2)}"""

    correction = ""
    last_error = None
    usage_total = {}
    for attempt in range(2):
        print(f"[rules_doctor] Calling LLM (attempt {attempt + 1}/2)...")
        result, usage = call_llm_structured(
            SYSTEM_PROMPT, base_user_content + correction, CONCEPT_SKILL_ROWS_TOOL
        )
        usage_total = add_usage(usage_total, usage)
        rows = rows_from_pairs(board, subject, grade, chapter, result.get("rows", []))

        try:
            validate_rows(rows)
        except ValueError as e:
            last_error = str(e)
            print(f"[rules_doctor] Doctored rows invalid (attempt {attempt + 1}/2): {e}")
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

        print(f"[rules_doctor] Doctored CSV produced ({len(rows)} rows)")
        return {
            "csv": csv_to_text(rows), "rows": rows,
            "usage": usage_total, "cost_usd": cost_usd(usage_total),
        }

    print("[rules_doctor] Doctoring failed — rows invalid after retry")
    return {
        "csv": None, "error": last_error,
        "usage": usage_total, "cost_usd": cost_usd(usage_total),
    }
