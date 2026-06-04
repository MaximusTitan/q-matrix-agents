"""
agents/map_extraction.py

Map Extraction Agent.
Extracts a concept-skill-map from a chapter PDF and saves it to the KB.

Input:  board, subject, grade, chapter (identifiers)
        guidance (optional) — human-provided extraction guidance string.
                              If not passed, agent checks KB for a saved
                              extraction_guidance.md for this chapter.
Output: concept-skill-map.json written to KB

Skills used:
    pdf_reader  — extract_text_from_pdf
    kb_access   — get_chapter_pdf_path, save_concept_skill_map,
                  load_extraction_guidance
    llm         — call_llm
"""

import json
import os

from skills.pdf_reader import extract_text_from_pdf
from skills.kb_access import (
    get_chapter_pdf_path,
    save_concept_skill_map,
    load_extraction_guidance,
)
from skills.llm import call_llm

# Load the base system prompt from file
_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "map_extraction_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    BASE_SYSTEM_PROMPT = f.read()


def run(
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    guidance: str = None,
) -> dict:
    """
    Extract a concept-skill-map from a chapter PDF and save it to the KB.

    Args:
        board:    Education board (e.g. "CBSE")
        subject:  Subject name (e.g. "Science")
        grade:    Grade level (e.g. "Grade 8")
        chapter:  Chapter folder name (e.g. "Chapter10_Sound")
        guidance: Optional human-provided guidance string to constrain
                  extraction. If None, checks KB for saved
                  extraction_guidance.md for this chapter.

    Returns:
        The extracted concept-skill-map as a Python dict.

    Raises:
        FileNotFoundError: If the chapter PDF does not exist.
        ValueError: If the LLM output cannot be parsed as valid JSON.
    """
    print(f"[map_extraction] Starting: {board}/{subject}/{grade}/{chapter}")

    # Step 1 — Resolve guidance
    # Priority: passed argument > saved KB guidance > none
    if guidance is None:
        guidance = load_extraction_guidance(board, subject, grade, chapter)

    if guidance:
        print(f"[map_extraction] Applying extraction guidance ({len(guidance)} chars)")
        system_prompt = (
            BASE_SYSTEM_PROMPT
            + "\n\n## Additional Guidance (Human-Provided)\n\n"
            + guidance.strip()
        )
    else:
        system_prompt = BASE_SYSTEM_PROMPT

    # Step 2 — Get PDF path and extract text
    pdf_path = get_chapter_pdf_path(board, subject, grade, chapter)
    print(f"[map_extraction] Extracting text from: {pdf_path}")
    chapter_text = extract_text_from_pdf(pdf_path)
    print(f"[map_extraction] Extracted {len(chapter_text)} characters")

    # Step 3 — Build user message
    user_content = f"""board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- CHAPTER TEXT START ---
{chapter_text}
--- CHAPTER TEXT END ---"""

    # Step 4 — Call LLM
    print(f"[map_extraction] Calling LLM...")
    raw_response = call_llm(system_prompt, user_content)

    # Step 5 — Parse JSON response
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()

    try:
        concept_skill_map = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"[map_extraction] LLM returned invalid JSON.\n"
            f"Error: {e}\n"
            f"Raw response:\n{raw_response[:500]}"
        )

    # Step 6 — Validate basic structure
    if "concepts" not in concept_skill_map or "skills" not in concept_skill_map:
        raise ValueError(
            f"[map_extraction] JSON missing 'concepts' or 'skills' key.\n"
            f"Got: {list(concept_skill_map.keys())}"
        )

    concept_count = len(concept_skill_map["concepts"])
    skill_count   = len(concept_skill_map["skills"])
    print(f"[map_extraction] Extracted {concept_count} concepts, {skill_count} skills")

    # Step 7 — Save to KB
    save_concept_skill_map(board, subject, grade, chapter, concept_skill_map)
    print(f"[map_extraction] Saved concept-skill-map to KB")

    return concept_skill_map