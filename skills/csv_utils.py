"""
skills/csv_utils.py

Parse and validate curriculum CSVs produced by the Generator Agent.
The schema is fixed: board, subject, grade, chapter, concept, skill.
"""

import csv
import io
import json

REQUIRED_COLUMNS = {"board", "subject", "grade", "chapter", "concept", "skill"}
BASE_COLUMNS = ["board", "subject", "grade", "chapter", "concept", "skill"]

# Shared tool schema for agents that produce concept-skill rows via a forced tool call
# instead of hand-authoring raw CSV text. Keeping the model to {concept, skill} pairs —
# with the four identifier columns injected in code via rows_from_pairs — means it never
# has to escape a delimiter itself, which is what caused the recurring "more fields than
# headers" CSV validation failures.
CONCEPT_SKILL_ROWS_TOOL = {
    "name": "submit_concept_skill_rows",
    "description": (
        "Submit the final list of concept-skill rows for this chapter's curriculum CSV. "
        "Do not include board/subject/grade/chapter — those are fixed identifier columns "
        "applied automatically after you submit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {
                            "type": "string",
                            "minLength": 1,
                            "description": "The concept name.",
                        },
                        "skill": {
                            "type": "string",
                            "minLength": 1,
                            "description": "One observable, verb-led skill tied to this concept.",
                        },
                    },
                    "required": ["concept", "skill"],
                },
            },
        },
        "required": ["rows"],
    },
}

# Shared tool schema for Check 1 (universal-rules compliance). Forcing a tool call
# instead of hand-formatted JSON means a stray quote/apostrophe inside a feedback
# string can never break parsing — the recurring failure mode when Check 1 used
# free-text JSON.
RULES_CHECK_TOOL = {
    "name": "submit_rules_check",
    "description": "Submit the universal-rules compliance verdict for this CSV.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {
                "type": "boolean",
                "description": "True only if the CSV has zero rule violations.",
            },
            "feedback": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One entry per violation found. Empty if passed is true.",
            },
        },
        "required": ["passed", "feedback"],
    },
}


def parse_csv(raw_text: str) -> list[dict]:
    """
    Parse a CSV string into a list of row dicts.

    Args:
        raw_text: Raw CSV string from the Generator Agent.

    Returns:
        List of dicts, one per row, keyed by column name.

    Raises:
        ValueError: If the CSV is empty or cannot be parsed.
    """
    raw_text = raw_text.strip()

    # Strip markdown code fences if the LLM wrapped it
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    if not raw_text:
        raise ValueError("CSV content is empty.")

    reader = csv.DictReader(io.StringIO(raw_text))
    rows = list(reader)

    if not rows:
        raise ValueError("CSV parsed but contains no data rows.")

    return rows


def validate_csv_schema(raw_text: str) -> list[dict]:
    """
    Parse the CSV and verify it has all required columns and no empty
    required fields.

    Args:
        raw_text: Raw CSV string from the Generator Agent.

    Returns:
        Parsed rows as a list of dicts (same as parse_csv) if valid.

    Raises:
        ValueError: With a descriptive message if validation fails.
    """
    rows = parse_csv(raw_text)

    # csv.DictReader collects any fields beyond the header count under a None key
    # (usually an unescaped comma inside a concept/skill). Detect those malformed
    # rows and raise a ValueError — otherwise the None key crashes the sorted()
    # column checks below with "'<' not supported between instances of 'NoneType'
    # and 'str'", a TypeError that escapes callers' ValueError-only retry loops.
    malformed = [i for i, row in enumerate(rows, start=2) if None in row]
    if malformed:
        raise ValueError(
            f"CSV has {len(malformed)} row(s) with more fields than headers "
            f"(row(s) {', '.join(map(str, malformed[:10]))}"
            f"{', ...' if len(malformed) > 10 else ''}); "
            "a field containing a comma must be wrapped in double quotes."
        )

    # Check columns
    actual_columns = set(rows[0].keys())
    missing_columns = REQUIRED_COLUMNS - actual_columns
    if missing_columns:
        raise ValueError(
            f"CSV is missing required columns: {', '.join(sorted(missing_columns))}. "
            f"Found: {', '.join(sorted(actual_columns))}"
        )

    # Check for empty required fields
    errors = []
    for i, row in enumerate(rows, start=2):  # start=2 because row 1 is headers
        for col in REQUIRED_COLUMNS:
            # A row with fewer fields than headers gets None-valued cells (DictReader
            # restval), so guard against .strip() on None as well as missing keys.
            if not (row.get(col) or "").strip():
                errors.append(f"Row {i}: '{col}' is empty.")

    if errors:
        raise ValueError(
            f"CSV has {len(errors)} empty required field(s):\n" +
            "\n".join(errors[:10]) +
            ("\n... (truncated)" if len(errors) > 10 else "")
        )

    return rows


