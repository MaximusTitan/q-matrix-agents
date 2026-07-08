"""
skills/report_render.py

Renders the human-readable `report.md` from a structured run record (see
`run_record.py`). Single source of the markdown for BOTH the chapter's `run/report.md`
and each `escalations/{...}/report.md`, so the two never drift.

The field labels here are kept byte-compatible with the legacy regex parsers in
`kb_access.py` (`_parse_report_header`, `_parse_report_attempts`) so that reports
rendered by this module remain readable by the existing escalation read-back path.
Do not rename `**Board:**`, `**Total Attempts:**`, `### Attempt N (input_type: ...)`,
`**Check 1 — Universal Rules:**`, `**Check 2 — CSM Coverage:**`, `Missing concepts:`,
or `Missing skills:` without updating those parsers.
"""


def _check_status(check: dict | None) -> str:
    return "✓ PASSED" if check and check.get("passed") else "✗ FAILED"


def _feedback_bullets(check: dict | None) -> str:
    items = (check or {}).get("feedback", []) or []
    return "\n".join(f"  - {f}" for f in items) or "  None"


def _attempt_section(attempt: dict) -> str:
    n = attempt.get("attempt")
    input_type = attempt.get("input_type") or "unknown"
    gen = attempt.get("generator")

    if gen is None:
        # Generation-stage failure: no CSV was produced this attempt.
        return (
            f"### Attempt {n} (input_type: {input_type})\n\n"
            f"**Prompt used:** see `attempt_{n}_prompt.md`\n\n"
            f"Generation failed before evaluation — no CSV produced.\n"
        )

    c1 = gen.get("check1", {})
    c2 = gen.get("check2", {})
    missing_concepts = ", ".join(c2.get("missing_concepts", [])) or "None"
    missing_skills = ", ".join(c2.get("missing_skills", [])) or "None"

    return (
        f"### Attempt {n} (input_type: {input_type})\n\n"
        f"**Prompt used:** see `attempt_{n}_prompt.md`\n\n"
        f"**Check 1 — Universal Rules:** {_check_status(c1)}\n"
        f"{_feedback_bullets(c1)}\n\n"
        f"**Check 2 — CSM Coverage:** {_check_status(c2)}\n"
        f"{_feedback_bullets(c2)}\n"
        f"Missing concepts: {missing_concepts}\n"
        f"Missing skills:   {missing_skills}\n"
    )


def _doctored_section(record: dict) -> str:
    lines = []
    for attempt in record.get("attempts", []):
        n = attempt.get("attempt")
        for d in attempt.get("doctors", []):
            kind = "rules (Check-1)" if d.get("kind") == "rules" else "coverage (Check-2)"
            status = "✓ passed re-verification" if d.get("passed") else "✗ failed re-verification"
            if d.get("regressed"):
                status += " ⚠ REGRESSED coverage"
            csv_file = d.get("csv_file")
            if csv_file:
                file_note = f"see `{csv_file}`"
            elif d.get("error"):
                file_note = f"{d['error']} — not written"
            else:
                file_note = "schema-invalid — not written"
            lines.append(f"- Attempt {n} [{kind}]: {status} ({file_note})")

    if not lines:
        return ""

    return (
        "## Doctored CSVs (surgical repairs)\n\n"
        "Surgical patches of a failing CSV produced by the Doctor / Rules Doctor. "
        "Each was re-verified through both checks; the status and patched CSV file are "
        "listed below for diagnostic review.\n\n"
        + "\n".join(lines)
        + "\n\n---\n\n"
    )


def _what_to_do(record: dict) -> str:
    board = record.get("board", "")
    subject = record.get("subject", "")
    grade = record.get("grade", "")
    chapter = record.get("chapter", "")
    return (
        "## What To Do\n\n"
        "Review the attempt history above, then choose an action:\n\n"
        "**Option A — Resume with human feedback:**\n"
        "```\n"
        f'python orchestrator.py --board "{board}" --subject "{subject}" '
        f'--grade "{grade}" --chapter "{chapter}" --human-feedback "your instructions here"\n'
        "```\n\n"
        "**Option B — Re-extract the concept-skill-map:**\n"
        "```\n"
        f'python orchestrator.py --board "{board}" --subject "{subject}" '
        f'--grade "{grade}" --chapter "{chapter}" --re-extract --map-guidance "your guidance here"\n'
        "```\n\n"
        "**Option C — Reject with a new grade rule:**\n"
        "```\n"
        f'python orchestrator.py --reject --board "{board}" --subject "{subject}" '
        f'--grade "{grade}" --chapter "{chapter}" --reason "your rule here"\n'
        "```\n\n"
        "## Human Feedback\n\n"
        "<!-- Add your notes here before re-running -->\n"
    )


def render_report_md(record: dict) -> str:
    """Render the human-readable report for a run record.

    Works for both passed and escalated runs; the resume-command footer is only
    emitted for escalations.
    """
    escalated = record.get("final_status") == "escalated"
    title = "Escalation Report" if escalated else "Run Report"
    failed_check = record.get("failed_check") or "none"

    attempts = record.get("attempts", [])
    history_text = "\n---\n\n".join(_attempt_section(a) for a in attempts)
    if history_text:
        history_text += "\n"

    final_csv_file = record.get("final_csv_file") or "last_csv.csv"

    report = (
        f"# {title}\n\n"
        f"**Board:** {record.get('board', '')}\n"
        f"**Subject:** {record.get('subject', '')}\n"
        f"**Grade:** {record.get('grade', '')}\n"
        f"**Chapter:** {record.get('chapter', '')}\n"
        f"**Date:** {record.get('date', '')}\n"
        f"**Failed Check:** {failed_check}\n"
        f"**Total Attempts:** {len(attempts)}\n\n"
        "---\n\n"
        "## Attempt History\n\n"
        f"{history_text}"
        "---\n\n"
        f"{_doctored_section(record)}"
        "## Final CSV\n\n"
        f"See `{final_csv_file}` in this folder.\n\n"
        "---\n\n"
    )

    if escalated:
        report += _what_to_do(record)

    return report
