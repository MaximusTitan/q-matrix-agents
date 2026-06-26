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
            if not row.get(col, "").strip():
                errors.append(f"Row {i}: '{col}' is empty.")

    if errors:
        raise ValueError(
            f"CSV has {len(errors)} empty required field(s):\n" +
            "\n".join(errors[:10]) +
            ("\n... (truncated)" if len(errors) > 10 else "")
        )

    return rows


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
