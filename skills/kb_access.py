"""
skills/kb_access.py

All knowledge base read/write operations.
Every path resolves relative to KB_ROOT from the environment.
This is the only file in the codebase that knows the KB folder structure.
"""

import os
import json
from dotenv import load_dotenv
from skills.file_io import (
    read_file, write_file, append_file,
    file_exists, create_directory
)

load_dotenv()
KB_ROOT = os.getenv("KB_ROOT")

if not KB_ROOT:
    raise EnvironmentError("KB_ROOT is not set. Add it to your .env file.")


# ─── Path Builders ────────────────────────────────────────────────────────────

def _curriculum_docs_path(board: str, subject: str, grade: str) -> str:
    return os.path.join(KB_ROOT, "curriculum-docs", board, subject, grade)

def _textbook_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(KB_ROOT, "textbooks", board, subject, grade, chapter)

def _csm_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(_textbook_path(board, subject, grade, chapter), "concept-skill-map.json")

def _chapter_pdf_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(_textbook_path(board, subject, grade, chapter), "chapter.pdf")

def _grade_prompt_path(board: str, subject: str, grade: str) -> str:
    return os.path.join(KB_ROOT, "prompt-library", board, subject, grade, "prompt.md")

def _base_prompt_path(board: str, subject: str) -> str:
    return os.path.join(KB_ROOT, "prompt-library", board, subject, "base_prompt.md")

def _universal_rules_path() -> str:
    return os.path.join(KB_ROOT, "rulesets", "universal_rules.md")

def _grade_rules_path(board: str, subject: str, grade: str) -> str:
    return os.path.join(KB_ROOT, "rulesets", board, subject, grade, "rules.md")

def _escalation_path(board: str, subject: str, grade: str, chapter: str, date: str) -> str:
    filename = f"{board}_{subject}_{grade}_{chapter}_{date}.md"
    return os.path.join(KB_ROOT, "escalations", filename)


# ─── Curriculum Docs ─────────────────────────────────────────────────────────

def load_curriculum_docs(board: str, subject: str, grade: str) -> str:
    """
    Load all curriculum documentation text for a given board/subject/grade.
    Reads all .md and extracted .txt files in the curriculum-docs folder.
    PDFs in this folder are read via pdf_reader — not directly here.

    Args:
        board:   Education board (e.g. "CBSE")
        subject: Subject name (e.g. "Science")
        grade:   Grade level (e.g. "Grade8")

    Returns:
        Combined text content of all curriculum docs for this combination.

    Raises:
        FileNotFoundError: If no curriculum docs exist for this combination.
    """
    path = _curriculum_docs_path(board, subject, grade)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"No curriculum docs found at: {path}")

    combined = []
    for fname in os.listdir(path):
        fpath = os.path.join(path, fname)
        if fname.endswith(".md") or fname.endswith(".txt"):
            combined.append(read_file(fpath))
        elif fname.endswith(".pdf"):
            # Import here to avoid circular dependency
            from skills.pdf_reader import extract_text_from_pdf
            combined.append(extract_text_from_pdf(fpath))

    if not combined:
        raise FileNotFoundError(f"Curriculum docs folder exists but is empty: {path}")

    return "\n\n---\n\n".join(combined)


# ─── Chapter PDF ─────────────────────────────────────────────────────────────

def get_chapter_pdf_path(board: str, subject: str, grade: str, chapter: str) -> str:
    """
    Return the path to a chapter PDF. Does not read the file.

    Args:
        board, subject, grade, chapter: identifiers

    Returns:
        Absolute path string.

    Raises:
        FileNotFoundError: If the PDF does not exist.
    """
    path = _chapter_pdf_path(board, subject, grade, chapter)
    if not file_exists(path):
        raise FileNotFoundError(f"Chapter PDF not found: {path}")
    return path


# ─── Concept-Skill Map ───────────────────────────────────────────────────────

def concept_skill_map_exists(board: str, subject: str, grade: str, chapter: str) -> bool:
    """
    Check whether a concept-skill-map.json exists for a chapter.

    Returns:
        True if it exists, False otherwise.
    """
    return file_exists(_csm_path(board, subject, grade, chapter))


def load_concept_skill_map(board: str, subject: str, grade: str, chapter: str) -> dict:
    """
    Load the concept-skill-map JSON for a chapter.

    Returns:
        Parsed JSON as a Python dict.

    Raises:
        FileNotFoundError: If the map does not exist.
        ValueError: If the JSON is malformed.
    """
    path = _csm_path(board, subject, grade, chapter)
    if not file_exists(path):
        raise FileNotFoundError(f"concept-skill-map not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed concept-skill-map at {path}: {e}")


