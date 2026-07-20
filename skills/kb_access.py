"""
skills/kb_access.py

All knowledge base read/write operations.
Every path resolves relative to KB_ROOT from the environment.
This is the only file in the codebase that knows the KB folder structure.
"""

import os
import re
import json
from dotenv import load_dotenv
from skills.file_io import (
    read_file, write_file, append_file,
    file_exists, create_directory, remove_dir
)
from skills.csv_utils import parse_csv
from skills.report_render import render_report_md

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

def _confirmed_csv_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(_textbook_path(board, subject, grade, chapter), "confirmed_curriculum.csv")

def _chapter_pdf_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(_textbook_path(board, subject, grade, chapter), "chapter.pdf")

def _run_dir_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(_textbook_path(board, subject, grade, chapter), "run")

def _run_record_path(board: str, subject: str, grade: str, chapter: str) -> str:
    return os.path.join(_run_dir_path(board, subject, grade, chapter), "run.json")

def _grade_prompt_path(board: str, subject: str, grade: str) -> str:
    return os.path.join(KB_ROOT, "prompt-library", board, subject, grade, "prompt.md")

def _base_prompt_path(board: str, subject: str) -> str:
    return os.path.join(KB_ROOT, "prompt-library", board, subject, "base_prompt.md")

def _universal_rules_path() -> str:
    return os.path.join(KB_ROOT, "rulesets", "universal_rules.md")

def _grade_rules_path(board: str, subject: str, grade: str) -> str:
    return os.path.join(KB_ROOT, "rulesets", board, subject, grade, "rules.md")

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


# ─── Confirmed Curriculum CSV ────────────────────────────────────────────────

def confirmed_csv_exists(board: str, subject: str, grade: str, chapter: str) -> bool:
    """
    Check whether a confirmed_curriculum.csv exists for a chapter.

    Returns:
        True if it exists, False otherwise.
    """
    return file_exists(_confirmed_csv_path(board, subject, grade, chapter))


def load_confirmed_csv(board: str, subject: str, grade: str, chapter: str) -> str:
    """
    Load the confirmed (prerequisite-enriched) curriculum CSV text for a chapter.

    Returns:
        The CSV text.

    Raises:
        FileNotFoundError: If the confirmed CSV does not exist.
    """
    path = _confirmed_csv_path(board, subject, grade, chapter)
    if not file_exists(path):
        raise FileNotFoundError(f"confirmed_curriculum.csv not found: {path}")
    return read_file(path)


def save_confirmed_csv(board: str, subject: str, grade: str, chapter: str, csv_text: str) -> str:
    """
    Write the confirmed (prerequisite-enriched) curriculum CSV to the KB.
    This is the persisted checkpoint for a chapter once its CSV is confirmed.
    Overwrites any existing file — the latest confirmation wins.

    Args:
        board, subject, grade, chapter: identifiers
        csv_text: The enriched CSV string to write.

    Returns:
        The path the CSV was written to.

    Raises:
        OSError: If the file cannot be written.
    """
    path = _confirmed_csv_path(board, subject, grade, chapter)
    create_directory(os.path.dirname(path))
    write_file(path, csv_text)
    return path


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


# ─── Run Records ─────────────────────────────────────────────────────────────

# Sibling files inside a chapter's run/ folder are named from a fixed, safe
# alphabet. This regex is the whitelist that guards load_run_artifact against a
# user-controlled filename (path traversal, absolute paths, hidden files).
_RUN_FILE_RE = re.compile(r"^[A-Za-z0-9_]+\.(csv|md|json)$")


def save_run_record(
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    record: dict,
    artifacts: dict[str, str],
    report_md: str,
) -> str:
    """
    Persist the structured run record for a chapter, overwriting any previous run.

    Layout (latest run only — the folder is cleared first so a shorter re-run never
    leaves orphaned siblings from a longer previous run):
        textbooks/{board}/{subject}/{grade}/{chapter}/run/
            run.json                          ← structured source of truth (pointers)
            gen_attempt_{n}.csv               ← generator output per attempt
            doctored_attempt_{n}.csv          ← coverage-doctor output
            doctored_rules_attempt_{n}.csv    ← rules-doctor output
            attempt_{n}_prompt.md             ← generation-guidance snapshot
            confirmed.csv | last_csv.csv      ← final CSV
            report.md                         ← derived human-readable summary

    Args:
        record:    Fully-assembled run.json dict (with *_file pointers only).
        artifacts: Map of sibling filename -> file content (CSV text / prompt md).
        report_md: Pre-rendered report.md (from report_render.render_report_md).

    Returns:
        Path to the run/ folder.
    """
    run_dir = _run_dir_path(board, subject, grade, chapter)
    remove_dir(run_dir)
    create_directory(run_dir)

    # json.dump with a stable key order + indent keeps re-run diffs readable.
    record_json = json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False)
    write_file(os.path.join(run_dir, "run.json"), record_json)

    for filename, content in artifacts.items():
        write_file(os.path.join(run_dir, filename), content or "")

    write_file(os.path.join(run_dir, "report.md"), report_md)

    return run_dir


