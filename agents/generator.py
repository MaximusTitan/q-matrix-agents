"""
agents/generator.py

Generator Agent.
Produces a curriculum CSV from curriculum docs + prompt or rules.

Input:  board, subject, grade, chapter, input_type ("grade_prompt" | "base_prompt" | "cold_start")
Output: raw CSV string

Skills used:
    kb_access  — load_curriculum_docs, load_prompt
    llm        — call_llm
    csv_utils  — validate_csv_schema
"""

import os
from skills.kb_access import load_curriculum_docs, load_prompt, load_prompt_at_level
from skills.llm import call_llm
from skills.csv_utils import validate_csv_schema

# Load the generator system prompt
_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "generator_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def run(board: str, subject: str, grade: str, chapter: str, forced_level: str = None) -> dict:
    """
    Generate a curriculum CSV for a given chapter.

    Prompt resolution:
        - forced_level is None (default): kb_access.load_prompt resolves by file existence
            1. grade-specific prompt  → input_type: grade_prompt
            2. subject base prompt    → input_type: base_prompt
            3. cold start (rules)     → input_type: cold_start
        - forced_level set: load that EXACT level via load_prompt_at_level. Used by the
          orchestrator to honour the subject→grade specialization ladder regardless of which
          prompt files already exist on disk.

    Args:
        board:        Education board (e.g. "CBSE")
        subject:      Subject name (e.g. "Science")
        grade:        Grade level (e.g. "Grade8")
        chapter:      Chapter folder name (e.g. "Chapter10_Sound")
        forced_level: Optional — one of "grade_prompt", "base_prompt", "cold_start".
                      When set, bypasses normal resolution and loads exactly that level.

    Returns:
        Dict with keys:
            csv        (str)  — validated raw CSV string
            input_type (str)  — which prompt type was used
            rows       (list) — parsed CSV rows as list of dicts

    Raises:
        FileNotFoundError: If curriculum docs are not found.
        ValueError: If the generated CSV fails schema validation.
    """
    print(f"[generator] Starting: {board}/{subject}/{grade}/{chapter}")

    # Step 1 — Load curriculum docs
    print(f"[generator] Loading curriculum docs...")
    curriculum_docs = load_curriculum_docs(board, subject, grade)
    print(f"[generator] Loaded {len(curriculum_docs)} chars of curriculum content")

    # Step 2 — Load prompt (forced level, or best available)
    if forced_level is None:
        prompt_content, input_type = load_prompt(board, subject, grade)
    else:
        prompt_content, input_type = load_prompt_at_level(board, subject, grade, forced_level)
        print(f"[generator] Forced prompt level: {forced_level}")
    print(f"[generator] Using input_type: {input_type}")

    # Step 3 — Build user message
    # The system prompt contains generation instructions.
    # The prompt_content (whether a saved prompt or universal rules)
    # is injected as additional guidance in the user message.
    user_content = f"""board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- GENERATION GUIDANCE ---
{prompt_content}

--- CURRICULUM DOCUMENTATION ---
{curriculum_docs}"""

    # Step 4 — Call LLM
    print(f"[generator] Calling LLM...")
    raw_csv = call_llm(SYSTEM_PROMPT, user_content)

    # Step 5 — Strip any markdown fences the LLM might add
    cleaned = raw_csv.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()

    # Step 6 — Validate schema
    print(f"[generator] Validating CSV schema...")
    rows = validate_csv_schema(cleaned)
    print(f"[generator] Generated {len(rows)} concept-skill rows")

    return {
        "csv":        cleaned,
        "input_type": input_type,
        "rows":       rows,
    }
