"""
agents/eval.py

Eval Agent.
Runs two sequential checks against a generated CSV.

Check 1 — Universal rules compliance (LLM-judged)
Check 2 — Concept-skill-map coverage (LLM-judged via diff.py)

Check 2 only runs if Check 1 passes.

Input:  csv (str), board, subject, grade, chapter
Output: dict with check1 and check2 results

Skills used:
    kb_access  — load_rules, load_concept_skill_map
    llm        — call_llm (Check 1)
    diff       — diff_full (Check 2)
    csv_utils  — parse_csv
"""

import json
import os

from skills.kb_access import load_rules, load_concept_skill_map
from skills.llm import call_llm
from skills.diff import diff_full

# Load the eval system prompt
_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "eval_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def _parse_llm_json(raw: str, check_name: str) -> dict:
    """Parse and clean JSON from LLM response."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"[eval] {check_name} — LLM returned invalid JSON.\n"
            f"Error: {e}\nRaw:\n{raw[:500]}"
        )


def run_check1(csv: str, board: str, subject: str, grade: str) -> dict:
    """
    Run Check 1 — universal rules compliance.

    Args:
        csv:     Raw CSV string from Generator Agent.
        board, subject, grade: Used to load the correct ruleset.

    Returns:
        Dict with keys: passed (bool), feedback (list)
    """
    print(f"[eval] Running Check 1 — universal rules")

    rules = load_rules(board, subject, grade)

    user_content = f"""CHECK: 1

--- RULES ---
{rules}

--- GENERATED CSV ---
{csv}"""

    raw = call_llm(SYSTEM_PROMPT, user_content)
    result = _parse_llm_json(raw, "Check 1")

    passed = result.get("passed", False)
    feedback = result.get("feedback", [])

    print(f"[eval] Check 1: {'PASSED' if passed else 'FAILED'} "
          f"({len(feedback)} issue(s))")

    return {"passed": passed, "feedback": feedback}


def run_check2(csv: str, board: str, subject: str, grade: str, chapter: str) -> dict:
    """
    Run Check 2 — concept-skill-map coverage.

    Args:
        csv:                Raw CSV string from Generator Agent.
        board, subject, grade, chapter: Used to load the concept-skill-map.

    Returns:
        Dict with keys: passed (bool), missing_concepts (list),
                        missing_skills (list), feedback (list)
    """
    print(f"[eval] Running Check 2 — CSM coverage")

    concept_skill_map = load_concept_skill_map(board, subject, grade, chapter)
    result = diff_full(csv, concept_skill_map)

    print(f"[eval] Check 2: {'PASSED' if result['passed'] else 'FAILED'} "
          f"({len(result['missing_concepts'])} missing concepts, "
          f"{len(result['missing_skills'])} missing skills)")

    return result


def run(
    csv: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str
) -> dict:
    """
    Run both checks sequentially.
    Check 2 only runs if Check 1 passes.

    Args:
        csv:     Raw CSV string from Generator Agent.
        board, subject, grade, chapter: Chapter identifiers.

    Returns:
        Dict with keys:
            check1 (dict) — always present
            check2 (dict) — present only if Check 1 passed
    """
    print(f"[eval] Starting: {board}/{subject}/{grade}/{chapter}")

    # Check 1
    check1 = run_check1(csv, board, subject, grade)

    if not check1["passed"]:
        print(f"[eval] Check 1 failed — skipping Check 2")
        return {"check1": check1}

    # Check 2 — only if Check 1 passed
    check2 = run_check2(csv, board, subject, grade, chapter)

    return {
        "check1": check1,
        "check2": check2,
    }