def save_concept_skill_map(board: str, subject: str, grade: str, chapter: str, data: dict) -> None:
    """
    Write a concept-skill-map dict to the KB as JSON.

    Args:
        board, subject, grade, chapter: identifiers
        data: The concept-skill-map dict to write.

    Raises:
        OSError: If the file cannot be written.
    """
    path = _csm_path(board, subject, grade, chapter)
    create_directory(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Prompt Library ──────────────────────────────────────────────────────────

def load_prompt(board: str, subject: str, grade: str) -> tuple[str, str]:
    """
    Load the best available prompt for a board/subject/grade combination.
    Resolution order:
      1. grade-specific prompt  → prompt-library/{board}/{subject}/{grade}/prompt.md
      2. subject base prompt    → prompt-library/{board}/{subject}/base_prompt.md
      3. cold start             → rulesets/universal_rules.md

    Returns:
        Tuple of (content: str, input_type: str)
        input_type is one of: "grade_prompt", "base_prompt", "cold_start"
    """
    grade_path = _grade_prompt_path(board, subject, grade)
    if file_exists(grade_path):
        return read_file(grade_path), "grade_prompt"

    base_path = _base_prompt_path(board, subject)
    if file_exists(base_path):
        return read_file(base_path), "base_prompt"

    rules_path = _universal_rules_path()
    if not file_exists(rules_path):
        raise FileNotFoundError(f"universal_rules.md not found at: {rules_path}")
    return read_file(rules_path), "cold_start"


def save_prompt(board: str, subject: str, content: str, mode: str, grade: str = None) -> None:
    """
    Save a prompt to the appropriate location in the prompt library.

    Args:
        board:   Education board
        subject: Subject name
        content: Prompt content to write
        mode:    One of "base_prompt" or "grade_prompt"
        grade:   Required when mode is "grade_prompt"

    Raises:
        ValueError: If mode is "grade_prompt" but grade is not provided.
    """
    if mode == "grade_prompt":
        if not grade:
            raise ValueError("grade is required when mode is 'grade_prompt'")
        path = _grade_prompt_path(board, subject, grade)
    elif mode == "base_prompt":
        path = _base_prompt_path(board, subject)
    else:
        raise ValueError(f"Unknown save mode: {mode}. Must be 'base_prompt' or 'grade_prompt'.")

    write_file(path, content)


# ─── Rulesets ────────────────────────────────────────────────────────────────

def load_rules(board: str, subject: str, grade: str) -> str:
    """
    Load rules for a board/subject/grade. Falls back to universal_rules if
    no grade-specific rules exist.

    Returns:
        Rules content as a string.
    """
    grade_rules = _grade_rules_path(board, subject, grade)
    universal_rules = _universal_rules_path()

    if file_exists(grade_rules):
        grade_content = read_file(grade_rules)
        universal_content = read_file(universal_rules)
        # Grade rules extend universal rules — both apply
        return f"{universal_content}\n\n## Grade-Specific Rules\n\n{grade_content}"

    if not file_exists(universal_rules):
        raise FileNotFoundError(f"universal_rules.md not found at: {universal_rules}")

    return read_file(universal_rules)


def append_grade_rule(board: str, subject: str, grade: str, reason: str) -> None:
    """
    Append a human rejection reason as a new rule in the grade-level ruleset.
    Creates the file if it doesn't exist.

    Args:
        board, subject, grade: identifiers
        reason: The rejection reason to encode as a rule.
    """
    path = _grade_rules_path(board, subject, grade)
    rule_entry = f"\n- {reason.strip()}\n"
    append_file(path, rule_entry)


# ─── Escalations ─────────────────────────────────────────────────────────────

def write_escalation(
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    date: str,
    failed_check: str,
    attempts: int,
    last_csv: str,
    last_feedback: dict,
    last_prompt: str,
) -> str:
    """
    Write an escalation report to the KB escalations folder.

    Returns:
        The path where the escalation file was written.
    """
    path = _escalation_path(board, subject, grade, chapter, date)

    missing_concepts = last_feedback.get("missing_concepts", [])
    missing_skills   = last_feedback.get("missing_skills", [])
    feedback_text    = last_feedback.get("feedback", [])

    content = f"""# Escalation Report

**Board:** {board}
**Subject:** {subject}
**Grade:** {grade}
**Chapter:** {chapter}
**Date:** {date}
**Failed Check:** {failed_check}
**Attempts:** {attempts}

---

## Last Generated CSV

```
{last_csv}
```

---

## Feedback From Last Eval

{chr(10).join(f"- {f}" for f in feedback_text)}

**Missing Concepts:** {", ".join(missing_concepts) if missing_concepts else "None"}
**Missing Skills:** {", ".join(missing_skills) if missing_skills else "None"}

---

## Last Prompt Used

```
{last_prompt}
```

---

## What To Do

1. Review the CSV and feedback above
2. Re-run with your guidance:

```
python orchestrator.py --board {board} --subject {subject} --grade {grade} --chapter {chapter} --human-feedback "your instructions here"
```

## Human Feedback

<!-- Add your instructions here -->
"""

    write_file(path, content)
    return path

# ─── Extraction Guidance ─────────────────────────────────────────────────────
 
def _extraction_guidance_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(
        _textbook_path(board, subject, grade, chapter),
        "extraction_guidance.md"
    )
 
 
def load_extraction_guidance(board: str, subject: str, grade: str, chapter: str) -> str | None:
    """
    Load human-provided extraction guidance for a specific chapter, if it exists.
    Used by the Map Extraction Agent when re-extracting after human review.
 
    Returns:
        Guidance string if found, None otherwise.
    """
    path = _extraction_guidance_path(board, subject, grade, chapter)
    if file_exists(path):
        return read_file(path)
    return None
 
 
def save_extraction_guidance(
    board: str, subject: str, grade: str, chapter: str, guidance: str
) -> None:
    """
    Save human-provided extraction guidance for a specific chapter.
    Written by the orchestrator when --re-extract flag is used.
 
    Args:
        board, subject, grade, chapter: identifiers
        guidance: Human instruction string to constrain map extraction.
    """
    path = _extraction_guidance_path(board, subject, grade, chapter)
    write_file(path, guidance)
 