def run_record_exists(board: str, subject: str, grade: str, chapter: str) -> bool:
    """Whether a structured run/run.json exists for a chapter."""
    return file_exists(_run_record_path(board, subject, grade, chapter))


def load_run_record(board: str, subject: str, grade: str, chapter: str) -> dict | None:
    """
    Load the latest structured run record for a chapter.

    Returns:
        The parsed run.json dict, or None if the chapter has no run/ folder yet
        (legacy chapters predating run records).

    Raises:
        ValueError: if run.json exists but is malformed.
    """
    path = _run_record_path(board, subject, grade, chapter)
    if not file_exists(path):
        return None
    # Read raw (not read_file, which strips Obsidian YAML frontmatter) — JSON must
    # be parsed byte-for-byte.
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed run.json at {path}: {e}") from e


def load_run_artifact(board: str, subject: str, grade: str, chapter: str,
                      filename: str) -> str:
    """
    Read one sibling artifact (a CSV / prompt / report) from a chapter's run/ folder.

    SECURITY: ``filename`` is user-controlled (it flows in from an API query param).
    It MUST match the strict whitelist ``_RUN_FILE_RE`` — a bare name from run.json's
    ``*_file`` pointers, with no path separators, no ``..`` and no leading dot — BEFORE
    it is ever joined onto a filesystem path.

    Returns:
        The artifact's text content.

    Raises:
        ValueError:        if filename fails whitelist validation.
        FileNotFoundError: if the artifact does not exist in the run/ folder.
    """
    if not _RUN_FILE_RE.match(filename):
        raise ValueError(f"Invalid run artifact filename: {filename!r}")

    path = os.path.join(_run_dir_path(board, subject, grade, chapter), filename)
    if not file_exists(path):
        raise FileNotFoundError(f"Run artifact not found: {filename}")
    return read_file(path)


# ─── Escalations ─────────────────────────────────────────────────────────────

def write_escalation(
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    date: str,
    record: dict,
    artifacts: dict[str, str],
) -> str:
    """
    Write a dated escalation snapshot folder to the KB escalations directory.

    Unlike the chapter's run/ folder (latest only), escalation folders accumulate by
    date so a chapter's failure history is preserved. The folder is a self-contained
    snapshot of the run that escalated.

    Folder structure (mirrors textbooks/{board}/{subject}/{grade}/{chapter}/):
        escalations/{board}/{subject}/{grade}/{chapter}/{date}/
            report.md                         ← derived human-readable summary
            run.json                          ← structured record (same as run/run.json)
            attempt_{n}_prompt.md, *.csv      ← every artifact of the run

    Args:
        record:    The assembled run.json dict for the escalated run.
        artifacts: Map of sibling filename -> content (from RunRecordBuilder.build()).

    Returns:
        Path to the escalation folder.
    """
    folder_path = os.path.join(KB_ROOT, "escalations", board, subject, grade, chapter, date)
    create_directory(folder_path)

    write_file(os.path.join(folder_path, "report.md"), render_report_md(record))
    write_file(
        os.path.join(folder_path, "run.json"),
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False),
    )
    for filename, content in artifacts.items():
        write_file(os.path.join(folder_path, filename), content or "")

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


# ─── Analytics / Enumeration ─────────────────────────────────────────────────
#
# Read-only helpers that walk the KB filesystem to report what has been run
# through the pipeline. There is no manifest in the KB — status is inferred from
# file presence:
#   - confirmed_curriculum.csv present  → chapter succeeded (confirmed CSV)
#   - an escalations/{...}/report.md    → chapter failed all cycles (escalated)
#   - concept-skill-map.json only       → reached extraction, no final outcome
# These keep KB-structure knowledge centralized in this module (see api.py).

