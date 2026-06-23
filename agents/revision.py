"""
agents/revision.py

Revision Agent.
Rewrites a generation prompt based on structured eval feedback.

Two modes:
    subject — revising toward a subject-level base_prompt.md
    grade   — revising toward a grade-specific prompt.md

failed_check can be "check1", "check2", or "both" since both checks
run in parallel and may fail simultaneously.

Input:  current_prompt, feedback, failed_check, mode, human_feedback (optional)
Output: revised_prompt (str)

Skills used:
    llm — call_llm
"""

import os
from skills.llm import call_llm

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "revision_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def run(
    current_prompt: str,
    feedback: list[str],
    failed_check: str,
    mode: str,
    human_feedback: str = None,
    model: str = None,
) -> str:
    """
    Rewrite a generation prompt based on eval feedback.

    Args:
        current_prompt: The prompt that was used and failed.
        feedback:       List of specific violations from the Eval Agent.
                        Items are prefixed with [Check 1] or [Check 2].
        failed_check:   "check1", "check2", or "both"
        mode:           "subject" or "grade"
        human_feedback: Optional additional guidance from a human reviewer.

    Returns:
        The revised prompt as a plain string.

    Raises:
        ValueError: If mode or failed_check are invalid.
    """
    if mode not in ("subject", "grade"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'subject' or 'grade'.")
    if failed_check not in ("check1", "check2", "both"):
        raise ValueError(f"Invalid failed_check: {failed_check}. Must be 'check1', 'check2', or 'both'.")

    print(f"[revision] Starting — mode: {mode}, failed_check: {failed_check}")

    feedback_text = "\n".join(f"- {f}" for f in feedback)

    human_section = ""
    if human_feedback:
        human_section = f"\n\n5. HUMAN FEEDBACK (highest priority):\n{human_feedback.strip()}"

    user_content = f"""1. mode: {mode}

2. failed_check: {failed_check}

3. current_prompt:
{current_prompt}

4. feedback:
{feedback_text}{human_section}"""

    revised, usage = call_llm(SYSTEM_PROMPT, user_content, model=model)
    print(f"[revision] Revised prompt generated ({len(revised)} chars)")
    return {"prompt": revised.strip(), "usage": usage}