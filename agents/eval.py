"""
agents/eval.py

Eval Agent.
Runs Check 1 and Check 2 in PARALLEL — both always run regardless of outcome.

Check 1 — Universal rules compliance (LLM-judged)
Check 2 — Concept-skill-map coverage (LLM-judged via diff.py)

Both checks are independent. Running them simultaneously means the Revision
Agent always receives full feedback from both checks in a single pass.

Input:  csv (str), board, subject, grade, chapter
Output: dict with check1 and check2 results — always both present

Skills used:
    kb_access  — load_rules, load_concept_skill_map
    llm        — call_llm (Check 1)
    diff       — diff_full (Check 2)
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from skills.kb_access import load_rules, load_concept_skill_map
from skills.llm import call_llm
from skills.diff import diff_full

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "eval_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def _parse_llm_json(raw: str, check_name: str) -> dict:
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
    Check 1 — Universal rules compliance.

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

    raw    = call_llm(SYSTEM_PROMPT, user_content)
    result = _parse_llm_json(raw, "Check 1")
    passed   = result.get("passed", False)
    feedback = result.get("feedback", [])

    print(f"[eval] Check 1: {'PASSED' if passed else 'FAILED'} ({len(feedback)} issue(s))")
    return {"passed": passed, "feedback": feedback}


def run_check2(csv: str, board: str, subject: str, grade: str, chapter: str) -> dict:
    """
    Check 2 — Concept-skill-map coverage.

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
    chapter: str,
) -> dict:
    """
    Run Check 1 and Check 2 in parallel.
    Both checks always run — neither is skipped based on the other's outcome.

    Returns:
        Dict with keys:
            check1 (dict) — always present
            check2 (dict) — always present
            passed (bool) — True only if both checks pass
    """
    print(f"[eval] Starting: {board}/{subject}/{grade}/{chapter}")
    print(f"[eval] Running Check 1 and Check 2 in parallel...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_c1 = executor.submit(run_check1, csv, board, subject, grade)
        future_c2 = executor.submit(run_check2, csv, board, subject, grade, chapter)

        check1 = future_c1.result()
        check2 = future_c2.result()

    passed = check1["passed"] and check2["passed"]
    print(f"[eval] Overall: {'✓ PASSED' if passed else '✗ FAILED'}")

    return {
        "check1": check1,
        "check2": check2,
        "passed": passed,
    }