def _list_child_dirs(path: str) -> list[str]:
    """Return sorted child directory names of `path`, or [] if it isn't a dir."""
    try:
        return sorted(
            name for name in os.listdir(path)
            if os.path.isdir(os.path.join(path, name))
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []


def list_textbook_chapters() -> list[dict]:
    """
    Enumerate every chapter directory under
    KB_ROOT/textbooks/{board}/{subject}/{grade}/{chapter}.

    Returns:
        One dict per chapter directory:
            {
                "board", "subject", "grade", "chapter": str,
                "has_csm":       bool,  # concept-skill-map.json present
                "has_confirmed": bool,  # confirmed_curriculum.csv present
            }
    """
    root = os.path.join(KB_ROOT, "textbooks")
    records: list[dict] = []
    for board in _list_child_dirs(root):
        for subject in _list_child_dirs(os.path.join(root, board)):
            for grade in _list_child_dirs(os.path.join(root, board, subject)):
                grade_path = os.path.join(root, board, subject, grade)
                for chapter in _list_child_dirs(grade_path):
                    records.append({
                        "board": board,
                        "subject": subject,
                        "grade": grade,
                        "chapter": chapter,
                        "has_csm": concept_skill_map_exists(board, subject, grade, chapter),
                        "has_confirmed": confirmed_csv_exists(board, subject, grade, chapter),
                    })
    return records


def _report_field(text: str, name: str) -> str:
    """Extract a `**Name:** value` header field from a report.md, or ''."""
    m = re.search(rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _parse_report_header(text: str) -> dict:
    """
    Parse the header block of an escalation report.md into identifiers + outcome.
    The header carries the ORIGINAL (un-normalized) grade/chapter values, so these
    match the textbooks/ folder names directly — no ambiguous underscore splitting.
    """
    attempts_raw = _report_field(text, "Total Attempts")
    try:
        total_attempts = int(attempts_raw)
    except (TypeError, ValueError):
        total_attempts = None
    return {
        "board": _report_field(text, "Board"),
        "subject": _report_field(text, "Subject"),
        "grade": _report_field(text, "Grade"),
        "chapter": _report_field(text, "Chapter"),
        "date": _report_field(text, "Date"),
        "failed_check": _report_field(text, "Failed Check"),
        "total_attempts": total_attempts,
    }


def _parse_report_attempts(text: str) -> list[dict]:
    """
    Parse the "## Attempt History" section of a report.md into structured
    per-attempt records. Best-effort: the raw report is always available as a
    fallback (see load_escalation_report), so a parsing miss here is non-fatal.
    """
    # Isolate the attempt-history section (ends at the next top-level "## " header).
    hist_m = re.search(
        r"## Attempt History\s*(.*?)(?:\n## |\Z)", text, re.DOTALL
    )
    if not hist_m:
        return []
    history = hist_m.group(1)

    attempts: list[dict] = []
    # Each attempt block starts with "### Attempt N (input_type: ...)".
    blocks = re.split(r"^### Attempt\s+", history, flags=re.MULTILINE)
    for block in blocks[1:]:
        head = re.match(r"(\d+)\s*(?:\(input_type:\s*([^)]*)\))?", block)
        number = int(head.group(1)) if head else None
        input_type = (head.group(2).strip() if head and head.group(2) else "")

        def _status_passed(check_label: str) -> bool | None:
            m = re.search(rf"\*\*{re.escape(check_label)}:\*\*\s*(.+)", block)
            if not m:
                return None
            return "PASSED" in m.group(1)

        def _bullets_after(check_label: str) -> list[str]:
            # Feedback bullets are "  - ..." lines that follow the check status line
            # up to the next blank line or the next bold "**" marker.
            m = re.search(
                rf"\*\*{re.escape(check_label)}:\*\*[^\n]*\n(.*?)(?:\n\s*\n|\n\*\*|\Z)",
                block, re.DOTALL,
            )
            if not m:
                return []
            bullets = re.findall(r"^\s*-\s+(.*\S)\s*$", m.group(1), re.MULTILINE)
            return [b for b in bullets if b.strip().lower() != "none"]

        def _csv_list(field_name: str) -> list[str]:
            m = re.search(rf"{re.escape(field_name)}:\s*(.+)", block)
            if not m:
                return []
            raw = m.group(1).strip()
            if raw.lower() == "none" or not raw:
                return []
            return [p.strip() for p in raw.split(",") if p.strip()]

        attempts.append({
            "attempt": number,
            "input_type": input_type,
            "check1_passed": _status_passed("Check 1 — Universal Rules"),
            "check1_feedback": _bullets_after("Check 1 — Universal Rules"),
            "check2_passed": _status_passed("Check 2 — CSM Coverage"),
            "check2_feedback": _bullets_after("Check 2 — CSM Coverage"),
            "missing_concepts": _csv_list("Missing concepts"),
            "missing_skills": _csv_list("Missing skills"),
        })
    return attempts


def list_escalations() -> list[dict]:
    """
    Enumerate populated escalation folders under
    KB_ROOT/escalations/{board}/{subject}/{grade}/{chapter}/{date}/.

    Only leaf folders containing a report.md are returned (empty escalation
    folders, of which there are several in the KB, are ignored). Identifiers come
    from the parsed report header, which preserves the original grade/chapter
    spelling — the same values used for the directory names themselves.

    Returns:
        One dict per escalation:
            {
                "board", "subject", "grade", "chapter", "date": str,
                "failed_check": str,          # "check1" | "check2" | "both" | ""
                "total_attempts": int | None,
                "folder": str,                # path relative to escalations/, e.g.
                                               # "CBSE/Maths/Grade 7/Chapter2_.../2026-06-26"
            }
    """
    root = os.path.join(KB_ROOT, "escalations")
    escalations: list[dict] = []
    for board in _list_child_dirs(root):
        for subject in _list_child_dirs(os.path.join(root, board)):
            for grade in _list_child_dirs(os.path.join(root, board, subject)):
                grade_path = os.path.join(root, board, subject, grade)
                for chapter in _list_child_dirs(grade_path):
                    chapter_path = os.path.join(grade_path, chapter)
                    for date in _list_child_dirs(chapter_path):
                        folder = os.path.join(board, subject, grade, chapter, date)
                        report_path = os.path.join(root, folder, "report.md")
                        if not file_exists(report_path):
                            continue
                        header = _parse_report_header(read_file(report_path))
                        header["folder"] = folder
                        escalations.append(header)
    return escalations


def load_escalation_report(folder: str) -> dict:
    """
    Load and parse a single escalation folder's report.md plus its sibling files.

    Args:
        folder: The escalation folder's path relative to escalations/ (as returned
                by list_escalations), not an absolute path.

    Returns:
        {
            "folder":   str,
            "header":   dict,          # see _parse_report_header
            "attempts": list[dict],    # see _parse_report_attempts
            "files":    list[str],     # sibling filenames (prompts, CSVs)
            "raw_report": str,         # full report.md markdown (complete fallback)
        }

    Raises:
        FileNotFoundError: If the folder or its report.md does not exist.
    """
    folder_path = os.path.join(KB_ROOT, "escalations", folder)
    report_path = os.path.join(folder_path, "report.md")
    if not file_exists(report_path):
        raise FileNotFoundError(f"Escalation report not found: {report_path}")

    text = read_file(report_path)
    try:
        files = sorted(
            name for name in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, name)) and name != "report.md"
        )
    except (FileNotFoundError, PermissionError):
        files = []

    return {
        "folder": folder,
        "header": _parse_report_header(text),
        "attempts": _parse_report_attempts(text),
        "files": files,
        "raw_report": text,
    }


