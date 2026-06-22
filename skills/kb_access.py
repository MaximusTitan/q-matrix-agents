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


def load_prompt_at_level(board: str, subject: str, grade: str, level: str) -> tuple[str, str]:
    """
    Force-load a prompt at a SPECIFIC level, ignoring the normal resolution order.

    Unlike load_prompt (which resolves grade > base > cold by file existence), this
    loads exactly the level requested. Used by the orchestrator after a Check-2-only
    revision writes a prompt at a chosen degree: it must regenerate with that exact
    level, even if a more-specialized (e.g. stale grade) prompt file also exists.

    Args:
        board:   Education board
        subject: Subject name
        grade:   Grade level
        level:   One of "grade_prompt", "base_prompt", "cold_start"

    Returns:
        Tuple of (content: str, input_type: str) where input_type == level.

    Raises:
        ValueError: If level is not one of the three known levels.
        FileNotFoundError: If the file for the requested level does not exist.
    """
    if level == "grade_prompt":
        path = _grade_prompt_path(board, subject, grade)
    elif level == "base_prompt":
        path = _base_prompt_path(board, subject)
    elif level == "cold_start":
        path = _universal_rules_path()
    else:
        raise ValueError(
            f"Unknown level: {level}. Must be 'grade_prompt', 'base_prompt', or 'cold_start'."
        )

    if not file_exists(path):
        raise FileNotFoundError(f"No prompt found at level '{level}': {path}")
    return read_file(path), level


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
    attempt_history: list[dict],
    doctored_artifacts: list[dict] = None,
) -> str:
    """
    Write an escalation report folder to the KB escalations directory.

    Folder structure:
        escalations/{board}_{subject}_{grade}_{chapter}_{date}/
            report.md           ← human-readable summary with full feedback history
            attempt_1_prompt.md ← prompt used in attempt 1
            attempt_2_prompt.md ← prompt used in attempt 2
            attempt_3_prompt.md ← prompt used in attempt 3
            last_csv.csv        ← final generated CSV

    Args:
        attempt_history: List of dicts, one per attempt:
            {
                "attempt":    int,
                "input_type": str,
                "check1":     { "passed": bool, "feedback": list },
                "check2":     { "passed": bool, "feedback": list,
                                "missing_concepts": list, "missing_skills": list },
                "prompt":     str,
            }
        doctored_artifacts: Optional list of doctored-CSV records from the
            Check-2-only path, one per doctored attempt:
            {
                "attempt": int,
                "csv":     str,
                "passed":  bool,   # did the doctored CSV pass re-verification?
            }

    Returns:
        Path to the escalation folder.
    """
    safe_chapter = chapter.replace(" ", "_")
    safe_grade   = grade.replace(" ", "_")
    folder_name  = f"{board}_{subject}_{safe_grade}_{safe_chapter}_{date}"
    folder_path  = os.path.join(KB_ROOT, "escalations", folder_name)
    create_directory(folder_path)

    # ── Write individual prompt files ─────────────────────────────────────────
    for entry in attempt_history:
        n = entry["attempt"]
        prompt_path = os.path.join(folder_path, f"attempt_{n}_prompt.md")
        write_file(prompt_path, entry.get("prompt", ""))

    # ── Write last CSV ────────────────────────────────────────────────────────
    csv_path = os.path.join(folder_path, "last_csv.csv")
    write_file(csv_path, last_csv)

    # ── Write doctored CSVs (Check-2-only path) ───────────────────────────────
    for doc in (doctored_artifacts or []):
        n = doc.get("attempt")
        doc_csv = doc.get("csv") or ""
        if doc_csv:
            write_file(os.path.join(folder_path, f"doctored_attempt_{n}.csv"), doc_csv)

    # ── Build report.md ───────────────────────────────────────────────────────
    history_sections = []
    for entry in attempt_history:
        n          = entry["attempt"]
        input_type = entry.get("input_type", "unknown")
        c1         = entry.get("check1", {})
        c2         = entry.get("check2", {})

        c1_status = "✓ PASSED" if c1.get("passed") else "✗ FAILED"
        c2_status = "✓ PASSED" if c2.get("passed") else "✗ FAILED"

        c1_feedback = "\n".join(f"  - {f}" for f in c1.get("feedback", [])) or "  None"
        c2_feedback = "\n".join(f"  - {f}" for f in c2.get("feedback", [])) or "  None"

        missing_concepts = ", ".join(c2.get("missing_concepts", [])) or "None"
        missing_skills   = ", ".join(c2.get("missing_skills",   [])) or "None"

        history_sections.append(f"""### Attempt {n} (input_type: {input_type})

**Prompt used:** see `attempt_{n}_prompt.md`

**Check 1 — Universal Rules:** {c1_status}
{c1_feedback}

**Check 2 — CSM Coverage:** {c2_status}
{c2_feedback}
Missing concepts: {missing_concepts}
Missing skills:   {missing_skills}
""")

    history_text = "\n---\n\n".join(history_sections)

    # ── Doctored-CSV section (Check-2-only path) ──────────────────────────────
    doctored_section = ""
    if doctored_artifacts:
        lines = []
        for doc in doctored_artifacts:
            n      = doc.get("attempt")
            status = "✓ passed re-verification" if doc.get("passed") else "✗ failed re-verification"
            has_csv = bool(doc.get("csv"))
            file_note = f"see `doctored_attempt_{n}.csv`" if has_csv else "schema-invalid — not written"
            lines.append(f"- Attempt {n}: {status} ({file_note})")
        doctored_section = (
            "## Doctored CSVs (Check-2-only repairs)\n\n"
            "These are surgical patches of the failing CSV produced by the revision agent. "
            "None passed both checks (otherwise the pipeline would have returned one instead "
            "of escalating). They are kept for diagnostic review.\n\n"
            + "\n".join(lines)
            + "\n\n---\n\n"
        )

    report = f"""# Escalation Report

**Board:** {board}
**Subject:** {subject}
**Grade:** {grade}
**Chapter:** {chapter}
**Date:** {date}
**Failed Check:** {failed_check}
**Total Attempts:** {attempts}

---

## Attempt History

{history_text}
---

{doctored_section}## Final CSV

See `last_csv.csv` in this folder.

---

## What To Do

Review the attempt history above, then choose an action:

**Option A — Resume with human feedback:**
```
python orchestrator.py --board "{board}" --subject "{subject}" --grade "{grade}" --chapter "{chapter}" --human-feedback "your instructions here"
```

**Option B — Re-extract the concept-skill-map:**
```
python orchestrator.py --board "{board}" --subject "{subject}" --grade "{grade}" --chapter "{chapter}" --re-extract --map-guidance "your guidance here"
```

**Option C — Reject with a new grade rule:**
```
python orchestrator.py --reject --board "{board}" --subject "{subject}" --grade "{grade}" --chapter "{chapter}" --reason "your rule here"
```

## Human Feedback

<!-- Add your notes here before re-running -->
"""

    report_path = os.path.join(folder_path, "report.md")
    write_file(report_path, report)

    return folder_path


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