def rows_from_pairs(board: str, subject: str, grade: str, chapter: str, pairs: list[dict]) -> list[dict]:
    """
    Build full 6-column row dicts from LLM-produced {concept, skill} pairs plus the
    fixed identifier constants. Used with CONCEPT_SKILL_ROWS_TOOL: the LLM only ever
    produces concept/skill text, never the identifier columns, so it can't corrupt them.

    Args:
        board, subject, grade, chapter: The four fixed identifier columns.
        pairs: List of dicts with "concept" and "skill" keys (a tool call's "rows" input).

    Returns:
        List of row dicts with all 6 base columns. Does not validate — call validate_rows
        on the result before trusting it.
    """
    return [
        {
            "board": board, "subject": subject, "grade": grade, "chapter": chapter,
            "concept": (p.get("concept") or "").strip(),
            "skill":   (p.get("skill")   or "").strip(),
        }
        for p in pairs
    ]


def validate_rows(rows: list[dict]) -> None:
    """
    Validate rows already in the standard schema shape (e.g. from rows_from_pairs),
    as opposed to parsed CSV text. Only checks what a forced tool call can still get
    wrong — an empty rows list, or an empty concept/skill despite the schema's
    minLength hint (not mechanically enforced without strict tool use).

    Raises:
        ValueError: With a descriptive message if validation fails.
    """
    if not rows:
        raise ValueError("No concept-skill rows were produced.")

    errors = []
    for i, row in enumerate(rows, start=2):  # start=2 to mirror validate_csv_schema (row 1 = header)
        for col in ("concept", "skill"):
            if not row[col]:
                errors.append(f"Row {i}: '{col}' is empty.")

    if errors:
        raise ValueError(
            f"CSV has {len(errors)} empty required field(s):\n" +
            "\n".join(errors[:10]) +
            ("\n... (truncated)" if len(errors) > 10 else "")
        )


def csv_to_text(rows: list[dict]) -> str:
    """
    Convert a list of row dicts back to a CSV string.
    Useful when passing parsed rows back through the pipeline.

    Args:
        rows: List of dicts with the standard schema columns.

    Returns:
        CSV string with headers.
    """
    if not rows:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=BASE_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def enriched_csv_to_text(rows: list[dict], extra_columns: list[str]) -> str:
    """
    Convert rows to a CSV string with the 6 base columns plus extra columns
    (e.g. prerequisite columns added by the prerequisite agent).

    List- or dict-valued cells are JSON-encoded so they round-trip cleanly back
    through parse_csv + json.loads. The csv module handles quoting the JSON string.
    Future prerequisite levels (L2-L4) pass their own column names via extra_columns.

    Args:
        rows:          List of row dicts. Each may carry the base columns plus any
                       of extra_columns. Missing extra cells default to "[]".
        extra_columns: Ordered list of extra column names to append after the base 6.

    Returns:
        CSV string with headers.
    """
    if not rows:
        return ""

    fieldnames = BASE_COLUMNS + list(extra_columns)

    serialized = []
    for row in rows:
        out = {col: row.get(col, "") for col in BASE_COLUMNS}
        for col in extra_columns:
            value = row.get(col)
            if isinstance(value, (list, dict)):
                out[col] = json.dumps(value, ensure_ascii=False)
            elif value is None:
                out[col] = "[]"
            else:
                # Already a string (e.g. pre-serialized JSON) — pass through.
                out[col] = value
        serialized.append(out)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(serialized)
    return output.getvalue()