def list_all_run_records() -> list[dict]:
    """
    Every structured run record in the KB — both sources, deduped by run_id.

    Two on-disk sources hold run.json:
        textbooks/{board}/{subject}/{grade}/{chapter}/run/run.json
            latest run only (pass or fail) — overwritten every re-run.
        escalations/{board}/{subject}/{grade}/{chapter}/{date}/run.json
            one snapshot per historical failure, accumulated by date, never
            overwritten (write_escalation persists a full run.json here too,
            not just report.md).

    A chapter currently sitting in escalated state has its current failure
    present in BOTH sources with the same run_id — deduping on that key means
    every distinct run is counted exactly once regardless of how many places
    it happens to be persisted.
    """
    records: dict[str, dict] = {}

    for ch in list_textbook_chapters():
        rec = load_run_record(ch["board"], ch["subject"], ch["grade"], ch["chapter"])
        if rec:
            records[rec["run_id"]] = rec

    for esc in list_escalations():
        path = os.path.join(KB_ROOT, "escalations", esc["folder"], "run.json")
        if not file_exists(path):
            continue
        # Read raw (not read_file, which strips Obsidian YAML frontmatter) — JSON
        # must be parsed byte-for-byte, same as load_run_record.
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        records[rec["run_id"]] = rec

    return list(records.values())


