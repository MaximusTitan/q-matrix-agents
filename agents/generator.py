"""
agents/generator.py

Generator Agent.
Produces a curriculum CSV from curriculum docs + prompt or rules.

Input:  board, subject, grade, chapter, input_type ("grade_prompt" | "base_prompt" | "cold_start")
Output: raw CSV string

The model produces concept-skill rows via a forced tool call rather than hand-authoring
raw CSV text — it never has to escape a delimiter itself, which is what caused the
recurring "more fields than headers" validation failures when it forgot to quote a
comma inside a concept/skill value.

Skills used:
    kb_access  — load_curriculum_docs, load_prompt
    llm        — call_llm_structured
    csv_utils  — CONCEPT_SKILL_ROWS_TOOL, rows_from_pairs, validate_rows, csv_to_text
"""

import json
import os
from skills.kb_access import load_curriculum_docs, load_prompt, load_prompt_at_level
from skills.llm import call_llm_structured, add_usage, DEFAULT_MODEL
from skills.csv_utils import CONCEPT_SKILL_ROWS_TOOL, rows_from_pairs, validate_rows, csv_to_text

# Load the generator system prompt
_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "generator_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

# The model occasionally submits rows with an empty concept/skill despite the tool
# schema's minLength hint. A corrective re-prompt almost always fixes it, so generation
# is retried up to this many times before giving up and raising.
_MAX_GEN_ATTEMPTS = 3


class GenerationFailedError(ValueError):
    """
    Raised when the generator exhausts all attempts without producing a valid CSV.

    Carries the last invalid CSV text (if any) so the orchestrator can persist it to
    the escalation folder — the summary message alone doesn't show what the model
    actually produced, which otherwise makes malformed-CSV failures unreproducible
    after the fact.
    """

    def __init__(self, message: str, last_csv: str = ""):
        super().__init__(message)
        self.last_csv = last_csv


def run(
    board: str, subject: str, grade: str, chapter: str,
    forced_level: str = None, model: str = DEFAULT_MODEL,
) -> dict:
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

    # Steps 4–6 — Call the LLM via a forced tool call, build the full rows, validate.
    # Retry with a corrective re-prompt if the model submits an empty rows list or an
    # empty concept/skill, so a single bad submission doesn't fail the whole run.
    correction = ""
    last_error: ValueError | None = None
    last_rows: list[dict] = []
    usage_total = {}
    cost_total = 0.0
    for gen_attempt in range(1, _MAX_GEN_ATTEMPTS + 1):
        print(f"[generator] Calling LLM (attempt {gen_attempt}/{_MAX_GEN_ATTEMPTS})...")
        result, usage, cost = call_llm_structured(
            SYSTEM_PROMPT, user_content + correction, CONCEPT_SKILL_ROWS_TOOL, model=model
        )
        usage_total = add_usage(usage_total, usage)
        cost_total += cost
        rows = rows_from_pairs(board, subject, grade, chapter, result.get("rows", []))

        print(f"[generator] Validating rows...")
        try:
            validate_rows(rows)
        except ValueError as e:
            last_error = e
            last_rows = rows
            print(f"[generator] Invalid rows on attempt {gen_attempt}/{_MAX_GEN_ATTEMPTS}: {e}")
            # Echo the rejected rows back so the model can see and fix the exact
            # offending one, instead of resubmitting the whole set blind.
            correction = (
                "\n\n--- IMPORTANT ---\n"
                f"Your previous submission was rejected: {e}\n\n"
                "--- YOUR PREVIOUS ROWS ---\n"
                f"{json.dumps(result.get('rows', []), indent=2, ensure_ascii=False)}\n"
                "--- END PREVIOUS ROWS ---\n\n"
                "Call the tool again with the corrected, COMPLETE list of rows."
            )
            continue

        print(f"[generator] Generated {len(rows)} concept-skill rows")
        return {
            "csv":        csv_to_text(rows),
            "input_type": input_type,
            "rows":       rows,
            "usage":      usage_total,
            "cost_usd":   cost_total,
        }

    # Exhausted retries — surface the last invalid rows (serialized) alongside the error
    # so the orchestrator can persist them to the escalation folder for debugging.
    raise GenerationFailedError(
        f"Generator failed to produce valid rows after {_MAX_GEN_ATTEMPTS} attempts. "
        f"Last error: {last_error}",
        last_csv=csv_to_text(last_rows),
    )