def confirmed_csv_has_prereqs(board: str, subject: str, grade: str, chapter: str) -> bool:
    """
    Return True if a chapter's confirmed CSV has any non-empty Level-1 prerequisite
    cell. The prerequisite phase is defensive — it still writes the confirmed CSV
    with EMPTY L1 columns if mapping failed — so "confirmed CSV exists" is not the
    same as "prerequisites were actually mapped". This distinguishes the two.

    Returns:
        True if any prereq_*_L1_same_chapter cell holds a non-empty JSON array;
        False if the CSV is missing, unparseable, or all L1 cells are empty.
    """
    from agents.prerequisite import L1_COLUMNS

    if not confirmed_csv_exists(board, subject, grade, chapter):
        return False
    try:
        rows = parse_csv(load_confirmed_csv(board, subject, grade, chapter))
    except (ValueError, FileNotFoundError):
        return False

    for row in rows:
        for col in L1_COLUMNS:
            raw = (row.get(col) or "").strip()
            if not raw or raw == "[]":
                continue
            try:
                if json.loads(raw):  # non-empty list/dict
                    return True
            except (json.JSONDecodeError, TypeError):
                # Non-JSON but non-empty text still counts as "has prereqs".
                return True
    return False


def confirmed_csv_has_l2_prereqs(board: str, subject: str, grade: str, chapter: str) -> bool:
    """
    L2 analogue of confirmed_csv_has_prereqs — True if any Level-2 (cross-chapter)
    prerequisite cell on this chapter's confirmed CSV holds a non-empty JSON value.
    """
    from agents.prerequisite_l2 import L2_COLUMNS

    if not confirmed_csv_exists(board, subject, grade, chapter):
        return False
    try:
        rows = parse_csv(load_confirmed_csv(board, subject, grade, chapter))
    except (ValueError, FileNotFoundError):
        return False

    for row in rows:
        for col in L2_COLUMNS:
            raw = (row.get(col) or "").strip()
            if not raw or raw == "[]":
                continue
            try:
                if json.loads(raw):
                    return True
            except (json.JSONDecodeError, TypeError):
                return True
    return False


def list_chapters_in_grade_subject(board: str, subject: str, grade: str) -> list[dict]:
    """
    Chapters under textbooks/{board}/{subject}/{grade}/, filtered from
    list_textbook_chapters() rather than re-walking the filesystem, with two
    added flags for L2 eligibility:
        has_l1_prereqs  — confirmed_csv_has_prereqs(...)
        has_l2_prereqs  — confirmed_csv_has_l2_prereqs(...)

    Returns:
        One dict per chapter: {"board", "subject", "grade", "chapter",
        "has_csm", "has_confirmed", "has_l1_prereqs", "has_l2_prereqs"}.
    """
    chapters = [
        c for c in list_textbook_chapters()
        if c["board"] == board and c["subject"] == subject and c["grade"] == grade
    ]
    for c in chapters:
        c["has_l1_prereqs"] = confirmed_csv_has_prereqs(board, subject, grade, c["chapter"])
        c["has_l2_prereqs"] = confirmed_csv_has_l2_prereqs(board, subject, grade, c["chapter"])
    return chapters


def grade_subject_l1_complete(board: str, subject: str, grade: str) -> bool:
    """
    True iff every chapter in this board/subject/grade has L1 prerequisites
    mapped. False (not an error) if the grade+subject has zero chapters, so an
    empty group is never mistaken for "complete".
    """
    chapters = list_chapters_in_grade_subject(board, subject, grade)
    if not chapters:
        return False
    return all(c["has_l1_prereqs"] for c in chapters)


def load_confirmed_csvs_for_grade_subject(
    board: str, subject: str, grade: str, *, exclude_chapter: str | None = None
) -> dict[str, list[dict]]:
    """
    Batch-load every chapter's confirmed CSV in one board/subject/grade, keyed
    by chapter name. A chapter whose CSV is missing or unparseable is skipped
    (not raised) so one bad sibling doesn't block L2 mapping for the rest.

    Args:
        exclude_chapter: Chapter name to omit (typically the L2 target chapter
                          itself, since it's loaded separately by the caller).
    """
    result: dict[str, list[dict]] = {}
    for c in list_chapters_in_grade_subject(board, subject, grade):
        chapter = c["chapter"]
        if chapter == exclude_chapter:
            continue
        try:
            result[chapter] = parse_csv(load_confirmed_csv(board, subject, grade, chapter))
        except (ValueError, FileNotFoundError):
            continue
    return result