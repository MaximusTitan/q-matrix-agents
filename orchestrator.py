#!/usr/bin/env python3
"""
orchestrator.py

Q-Matrix Curriculum CSV Pipeline Orchestrator.
Thin coordinator — pure control flow, no LLM calls.

Can be used from CLI or called programmatically from api.py with an emit callback.

CLI Usage:
  python orchestrator.py --board CBSE --subject "Science" --grade "Grade 8" --chapter "Chapter10_Sound"
  python orchestrator.py ... --human-feedback "Add pressure as a concept"
  python orchestrator.py --reject ... --reason "Max 3 skills per concept"
  python orchestrator.py --re-extract ... --map-guidance "Only NCERT LO-aligned concepts"
  python orchestrator.py ... --no-sync
"""

import argparse
import re
import sys
from datetime import date
from concurrent.futures import ThreadPoolExecutor

from agents.map_extraction import run as run_map_extraction
from agents.generator      import run as run_generator
from agents.eval           import run as run_eval
from agents.revision       import run as run_revision
from agents.doctor         import run as run_doctor
from agents.rules_doctor   import run as run_rules_doctor
from agents.judge          import run as run_judge
from agents.prerequisite      import run as run_prerequisite, L1_COLUMNS
from agents.prerequisite_l2   import run as run_prerequisite_l2, L2_COLUMNS
from agents.chapter_relevance import screen as screen_chapter_relevance

from skills.kb_access import (
    concept_skill_map_exists,
    load_concept_skill_map,
    load_prompt,
    load_rules,
    append_grade_rule,
    write_escalation,
    save_extraction_guidance,
    save_confirmed_csv,
    save_run_record,
    confirmed_csv_has_prereqs,
    confirmed_csv_has_l2_prereqs,
    load_confirmed_csv,
    grade_subject_l1_complete,
    load_confirmed_csvs_for_grade_subject,
)
from skills.csv_utils import parse_csv, enriched_csv_to_text, validate_csv_schema
from skills.git_sync import pull_kb, push_kb
from skills.run_record import RunRecordBuilder
from skills.report_render import render_report_md
from skills.llm import DEFAULT_MODEL, add_usage

# Safety ceiling on generate→eval cycles. The loop also stops EARLY (before this cap)
# once the generator stops closing gaps — see the adaptive-budget check in run_pipeline.
MAX_ATTEMPTS = 6
MAX_PLATEAU_ROUNDS = 2  # consecutive non-improving attempts before escalating early

# Keys accepted in the `models` dict threaded through run_pipeline(...) — one per
# agent, each defaulting to AGENT_DEFAULT_MODELS[key] when not supplied.
AGENT_KEYS = (
    "map_extraction", "generator", "eval", "doctor",
    "rules_doctor", "revision", "judge", "prerequisite", "prerequisite_l2",
)

# Per-agent defaults, used when the caller's `models` dict omits a key. Map Extraction,
# Generator, and Eval default to Sonnet 5 — Sonnet produces noticeably fuller curriculum
# CSVs (100+ rows) than gpt-5.4-mini (which undershoots at <50 rows), and the eval gate
# needs a strong model to judge content rules reliably — every other agent defaults to
# gpt-5.4-mini.
AGENT_DEFAULT_MODELS = {
    "map_extraction": "anthropic/claude-sonnet-5",
    "generator":       "anthropic/claude-sonnet-5",
    "eval":            "anthropic/claude-sonnet-5",
    "doctor":          "openai/gpt-5.4-mini",
    "rules_doctor":    "openai/gpt-5.4-mini",
    "revision":        "openai/gpt-5.4-mini",
    "judge":           "openai/gpt-5.4-mini",
    "prerequisite":    "openai/gpt-5.4-mini",
    "prerequisite_l2": "openai/gpt-5.4-mini",
}


def _model_for(models: dict | None, key: str) -> str:
    return (models or {}).get(key) or AGENT_DEFAULT_MODELS.get(key, DEFAULT_MODEL)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _noop(*args, **kwargs):
    pass


def _persist_run_record(board, subject, grade, chapter, record, artifacts, report_md):
    """Persist the structured run record, defensively — a persistence failure must
    never break an otherwise-complete run (mirrors _run_prerequisite_phase)."""
    try:
        path = save_run_record(board, subject, grade, chapter, record, artifacts, report_md)
        print(f"[orchestrator] Saved run record: {path}")
    except Exception as e:
        print(f"[orchestrator] Warning: failed to persist run record — {e}")


def _revision_mode(input_type: str, c1_passed: bool, c2_passed: bool) -> str:
    if not c1_passed:
        return "subject" if input_type in ("cold_start", "base_prompt") else "grade"
    return "grade"


def _run_prerequisite_phase(board, subject, grade, chapter, attempt, csv_text, emit, model=DEFAULT_MODEL):
    """
    Run Level-1 (within-chapter) prerequisite mapping on a confirmed CSV, persist the
    enriched CSV checkpoint, and emit Prerequisites agent events.

    A failure here must NOT escalate an already-confirmed run: on any error we persist the
    base CSV with empty prerequisite columns and continue.

    Returns:
        (final_csv: str, checkpoint_path: str | None, usage: dict, cost_usd: float)
    """
    emit("agent_started", {
        "agent":   "Prerequisites",
        "attempt": attempt,
        "input":   {"level": "L1 (within-chapter)"},
    })

    try:
        rows = parse_csv(csv_text)
    except Exception as e:
        print(f"[orchestrator] Prerequisite phase skipped — CSV parse failed: {e}")
        emit("agent_completed", {
            "agent":  "Prerequisites",
            "output": {"error": f"CSV parse failed: {e}", "checkpoint": None},
        })
        return csv_text, None, {}, 0.0

    usage = {}
    cost = 0.0
    try:
        result = run_prerequisite(rows, board, subject, grade, chapter, model=model)
        enriched_rows = result["rows"]
        warnings      = result.get("warnings", [])
        concept_edges = result.get("concept_edges", {})
        skill_edges   = result.get("skill_edges", {})
        usage         = result.get("usage") or {}
        cost          = result.get("cost_usd", 0.0)
    except Exception as e:
        # Defensive: the agent is built to self-recover, but never let it break a pass.
        print(f"[orchestrator] Prerequisite mapping failed — persisting empty columns: {e}")
        enriched_rows = [{**r, L1_COLUMNS[0]: [], L1_COLUMNS[1]: []} for r in rows]
        warnings      = [f"prerequisite agent error: {e}"]
        concept_edges = {}
        skill_edges   = {}

    final_csv = enriched_csv_to_text(enriched_rows, L1_COLUMNS)

    checkpoint = None
    try:
        checkpoint = save_confirmed_csv(board, subject, grade, chapter, final_csv)
        print(f"[orchestrator] Saved confirmed CSV checkpoint: {checkpoint}")
    except Exception as e:
        print(f"[orchestrator] Warning: failed to persist confirmed CSV — {e}")

    emit("agent_completed", {
        "agent": "Prerequisites",
        "output": {
            "concept_edge_count": sum(len(v) for v in concept_edges.values()),
            "skill_edge_count":   sum(len(v) for v in skill_edges.values()),
            "warnings":           warnings,
            "checkpoint":         checkpoint,
            "usage":              usage,
            "cost_usd":           cost,
            "model":              model,
        },
    })
    return final_csv, checkpoint, usage, cost


_CHAPTER_ORDER_RE = re.compile(r"^\D*0*(\d+)")


def _chapter_order(chapter: str) -> int | None:
    """
    Leading number in a chapter folder name (e.g. "Chapter05_Arithmetic_Progressions"
    -> 5), used as a curriculum-sequence signal for L2 mapping. None if the name
    doesn't start with a number after any non-digit prefix (an unconventional chapter
    name) — callers must treat that as "order unknown", not "order zero".
    """
    m = _CHAPTER_ORDER_RE.match(chapter)
    return int(m.group(1)) if m else None


_IDENTIFIER_COLUMNS = ("board", "subject", "grade", "chapter")


def _identifiers_from_rows(rows: list[dict]) -> tuple[str, str, str, str]:
    """
    Derive (board, subject, grade, chapter) from parsed curriculum rows.

    A curriculum CSV carries these four identifier columns on every row. For the
    "bring your own CSV" path we read them straight from the data instead of asking
    the user to re-select them. Every row must agree and none may be blank.

    Raises:
        ValueError: if any identifier column is blank or differs across rows.
    """
    if not rows:
        raise ValueError("CSV has no data rows to derive identifiers from.")

    values = {}
    for col in _IDENTIFIER_COLUMNS:
        seen = {(r.get(col) or "").strip() for r in rows}
        if "" in seen:
            raise ValueError(f"Column '{col}' is blank in at least one row.")
        if len(seen) > 1:
            raise ValueError(
                f"Column '{col}' is not consistent across all rows "
                f"(found {len(seen)} distinct values: {', '.join(sorted(seen))}). "
                "A single run must cover one board/subject/grade/chapter."
            )
        values[col] = seen.pop()

    return values["board"], values["subject"], values["grade"], values["chapter"]


def run_prerequisite_only(csv_text: str, emit=None, models: dict | None = None) -> dict:
    """
    "Bring your own curriculum CSV" entry point: skip Stage 1 (generation + checks)
    and run ONLY Stage 2 (Level-1 within-chapter prerequisite mapping) on a CSV the
    user pasted or uploaded.

    The CSV must use the same 6 base columns the Generator emits
    (board, subject, grade, chapter, concept, skill). The four identifier columns are
    derived from the rows — no separate selection needed. Streams the same events the
    full pipeline does so the dashboard renders identically.

    Returns:
        {"passed": True, "csv": enriched_csv, "checkpoint": path} on success,
        {"passed": False, "error": message} if the CSV is invalid.
    """
    if emit is None:
        emit = _noop

    try:
        rows = validate_csv_schema(csv_text)  # 6 base columns, no empty required fields
        board, subject, grade, chapter = _identifiers_from_rows(rows)
    except ValueError as e:
        print(f"[orchestrator] run_prerequisite_only — invalid CSV: {e}")
        emit("error", {"message": f"Invalid curriculum CSV: {e}"})
        return {"passed": False, "error": str(e)}

    _print_header(board, subject, grade, chapter, extra="Mode: prerequisite-only (Stage 1 skipped)")

    emit("pipeline_started", {
        "board": board, "subject": subject,
        "grade": grade, "chapter": chapter,
        "human_feedback": None,
    })
    emit("attempt_started", {"attempt": 1, "max_attempts": 1})

    final_csv, checkpoint, prereq_usage, prereq_cost = _run_prerequisite_phase(
        board, subject, grade, chapter, attempt=1, csv_text=csv_text, emit=emit,
        model=_model_for(models, "prerequisite"),
    )

    # ── Persist a minimal run record for the "bring your own CSV" path ──────────
    builder = RunRecordBuilder(
        board, subject, grade, chapter, date.today().isoformat(),
        mode="prerequisite_only",
    )
    builder.add_pipeline_usage(
        "prerequisite", prereq_usage, prereq_cost, model=_model_for(models, "prerequisite")
    )
    builder.finalize(
        final_status="passed", failed_check=None,
        final_csv=final_csv, final_csv_name="confirmed.csv",
        confirmed_checkpoint=bool(checkpoint),
        has_prereqs=confirmed_csv_has_prereqs(board, subject, grade, chapter),
    )
    record, artifacts = builder.build()
    _persist_run_record(board, subject, grade, chapter, record, artifacts,
                        render_report_md(record))

    emit("pipeline_passed", {
        "attempt":         1,
        "csv":             final_csv,
        "source":          "user_provided",
        "selected_by":     "single",
        "candidate_count": 1,
        "judge_rationale": None,
        "checkpoint":      checkpoint,
    })
    print(f"\n[orchestrator] ✓ Prerequisite-only run complete")
    return {"passed": True, "csv": final_csv, "checkpoint": checkpoint}


def _run_l2_prerequisite_phase(board, subject, grade, chapter, emit, model=DEFAULT_MODEL):
    """
    Run Level-2 (cross-chapter, same grade+subject) prerequisite mapping for one
    target chapter, persist the enriched CSV checkpoint, and emit PrerequisitesL2
    agent events.

    Re-checks grade_subject_l1_complete defensively — the API route already gates
    this before spawning the run, but KB state could change between that check and
    this one actually executing on a background thread.

    Returns:
        (final_csv: str, checkpoint_path: str | None, usage: dict, cost_usd: float)
    """
    emit("agent_started", {
        "agent":   "PrerequisitesL2",
        "attempt": 1,
        "input":   {"level": "L2 (cross-chapter, same grade+subject)"},
    })

    if not grade_subject_l1_complete(board, subject, grade):
        msg = (f"L2 mapping requires every chapter in {board}/{subject}/{grade} to have "
               "L1 prerequisites mapped first.")
        print(f"[orchestrator] {msg}")
        emit("agent_completed", {"agent": "PrerequisitesL2", "output": {"error": msg, "checkpoint": None}})
        return "", None, {}, 0.0

    try:
        target_rows = parse_csv(load_confirmed_csv(board, subject, grade, chapter))
    except (ValueError, FileNotFoundError) as e:
        print(f"[orchestrator] L2 prerequisite phase skipped — target CSV unreadable: {e}")
        emit("agent_completed", {
            "agent": "PrerequisitesL2",
            "output": {"error": f"target CSV unreadable: {e}", "checkpoint": None},
        })
        return "", None, {}, 0.0

    sibling_rows_by_chapter = load_confirmed_csvs_for_grade_subject(
        board, subject, grade, exclude_chapter=chapter
    )

    # ── Curriculum-order gate ────────────────────────────────────────────────
    # A chapter can only be a genuine prerequisite SOURCE if it comes earlier in
    # the book — later chapters can never be prerequisites of an earlier one in a
    # linear curriculum. Chapter folder names encode this order (Chapter01_...,
    # Chapter02_...), so this is enforced deterministically, before either LLM call,
    # rather than trusted to LLM judgment (which has no notion of book order at all
    # and will otherwise assert semantically-plausible but directionally-backwards
    # edges — e.g. treating a later "Polynomials" chapter as a prerequisite for an
    # earlier "Real Numbers" chapter). Chapters whose name doesn't follow the
    # numbering convention keep an unknown order and are never excluded by this gate.
    target_order = _chapter_order(chapter)
    order_excluded = []
    if target_order is not None:
        for ch in list(sibling_rows_by_chapter.keys()):
            ch_order = _chapter_order(ch)
            if ch_order is not None and ch_order > target_order:
                order_excluded.append(ch)
                del sibling_rows_by_chapter[ch]

    if order_excluded:
        print(f"[orchestrator] Excluded {len(order_excluded)} later chapter(s) by curriculum "
              f"order (not eligible as prerequisite sources for {chapter}): {order_excluded}")

    target_concepts = list({r.get("concept", "") for r in target_rows})
    target_skills   = list({r.get("skill", "")   for r in target_rows})
    sibling_items = {
        ch: {
            "concepts": list({r.get("concept", "") for r in rows}),
            "skills":   list({r.get("skill", "")   for r in rows}),
        }
        for ch, rows in sibling_rows_by_chapter.items()
    }

    usage = {}
    cost = 0.0
    order_warnings = [
        f"excluded by curriculum order (later chapter, not eligible as a prerequisite source): {ch}"
        for ch in order_excluded
    ]
    try:
        screen_result = screen_chapter_relevance(
            chapter, target_concepts, target_skills, sibling_items, model=model
        )
        relevant_chapters = set(screen_result.get("relevant_chapters", []))
        screen_warnings = order_warnings + screen_result.get("warnings", [])
        usage = add_usage(usage, screen_result.get("usage") or {})
        cost += screen_result.get("cost_usd", 0.0)
    except Exception as e:
        # Defensive: a screening failure must not balloon into a full O(chapters^2)
        # sweep — fall back to no candidate chapters at all (mirrors agents' own
        # fail-to-empty pattern), same as any other L2 failure below.
        print(f"[orchestrator] Chapter relevance screen failed — no candidate chapters: {e}")
        relevant_chapters = set()
        screen_warnings = order_warnings + [f"chapter_relevance screen error: {e}"]

    candidate_pool = {ch: sibling_items[ch] for ch in relevant_chapters if ch in sibling_items}

    try:
        result = run_prerequisite_l2(
            target_rows, candidate_pool, sibling_rows_by_chapter,
            board, subject, grade, chapter, model=model,
        )
        enriched_rows = result["rows"]
        warnings      = screen_warnings + result.get("warnings", [])
        concept_edges = result.get("concept_edges", {})
        skill_edges   = result.get("skill_edges", {})
        usage         = add_usage(usage, result.get("usage") or {})
        cost         += result.get("cost_usd", 0.0)
    except Exception as e:
        # Defensive: never let an L2 failure break an already-confirmed chapter.
        print(f"[orchestrator] L2 prerequisite mapping failed — persisting empty columns: {e}")
        enriched_rows = [{**r, L2_COLUMNS[0]: [], L2_COLUMNS[1]: []} for r in target_rows]
        warnings      = screen_warnings + [f"prerequisite_l2 agent error: {e}"]
        concept_edges = {}
        skill_edges   = {}

    # Preserve existing L1 columns already present on the target rows — only add L2.
    final_csv = enriched_csv_to_text(enriched_rows, L1_COLUMNS + L2_COLUMNS)

    checkpoint = None
    try:
        checkpoint = save_confirmed_csv(board, subject, grade, chapter, final_csv)
        print(f"[orchestrator] Saved confirmed CSV checkpoint (L2): {checkpoint}")
    except Exception as e:
        print(f"[orchestrator] Warning: failed to persist confirmed CSV — {e}")

    emit("agent_completed", {
        "agent": "PrerequisitesL2",
        "output": {
            "concept_edge_count": sum(len(v) for v in concept_edges.values()),
            "skill_edge_count":   sum(len(v) for v in skill_edges.values()),
            "sibling_chapter_count": len(sibling_items),
            "candidate_chapter_count": len(candidate_pool),
            "warnings":           warnings,
            "checkpoint":         checkpoint,
            "usage":              usage,
            "cost_usd":           cost,
            "model":              model,
        },
    })
    return final_csv, checkpoint, usage, cost


def run_l2_prerequisite_only(
    board: str, subject: str, grade: str, chapter: str,
    emit=None, models: dict | None = None,
) -> dict:
    """
    Run Level-2 (cross-chapter) prerequisite mapping for one target chapter.

    Requires the target chapter to already have a confirmed CSV with L1 mapped,
    AND every chapter in its grade+subject to have L1 mapped (grade_subject_l1_complete)
    — callers (the API route) should gate on this before invoking, but this function
    re-checks defensively.

    Returns:
        {"passed": True, "csv": enriched_csv, "checkpoint": path} on success,
        {"passed": False, "error": message} if ineligible.
    """
    if emit is None:
        emit = _noop

    if not grade_subject_l1_complete(board, subject, grade):
        msg = (f"Not every chapter in {board}/{subject}/{grade} has L1 prerequisites "
               "mapped yet — L2 mapping is not available.")
        emit("error", {"message": msg})
        return {"passed": False, "error": msg}

    _print_header(board, subject, grade, chapter, extra="Mode: L2 prerequisite-only (cross-chapter)")

    emit("pipeline_started", {
        "board": board, "subject": subject,
        "grade": grade, "chapter": chapter,
        "human_feedback": None,
    })
    emit("attempt_started", {"attempt": 1, "max_attempts": 1})

    final_csv, checkpoint, prereq_usage, prereq_cost = _run_l2_prerequisite_phase(
        board, subject, grade, chapter, emit=emit,
        model=_model_for(models, "prerequisite_l2"),
    )

    if not checkpoint:
        emit("error", {"message": "L2 prerequisite mapping did not complete — see agent output for details."})
        return {"passed": False, "error": "L2 prerequisite mapping did not complete."}

    builder = RunRecordBuilder(
        board, subject, grade, chapter, date.today().isoformat(),
        mode="l2_prerequisite_only",
    )
    builder.add_pipeline_usage(
        "prerequisite_l2", prereq_usage, prereq_cost, model=_model_for(models, "prerequisite_l2")
    )
    builder.finalize(
        final_status="passed", failed_check=None,
        final_csv=final_csv, final_csv_name="confirmed.csv",
        confirmed_checkpoint=bool(checkpoint),
        has_prereqs=confirmed_csv_has_l2_prereqs(board, subject, grade, chapter),
    )
    record, artifacts = builder.build()
    _persist_run_record(board, subject, grade, chapter, record, artifacts,
                        render_report_md(record))

    emit("pipeline_passed", {
        "attempt":         1,
        "csv":             final_csv,
        "source":          "user_provided",
        "selected_by":     "single",
        "candidate_count": 1,
        "judge_rationale": None,
        "checkpoint":      checkpoint,
    })
    print(f"\n[orchestrator] ✓ L2 prerequisite-only run complete")
    return {"passed": True, "csv": final_csv, "checkpoint": checkpoint}


def _failed_check_label(c1_passed: bool, c2_passed: bool) -> str:
    if not c1_passed and not c2_passed:
        return "both"
    return "check1" if not c1_passed else "check2"


def _collect_feedback(c1: dict, c2: dict) -> list[str]:
    feedback = []
    for f in c1.get("feedback", []):
        feedback.append(f"[Check 1] {f}")
    missing_concepts = c2.get("missing_concepts", [])
    missing_skills   = c2.get("missing_skills",   [])
    if missing_concepts:
        feedback.append(f"[Check 2] {len(missing_concepts)} concept(s) not covered in the CSV:")
        for c in missing_concepts:
            feedback.append(f"[Check 2]   - {c}")
    if missing_skills:
        feedback.append(f"[Check 2] {len(missing_skills)} skill(s) not covered in the CSV:")
        for s in missing_skills:
            feedback.append(f"[Check 2]   - {s}")
    return feedback


def _coverage_regressions(before: dict, after: dict) -> dict:
    """
    Detect coverage the Doctor *broke*: items that were matched in the pre-doctor
    Check 2 but are reported missing in the re-evaluated (post-doctor) Check 2.

    The Doctor regenerates the whole CSV to close a gap, so it can rewrite the
    `concept`/`skill` text that was carrying a prior match (especially a 1:N
    "umbrella" match where one actual item covered several expected items). When
    that text changes, the fresh Check-2 pass can no longer match those expected
    items and they flip matched → missing — a net-negative edit.

    Args:
        before: pre-doctor check2 dict (has matched_concepts/matched_skills).
        after:  post-doctor check2 dict (has missing_concepts/missing_skills).

    Returns:
        {"concepts": [...], "skills": [...]} — expected items newly lost.
    """
    matched_concepts_before = set((before.get("matched_concepts") or {}).keys())
    matched_skills_before   = set((before.get("matched_skills")   or {}).keys())
    missing_concepts_after  = set(after.get("missing_concepts") or [])
    missing_skills_after    = set(after.get("missing_skills")   or [])

    return {
        "concepts": sorted(matched_concepts_before & missing_concepts_after),
        "skills":   sorted(matched_skills_before   & missing_skills_after),
    }


def _candidate(source: str, cycle: int, csv: str, rows: list) -> dict:
    """Build a passing-CSV candidate record for the Judge agent."""
    concepts = {r.get("concept", "").strip() for r in (rows or []) if r.get("concept", "").strip()}
    skills   = {r.get("skill",   "").strip() for r in (rows or []) if r.get("skill",   "").strip()}
    return {
        "id":            f"cycle{cycle}-{source}",
        "source":        source,
        "cycle":         cycle,
        "csv":           csv,
        "concept_count": len(concepts),
        "skill_count":   len(skills),
    }


def _doctor_and_record(
    emit,
    *,
    csv: str,
    check2: dict,
    csm_data: dict,
    universal_rules: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    attempt: int,
    models: dict | None = None,
) -> dict:
    """
    Doctor a Check-2-only failing CSV and re-verify it through both checks.

    Used on the Check-2-only path: the generated CSV already passed Check 1, so rather
    than regenerate, we surgically patch it to close coverage gaps and re-evaluate.

    Returns:
        {"csv": str|None, "passed": bool} — csv is None if doctoring produced an
        invalid CSV or errored. Never raises.
    """
    gaps_addressed = {
        "missing_concepts": check2.get("missing_concepts", []),
        "missing_skills":   check2.get("missing_skills",   []),
        "extra_concepts":   check2.get("extra_concepts",   []),
        "extra_skills":     check2.get("extra_skills",     []),
        "violations":       [],
    }

    def _coverage_error(message: str, usage: dict = None, cost_usd: float = 0.0) -> dict:
        """Failure result carrying a coverage doctor_entry so the run record still
        captures that a doctor pass was attempted and why it produced no CSV.
        `usage`/`cost_usd` reflect whatever tokens the doctor call actually spent
        (zero when it raised before a response came back)."""
        return {
            "csv": None, "passed": False,
            "doctor_entries": [{
                "kind": "coverage", "chained_from": None,
                "gaps_addressed": gaps_addressed,
                "csv": None, "error": message,
                "reeval_check1": None, "reeval_check2": None,
                "passed": False, "regressed": False,
                "regressed_concepts": [], "regressed_skills": [],
                "usage": usage or {}, "cost_usd": cost_usd,
            }],
        }

    emit("agent_started", {
        "agent":   "Doctor",
        "attempt": attempt,
        "input": {
            "missing_concepts": check2.get("missing_concepts", []),
            "missing_skills":   check2.get("missing_skills",   []),
            "extra_concepts":   check2.get("extra_concepts",   []),
            "extra_skills":     check2.get("extra_skills",     []),
            "csv_preview":      csv,
        },
    })

    doctor_model = _model_for(models, "doctor")
    eval_model   = _model_for(models, "eval")
    try:
        doc = run_doctor(
            failing_csv=csv,
            check2=check2,
            concept_skill_map=csm_data,
            universal_rules=universal_rules,
            board=board, subject=subject, grade=grade, chapter=chapter,
            model=doctor_model,
        )
    except Exception as e:
        print(f"[orchestrator] CSV doctoring errored — {e}")
        emit("agent_completed", {"agent": "Doctor", "output": {"error": str(e), "model": doctor_model}})
        return _coverage_error(str(e))

    if doc.get("csv") is None:
        error = doc.get("error", "invalid CSV after retry")
        emit("agent_completed", {
            "agent":  "Doctor",
            "output": {
                "error": error, "usage": doc.get("usage"), "cost_usd": doc.get("cost_usd"),
                "model": doctor_model,
            },
        })
        return _coverage_error(error, doc.get("usage"), doc.get("cost_usd", 0.0))

    doctored_csv = doc["csv"]
    emit("agent_completed", {
        "agent":  "Doctor",
        "output": {
            "rows": len(doc["rows"]), "csv_preview": doctored_csv,
            "usage": doc.get("usage"), "cost_usd": doc.get("cost_usd"),
            "model": doctor_model,
        },
    })

    # ── Re-verify the doctored CSV through both checks ─────────────────────────
    # Mirror the primary Eval emit shape so the dashboard renders the full
    # Check 1 / Check 2 + coverage-diff for the doctored output.
    emit("agent_started", {
        "agent":   "Eval (doctored)",
        "attempt": attempt,
        "input": {
            "rows":              len(doc["rows"]),
            "csv_preview":       doctored_csv,
            "concept_skill_map": csm_data,
        },
    })
    doc_eval = run_eval(doctored_csv, board, subject, grade, chapter, model=eval_model)
    dc1, dc2 = doc_eval["check1"], doc_eval["check2"]

    # ── Regression guard ───────────────────────────────────────────────────────
    # Did the Doctor break coverage that the pre-doctor CSV already had? Compare the
    # re-evaluated Check 2 against the matches we came in with. Any matched → missing
    # flip is a net-negative edit (typically the Doctor rewrote text that was carrying
    # a 1:N umbrella match). We surface it so the doctored CSV isn't trusted downstream.
    regressions = _coverage_regressions(check2, dc2)
    regressed   = bool(regressions["concepts"] or regressions["skills"])
    if regressed:
        print(f"[orchestrator] ⚠ Doctor REGRESSED coverage — "
              f"{len(regressions['concepts'])} concept(s), {len(regressions['skills'])} skill(s) "
              f"were matched before doctoring but are now missing: "
              f"{', '.join(regressions['concepts'] + regressions['skills'])}")

    # ── Diagnose a doctored Check-2 failure ─────────────────────────────────────
    # If the patch still doesn't cover the map, classify why so the next run is
    # debuggable: items the Doctor was told to ADD but are STILL missing ("unfixed"
    # — the Doctor ignored/paraphrased them) vs items newly missing that weren't on
    # the original gap list ("newly-missing" — the Doctor introduced the gap).
    if not dc2["passed"]:
        before_missing = set(check2.get("missing_concepts", []) + check2.get("missing_skills", []))
        after_missing  = set(dc2.get("missing_concepts", [])    + dc2.get("missing_skills", []))
        unfixed        = sorted(after_missing & before_missing)
        newly_missing  = sorted(after_missing - before_missing)
        if unfixed:
            print(f"[orchestrator] Doctor still-UNFIXED ({len(unfixed)} item(s) it was "
                  f"told to add but didn't): {', '.join(unfixed)}")
        if newly_missing:
            print(f"[orchestrator] Doctor NEWLY-MISSING ({len(newly_missing)} item(s) not on "
                  f"the original gap list): {', '.join(newly_missing)}")

    emit("agent_completed", {
        "agent":  "Eval (doctored)",
        "output": {
            "check1": {
                "passed":   dc1["passed"],
                "feedback": dc1["feedback"],
                "usage":    dc1.get("usage"),
                "cost_usd": dc1.get("cost_usd"),
            },
            "check2": {
                "passed":             dc2["passed"],
                "feedback":           dc2.get("feedback",         []),
                "missing_concepts":   dc2.get("missing_concepts", []),
                "missing_skills":     dc2.get("missing_skills",   []),
                "matched_concepts":   dc2.get("matched_concepts", {}),
                "matched_skills":     dc2.get("matched_skills",   {}),
                "extra_concepts":     dc2.get("extra_concepts",   []),
                "extra_skills":       dc2.get("extra_skills",     []),
                "reconciliation":     dc2.get("reconciliation",   {"concepts": {}, "skills": {}}),
                "regressed":          regressed,
                "regressed_concepts": regressions["concepts"],
                "regressed_skills":   regressions["skills"],
                "usage":              dc2.get("usage"),
                "cost_usd":           dc2.get("cost_usd"),
            },
            "usage":    doc_eval.get("usage"),
            "cost_usd": doc_eval.get("cost_usd"),
            "model":    eval_model,
        },
    })
    print(f"[orchestrator] Doctored CSV re-verify — "
          f"check1 {'✓' if dc1['passed'] else '✗'}, check2 {'✓' if dc2['passed'] else '✗'}"
          f"{' (REGRESSED)' if regressed else ''}")

    coverage_entry = {
        "kind": "coverage", "chained_from": None,
        "gaps_addressed": gaps_addressed,
        "csv": doctored_csv, "error": None,
        "reeval_check1": dc1, "reeval_check2": dc2,
        "passed": doc_eval["passed"], "regressed": regressed,
        "regressed_concepts": regressions["concepts"],
        "regressed_skills":   regressions["skills"],
        "usage": doc.get("usage"), "cost_usd": doc.get("cost_usd", 0.0),
        "model": doctor_model,
    }

    # ── Doctor chain: coverage fixed but rules broke → Rules Doctor ─────────────
    # The coverage Doctor closed the Check-2 gap but introduced a Check-1 (rules)
    # violation — a CSV one rule-fix away from passing. Hand it to the Rules Doctor,
    # which fixes rules WHILE preserving coverage (its own regression guard protects
    # the coverage just gained). One bounded extra pass — no loop. Only chain when the
    # coverage gain is real (not regressed); a regressed CSV is not worth rescuing.
    chained_entries: list[dict] = []
    if dc2["passed"] and not dc1["passed"] and not regressed:
        print("[orchestrator] Coverage Doctor fixed Check 2 but broke Check 1 — "
              "chaining Rules Doctor to repair rules while preserving coverage")
        chained = _rules_doctor_and_record(
            emit,
            csv=doctored_csv, check1=dc1, check2=dc2, csm_data=csm_data,
            universal_rules=universal_rules,
            board=board, subject=subject, grade=grade, chapter=chapter,
            attempt=attempt, models=models,
        )
        # Mark every chained entry as descending from the coverage pass so the trail
        # reads as a chain, not two independent doctors.
        chained_entries = chained.get("doctor_entries", [])
        for e in chained_entries:
            e["chained_from"] = "coverage"
        if chained.get("csv") is not None:
            # The chained result (rules-repaired) supersedes the coverage-only output,
            # but the trail keeps BOTH the coverage pass and the chained rules pass.
            chained["doctor_entries"] = [coverage_entry, *chained_entries]
            return chained

    return {
        "csv":                doctored_csv,
        "passed":             doc_eval["passed"],
        "rows":               doc["rows"],
        "regressed":          regressed,
        "regressed_concepts": regressions["concepts"],
        "regressed_skills":   regressions["skills"],
        "doctor_entries":     [coverage_entry, *chained_entries],
    }


def _rules_doctor_and_record(
    emit,
    *,
    csv: str,
    check1: dict,
    check2: dict,
    csm_data: dict,
    universal_rules: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    attempt: int,
    models: dict | None = None,
) -> dict:
    """
    Doctor a Check-1-only failing CSV and re-verify it through both checks.

    Mirror of _doctor_and_record for the opposite case: the generated CSV already passed
    Check 2 (coverage), so rather than regenerate, we surgically fix the universal-rule
    violations and re-evaluate. The regression guard here protects the coverage the CSV
    came in with — a rule-fix must not break a matched concept/skill.

    Returns:
        {"csv": str|None, "passed": bool} — csv is None if doctoring produced an
        invalid CSV or errored. Never raises.
    """
    gaps_addressed = {
        "missing_concepts": [],
        "missing_skills":   [],
        "extra_concepts":   [],
        "extra_skills":     [],
        "violations":       check1.get("feedback", []),
    }

    def _rules_error(message: str, usage: dict = None, cost_usd: float = 0.0) -> dict:
        """Failure result carrying a rules doctor_entry so the run record still
        captures the attempted repair."""
        return {
            "csv": None, "passed": False,
            "doctor_entries": [{
                "kind": "rules", "chained_from": None,
                "gaps_addressed": gaps_addressed,
                "csv": None, "error": message,
                "reeval_check1": None, "reeval_check2": None,
                "passed": False, "regressed": False,
                "regressed_concepts": [], "regressed_skills": [],
                "usage": usage or {}, "cost_usd": cost_usd,
            }],
        }

    emit("agent_started", {
        "agent":   "Doctor (rules)",
        "attempt": attempt,
        "input": {
            "violations":  check1.get("feedback", []),
            "csv_preview": csv,
        },
    })

    rules_model = _model_for(models, "rules_doctor")
    eval_model  = _model_for(models, "eval")
    try:
        doc = run_rules_doctor(
            failing_csv=csv,
            check1=check1,
            universal_rules=universal_rules,
            concept_skill_map=csm_data,
            check2=check2,
            board=board, subject=subject, grade=grade, chapter=chapter,
            model=rules_model,
        )
    except Exception as e:
        print(f"[orchestrator] Rules doctoring errored — {e}")
        emit("agent_completed", {"agent": "Doctor (rules)", "output": {"error": str(e), "model": rules_model}})
        return _rules_error(str(e))

    if doc.get("csv") is None:
        error = doc.get("error", "invalid CSV after retry")
        emit("agent_completed", {
            "agent":  "Doctor (rules)",
            "output": {
                "error": error, "usage": doc.get("usage"), "cost_usd": doc.get("cost_usd"),
                "model": rules_model,
            },
        })
        return _rules_error(error, doc.get("usage"), doc.get("cost_usd", 0.0))

    doctored_csv = doc["csv"]
    emit("agent_completed", {
        "agent":  "Doctor (rules)",
        "output": {
            "rows": len(doc["rows"]), "csv_preview": doctored_csv,
            "usage": doc.get("usage"), "cost_usd": doc.get("cost_usd"),
            "model": rules_model,
        },
    })

    # ── Re-verify the doctored CSV through both checks ─────────────────────────
    # Reuse the "Eval (doctored)" agent name (already rendered by the dashboard); the
    # two doctors are mutually exclusive within an attempt so the name never collides.
    emit("agent_started", {
        "agent":   "Eval (doctored)",
        "attempt": attempt,
        "input": {
            "rows":              len(doc["rows"]),
            "csv_preview":       doctored_csv,
            "concept_skill_map": csm_data,
        },
    })
    doc_eval = run_eval(doctored_csv, board, subject, grade, chapter, model=eval_model)
    dc1, dc2 = doc_eval["check1"], doc_eval["check2"]

    # ── Regression guard ───────────────────────────────────────────────────────
    # The CSV came in passing Check 2. Did the rule-fix break any coverage it already
    # had? Compare the incoming Check 2 (matched) against the re-evaluated Check 2
    # (missing). Any matched → missing flip means the rephrase lost a cover.
    regressions = _coverage_regressions(check2, dc2)
    regressed   = bool(regressions["concepts"] or regressions["skills"])
    if regressed:
        print(f"[orchestrator] ⚠ Rules Doctor REGRESSED coverage — "
              f"{len(regressions['concepts'])} concept(s), {len(regressions['skills'])} skill(s) "
              f"were matched before doctoring but are now missing: "
              f"{', '.join(regressions['concepts'] + regressions['skills'])}")

    emit("agent_completed", {
        "agent":  "Eval (doctored)",
        "output": {
            "check1": {
                "passed":   dc1["passed"],
                "feedback": dc1["feedback"],
                "usage":    dc1.get("usage"),
                "cost_usd": dc1.get("cost_usd"),
            },
            "check2": {
                "passed":             dc2["passed"],
                "feedback":           dc2.get("feedback",         []),
                "missing_concepts":   dc2.get("missing_concepts", []),
                "missing_skills":     dc2.get("missing_skills",   []),
                "matched_concepts":   dc2.get("matched_concepts", {}),
                "matched_skills":     dc2.get("matched_skills",   {}),
                "extra_concepts":     dc2.get("extra_concepts",   []),
                "extra_skills":       dc2.get("extra_skills",     []),
                "reconciliation":     dc2.get("reconciliation",   {"concepts": {}, "skills": {}}),
                "regressed":          regressed,
                "regressed_concepts": regressions["concepts"],
                "regressed_skills":   regressions["skills"],
                "usage":              dc2.get("usage"),
                "cost_usd":           dc2.get("cost_usd"),
            },
            "usage":    doc_eval.get("usage"),
            "cost_usd": doc_eval.get("cost_usd"),
            "model":    eval_model,
        },
    })
    print(f"[orchestrator] Rules-doctored CSV re-verify — "
          f"check1 {'✓' if dc1['passed'] else '✗'}, check2 {'✓' if dc2['passed'] else '✗'}"
          f"{' (REGRESSED)' if regressed else ''}")

    rules_entry = {
        "kind": "rules", "chained_from": None,
        "gaps_addressed": gaps_addressed,
        "csv": doctored_csv, "error": None,
        "reeval_check1": dc1, "reeval_check2": dc2,
        "passed": doc_eval["passed"], "regressed": regressed,
        "regressed_concepts": regressions["concepts"],
        "regressed_skills":   regressions["skills"],
        "usage": doc.get("usage"), "cost_usd": doc.get("cost_usd", 0.0),
        "model": rules_model,
    }

    return {
        "csv":                doctored_csv,
        "passed":             doc_eval["passed"],
        "rows":               doc["rows"],
        "regressed":          regressed,
        "regressed_concepts": regressions["concepts"],
        "regressed_skills":   regressions["skills"],
        "doctor_entries":     [rules_entry],
    }


def _print_header(board, subject, grade, chapter, extra=None):
    print(f"\n{'='*60}")
    print(f"Q-Matrix Pipeline")
    print(f"Target: {board}/{subject}/{grade}/{chapter}")
    if extra:
        print(extra)
    print(f"{'='*60}\n")


# ─── Core pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    human_feedback: str = None,
    models: dict | None = None,
    emit=None,
) -> dict:
    """
    Run the full pipeline for one chapter.

    Args:
        models: Optional dict mapping agent key (see AGENT_KEYS) -> Gateway model id.
                Any key omitted (or a wholly omitted/None dict) falls back to
                DEFAULT_MODEL for that agent.
        emit: Optional callable(event_type: str, data: dict).
              Called at each key step so the API can stream events to the frontend.
              Defaults to no-op — CLI mode works without it.
    """
    if emit is None:
        emit = _noop

    _print_header(
        board, subject, grade, chapter,
        extra=f"Human feedback: {human_feedback[:80]}..." if human_feedback else None,
    )

    emit("pipeline_started", {
        "board": board, "subject": subject,
        "grade": grade, "chapter": chapter,
        "human_feedback": human_feedback,
    })

    map_exists            = concept_skill_map_exists(board, subject, grade, chapter)
    current_csv           = None
    current_input_type    = None
    eval_result           = None
    attempt               = 0

    # ── Structured run record ───────────────────────────────────────────────────
    # Accumulates every CSV + its eval checks + the doctor trail as the run proceeds,
    # and is persisted (latest-only) for BOTH passing and escalated runs.
    builder = RunRecordBuilder(board, subject, grade, chapter, date.today().isoformat())

    # ── Ephemeral revision state ────────────────────────────────────────────────
    # The revised prompt is threaded through the run IN MEMORY only — never written to
    # the shared prompt library — so one chapter's revisions can't contaminate its
    # siblings (or race a concurrent batch), and every chapter starts from the same clean
    # read-only seed. working_prompt seeds from the library on attempt 1 and becomes the
    # previous cycle's revised prompt thereafter.
    check2_only_revisions = 0     # drives subject(1st) → grade(2nd) specialization degree
    working_prompt        = None  # generation guidance for the current attempt (in-memory)
    working_input_type    = None  # logical level label for working_prompt
    prev_csv              = None  # previous attempt's CSV — fed back for edit-in-place regen
    prev_feedback         = None  # its eval violations, telling the generator what to fix
    prev_gap_count        = None  # total unresolved gaps last attempt — drives adaptive budget
    plateau_rounds        = 0     # consecutive attempts with no gap reduction
    passing_candidates    = []    # every CSV that passed BOTH checks (generated + doctored)

    def _escalate_generation_failure(err: Exception) -> dict:
        """Escalate (rather than crash) when generation can't yield a valid CSV.

        Records progress in the KB and emits a terminal escalation so the dashboard —
        and any queued batch — advances. Called from both generation call sites.
        """
        print(f"[orchestrator] Generation failed on attempt {attempt} — escalating: {err}")
        emit("agent_completed", {"agent": "Generator", "output": {"error": str(err)}})
        # GenerationFailedError carries the last invalid CSV text; current_csv is never
        # set on a generation-stage failure since generation didn't succeed this attempt.
        failed_csv = getattr(err, "last_csv", "") or current_csv or ""
        builder.finalize(
            final_status="escalated", failed_check="generation",
            final_csv=failed_csv, final_csv_name="last_csv.csv",
            confirmed_checkpoint=False, has_prereqs=False,
        )
        record, artifacts = builder.build()
        report_md = render_report_md(record)
        _persist_run_record(board, subject, grade, chapter, record, artifacts, report_md)
        folder = write_escalation(
            board=board, subject=subject, grade=grade, chapter=chapter,
            date=date.today().isoformat(),
            record=record, artifacts=artifacts,
        )
        emit("pipeline_escalated", {
            "attempt":       attempt,
            "failed_check":  "generation",
            "folder":        folder,
            "last_feedback": {"generation_error": str(err)},
        })
        return {"passed": False, "csv": current_csv, "attempts": attempt}

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        print(f"\n── Attempt {attempt}/{MAX_ATTEMPTS} ──────────────────────────────────────")

        # Attempt 1 seeds from the read-only prompt library; every later attempt reuses the
        # in-memory revised prompt from the previous cycle. Nothing is written to disk.
        if working_prompt is None:
            working_prompt, working_input_type = load_prompt(board, subject, grade)
        prompt_snapshot = working_prompt

        # ── Map Extraction (pre-cycle, runs once before attempt 1 if no map exists) ──
        gen_result = None
        if not map_exists and attempt == 1:
            print("[orchestrator] No map — running Map Extraction + Generator in parallel")
            # Emit before attempt_started so the card sits outside the cycle groups
            emit("agent_started", {
                "agent": "Map Extraction",
                "parallel": False,
                "attempt": attempt,
                "input": {"board": board, "subject": subject, "grade": grade, "chapter": chapter},
            })

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_map = executor.submit(
                    run_map_extraction, board, subject, grade, chapter,
                    model=_model_for(models, "map_extraction"),
                )
                future_gen = executor.submit(
                    run_generator, board, subject, grade, chapter,
                    prompt_override=working_prompt,
                    input_type_override=working_input_type,
                    previous_csv=prev_csv, feedback=prev_feedback,
                    model=_model_for(models, "generator"),
                )
                map_result = future_map.result()
                # Record spent tokens immediately — Map Extraction already completed
                # successfully even if Generator subsequently fails and escalates.
                builder.add_pipeline_usage(
                    "map_extraction", map_result.get("usage") or {}, map_result.get("cost_usd", 0.0),
                    model=_model_for(models, "map_extraction"),
                )
                try:
                    gen_result = future_gen.result()
                except (ValueError, FileNotFoundError) as e:
                    return _escalate_generation_failure(e)

            map_exists = True
            emit("agent_completed", {
                "agent": "Map Extraction",
                "output": {
                    "concepts": map_result["concepts"],
                    "skills":   map_result["skills"],
                    "usage":    map_result.get("usage"),
                    "cost_usd": map_result.get("cost_usd"),
                    "model":    _model_for(models, "map_extraction"),
                },
            })

        # ── Attempt starts after any pre-cycle work ────────────────────────────
        emit("attempt_started", {"attempt": attempt, "max_attempts": MAX_ATTEMPTS})

        # ── Generate ──────────────────────────────────────────────────────────
        emit("agent_started", {
            "agent": "Generator",
            "parallel": False,
            "attempt": attempt,
            "input": {
                "board": board, "subject": subject, "grade": grade, "chapter": chapter,
                "base_prompt": prompt_snapshot,
            },
        })

        if gen_result is None:
            # Generation may fail even after the generator's own retries (e.g. the
            # model kept returning prose). Escalate gracefully instead of crashing.
            try:
                gen_result = run_generator(
                    board, subject, grade, chapter,
                    prompt_override=working_prompt,
                    input_type_override=working_input_type,
                    previous_csv=prev_csv, feedback=prev_feedback,
                    model=_model_for(models, "generator"),
                )
            except (ValueError, FileNotFoundError) as e:
                return _escalate_generation_failure(e)

        current_csv        = gen_result["csv"]
        current_input_type = gen_result["input_type"]

        emit("agent_completed", {
            "agent": "Generator",
            "output": {
                "rows":       len(gen_result["rows"]),
                "input_type": current_input_type,
                "csv_preview": current_csv,
                "usage":      gen_result.get("usage"),
                "cost_usd":   gen_result.get("cost_usd"),
                "model":      _model_for(models, "generator"),
            },
        })
        print(f"[orchestrator] Generated {len(gen_result['rows'])} rows via {current_input_type}")

        # ── Evaluate ──────────────────────────────────────────────────────────
        try:
            csm_data = load_concept_skill_map(board, subject, grade, chapter)
        except Exception:
            csm_data = None

        emit("agent_started", {
            "agent": "Eval",
            "attempt": attempt,
            "input": {
                "rows": len(gen_result["rows"]),
                "csv_preview": current_csv,
                "concept_skill_map": csm_data,
            },
        })

        eval_model = _model_for(models, "eval")
        eval_result = run_eval(current_csv, board, subject, grade, chapter, model=eval_model)
        c1 = eval_result["check1"]
        c2 = eval_result["check2"]

        emit("agent_completed", {
            "agent": "Eval",
            "output": {
                "check1": {
                    "passed":   c1["passed"],
                    "feedback": c1["feedback"],
                    "usage":    c1.get("usage"),
                    "cost_usd": c1.get("cost_usd"),
                },
                "check2": {
                    "passed":            c2["passed"],
                    "feedback":          c2.get("feedback",          []),
                    "missing_concepts":  c2.get("missing_concepts",  []),
                    "missing_skills":    c2.get("missing_skills",    []),
                    "matched_concepts":  c2.get("matched_concepts",  {}),
                    "matched_skills":    c2.get("matched_skills",    {}),
                    "extra_concepts":    c2.get("extra_concepts",    []),
                    "extra_skills":      c2.get("extra_skills",      []),
                    "reconciliation":    c2.get("reconciliation",    {"concepts": {}, "skills": {}}),
                    "usage":             c2.get("usage"),
                    "cost_usd":          c2.get("cost_usd"),
                },
                "usage":    eval_result.get("usage"),
                "cost_usd": eval_result.get("cost_usd"),
                "model":    eval_model,
            },
        })

        print(f"[orchestrator] Check 1: {'✓ PASSED' if c1['passed'] else '✗ FAILED'}")
        print(f"[orchestrator] Check 2: {'✓ PASSED' if c2['passed'] else '✗ FAILED'}")

        builder.add_attempt(
            attempt=attempt,
            input_type=current_input_type,
            prompt=prompt_snapshot,
            gen_csv=current_csv,
            gen_rows=len(gen_result["rows"]),
            check1=c1,
            check2=c2,
            usage=gen_result.get("usage"),
            cost_usd=gen_result.get("cost_usd", 0.0),
            model=_model_for(models, "generator"),
        )

        if c1["passed"] and c2["passed"]:
            print(f"\n[orchestrator] ✓ Pipeline passed on attempt {attempt}")
            passing_candidates.append(
                _candidate("generated", attempt, current_csv, gen_result["rows"])
            )
            break

        # ── Check-2-only failure → doctor the CSV ───────────────────────────────
        # Runs even on the LAST attempt so the final failing generation still yields
        # a fallback candidate. The doctored CSV is held as a best-candidate and used
        # below as a worked reference when writing the generalized prompt.
        check2_only           = c1["passed"] and not c2["passed"]
        doctored_this_attempt = None
        if check2_only:
            try:
                universal_rules = load_rules(board, subject, grade)
            except Exception:
                universal_rules = ""

            csm_for_doctor = csm_data
            if csm_for_doctor is None:
                try:
                    csm_for_doctor = load_concept_skill_map(board, subject, grade, chapter)
                except Exception:
                    csm_for_doctor = None

            if csm_for_doctor is not None:
                doctored_this_attempt = _doctor_and_record(
                    emit,
                    csv=current_csv, check2=c2, csm_data=csm_for_doctor,
                    universal_rules=universal_rules,
                    board=board, subject=subject, grade=grade, chapter=chapter,
                    attempt=attempt, models=models,
                )
                for entry in doctored_this_attempt.get("doctor_entries", []):
                    builder.add_doctor(attempt=attempt, **entry)
                if doctored_this_attempt["passed"]:
                    passing_candidates.append(
                        _candidate("doctored", attempt,
                                   doctored_this_attempt["csv"],
                                   doctored_this_attempt.get("rows", []))
                    )
                    print(f"[orchestrator] Doctored CSV from attempt {attempt} "
                          f"passed both checks — added as candidate")
            else:
                print("[orchestrator] No concept-skill-map available — skipping CSV doctoring")

        # ── Check-1-only failure → rules-doctor the CSV ─────────────────────────
        # Mirror of the Check-2-only path: the generated CSV already covers the CSM, so
        # rather than regenerate, surgically fix the universal-rule violations and re-verify.
        # Produces a fallback candidate only — the prompt revision below (Branch A) is
        # unchanged. Runs even on the LAST attempt so a final failing generation still
        # yields a candidate.
        check1_only = c2["passed"] and not c1["passed"]
        if check1_only:
            try:
                universal_rules = load_rules(board, subject, grade)
            except Exception:
                universal_rules = ""

            csm_for_doctor = csm_data
            if csm_for_doctor is None:
                try:
                    csm_for_doctor = load_concept_skill_map(board, subject, grade, chapter)
                except Exception:
                    csm_for_doctor = None  # rules doctor can still run without the map

            rules_doctored = _rules_doctor_and_record(
                emit,
                csv=current_csv, check1=c1, check2=c2, csm_data=csm_for_doctor,
                universal_rules=universal_rules,
                board=board, subject=subject, grade=grade, chapter=chapter,
                attempt=attempt, models=models,
            )
            for entry in rules_doctored.get("doctor_entries", []):
                builder.add_doctor(attempt=attempt, **entry)
            if rules_doctored["passed"]:
                passing_candidates.append(
                    _candidate("rules_doctored", attempt,
                               rules_doctored["csv"],
                               rules_doctored.get("rows", []))
                )
                print(f"[orchestrator] Rules-doctored CSV from attempt {attempt} "
                      f"passed both checks — added as candidate")

        # ── Stop as soon as ANY candidate passes ────────────────────────────────
        # The generator passing both checks already breaks above; this catches a
        # DOCTOR pass. A CSV that clears both checks is shippable, so we stop here
        # rather than spend more cycles hunting for a marginally cleaner generated
        # candidate — the checks define the quality bar, not a downstream preference.
        if passing_candidates:
            print(f"[orchestrator] ✓ Doctor produced a passing candidate on attempt "
                  f"{attempt} — stopping (no further cycles)")
            break

        # ── Adaptive budget ─────────────────────────────────────────────────────
        # Only reached while STILL failing both checks. Keep going while the generator
        # is closing gaps; stop early once it plateaus (no reduction for
        # MAX_PLATEAU_ROUNDS attempts) so a stuck chapter doesn't burn the whole ceiling.
        gap_count = (
            len(c1.get("feedback", []))
            + len(c2.get("missing_concepts", []))
            + len(c2.get("missing_skills", []))
        )
        if prev_gap_count is not None and gap_count >= prev_gap_count:
            plateau_rounds += 1
        else:
            plateau_rounds = 0
        prev_gap_count = gap_count

        if attempt >= MAX_ATTEMPTS or plateau_rounds >= MAX_PLATEAU_ROUNDS:
            if plateau_rounds >= MAX_PLATEAU_ROUNDS and attempt < MAX_ATTEMPTS:
                print(f"[orchestrator] Adaptive stop — no gap reduction for "
                      f"{plateau_rounds} attempt(s) (gaps stuck at {gap_count})")
            break

        # ── Revise ────────────────────────────────────────────────────────────
        feedback = _collect_feedback(c1, c2)

        # Carry this attempt's CSV + its violations into the next generation so the
        # generator revises its own output in place rather than regenerating blind.
        prev_csv      = current_csv
        prev_feedback = feedback

        if current_input_type == "cold_start":
            prompt_to_revise = (
                "Generate a curriculum CSV for the given chapter using the "
                "rules and curriculum documentation provided."
            )
        else:
            prompt_to_revise = prompt_snapshot

        if check2_only and doctored_this_attempt is not None:
            # ── Branch B — Check-2-only: subject-first specialization ladder ────
            # Use the doctored CSV as a worked reference and produce a generalized
            # prompt whose degree escalates: 1st check-2-only revision → subject,
            # 2nd → grade. The revised prompt drives the next generation in-memory.
            check2_only_revisions += 1
            degree      = "subject" if check2_only_revisions == 1 else "grade"
            level_label = "base_prompt" if degree == "subject" else "grade_prompt"

            # A doctored CSV that REGRESSED coverage (broke prior matches) is a worse
            # reference than the generation it came from — fall back to current_csv so
            # the generalized prompt learns from the better-covered example.
            if doctored_this_attempt.get("regressed") or not doctored_this_attempt["csv"]:
                reference_csv = current_csv
            else:
                reference_csv = doctored_this_attempt["csv"]
            ref_feedback  = feedback + [
                "[Reference] A corrected (doctored) CSV that satisfies coverage for this "
                "chapter is shown below. Generalise its coverage pattern — do NOT copy its "
                "chapter-specific concepts:\n" + reference_csv
            ]

            emit("agent_started", {
                "agent":   "Revision",
                "attempt": attempt,
                "input":   {"failed_check": "check2", "mode": degree, "feedback": feedback},
            })

            revision_model = _model_for(models, "revision")
            revised, revision_usage, revision_cost = run_revision(
                current_prompt=prompt_to_revise,
                feedback=ref_feedback,
                failed_check="check2",
                mode=degree,
                human_feedback=human_feedback if attempt == 1 else None,
                model=revision_model,
            )
            working_prompt     = revised          # ephemeral — drives the next attempt only
            working_input_type = level_label
            builder.add_revision(
                attempt=attempt, usage=revision_usage, cost_usd=revision_cost, model=revision_model
            )

            emit("agent_completed", {
                "agent": "Revision",
                "output": {
                    "mode":           degree,
                    "save_mode":      level_label,
                    "prompt_length":  len(revised),
                    "revised_prompt": revised,
                    "usage":          revision_usage,
                    "cost_usd":       revision_cost,
                    "model":          revision_model,
                },
            })
            print(f"[orchestrator] Revised prompt held in-memory (degree={degree}); "
                  f"drives the next generation only")

        else:
            # ── Branch A — check1 failed or both failed ─────────────────────────
            failed_check = _failed_check_label(c1["passed"], c2["passed"])
            mode         = _revision_mode(current_input_type, c1["passed"], c2["passed"])

            emit("agent_started", {
                "agent":   "Revision",
                "attempt": attempt,
                "input":   {"failed_check": failed_check, "mode": mode, "feedback": feedback},
            })

            revision_model = _model_for(models, "revision")
            revised, revision_usage, revision_cost = run_revision(
                current_prompt=prompt_to_revise,
                feedback=feedback,
                failed_check=failed_check,
                mode=mode,
                human_feedback=human_feedback if attempt == 1 else None,
                model=revision_model,
            )

            level_label        = "grade_prompt" if mode == "grade" else "base_prompt"
            working_prompt     = revised          # ephemeral — drives the next attempt only
            working_input_type = level_label
            builder.add_revision(
                attempt=attempt, usage=revision_usage, cost_usd=revision_cost, model=revision_model
            )

            emit("agent_completed", {
                "agent": "Revision",
                "output": {
                    "mode":           mode,
                    "save_mode":      level_label,
                    "prompt_length":  len(revised),
                    "revised_prompt": revised,
                    "usage":          revision_usage,
                    "cost_usd":       revision_cost,
                    "model":          revision_model,
                },
            })
            print(f"[orchestrator] Revised prompt held in-memory (mode={mode})")

    # ── Post-loop selection ─────────────────────────────────────────────────────
    c1 = eval_result["check1"]
    c2 = eval_result["check2"]

    if passing_candidates:
        if len(passing_candidates) == 1:
            chosen          = passing_candidates[0]
            selected_by     = "single"
            judge_rationale = None
            builder.set_judge(
                selected_by="single", candidate_count=1,
                chosen_id=chosen["id"], rationale=None,
                candidates=[{
                    "id":            chosen["id"],
                    "source":        chosen["source"],
                    "cycle":         chosen["cycle"],
                    "concept_count": chosen["concept_count"],
                    "skill_count":   chosen["skill_count"],
                    "verdict":       "chosen",
                }],
            )
        else:
            # ── ≥2 passing CSVs → Judge picks one ──────────────────────────────
            try:
                judge_rules = load_rules(board, subject, grade)
            except Exception:
                judge_rules = ""
            try:
                judge_csm = load_concept_skill_map(board, subject, grade, chapter)
            except Exception:
                judge_csm = None

            emit("agent_started", {
                "agent":   "Judge",
                "attempt": attempt,
                "input": {
                    "candidates": [
                        {k: c[k] for k in ("id", "source", "cycle", "concept_count", "skill_count")}
                        for c in passing_candidates
                    ],
                },
            })

            judge_model = _model_for(models, "judge")
            verdict = run_judge(
                candidates=passing_candidates,
                concept_skill_map=judge_csm,
                universal_rules=judge_rules,
                board=board, subject=subject, grade=grade, chapter=chapter,
                model=judge_model,
            )
            chosen = next(
                (c for c in passing_candidates if c["id"] == verdict.get("chosen_id")),
                passing_candidates[0],
            )
            selected_by     = "judge"
            judge_rationale = verdict.get("rationale")

            # Merge orchestrator candidate metadata with the judge's per-candidate notes.
            notes_by_id = {n.get("id"): n for n in verdict.get("candidates", [])}
            merged = []
            for c in passing_candidates:
                n = notes_by_id.get(c["id"], {})
                merged.append({
                    "id":            c["id"],
                    "source":        c["source"],
                    "cycle":         c["cycle"],
                    "concept_count": c["concept_count"],
                    "skill_count":   c["skill_count"],
                    "csv":           c["csv"],
                    "verdict":       n.get("verdict", "chosen" if c["id"] == chosen["id"] else "rejected"),
                    "note":          n.get("note", ""),
                    "strengths":     n.get("strengths", []),
                    "concerns":      n.get("concerns", []),
                })

            emit("agent_completed", {
                "agent": "Judge",
                "output": {
                    "chosen_id":  chosen["id"],
                    "rationale":  judge_rationale,
                    "candidates": merged,
                    "usage":      verdict.get("usage"),
                    "cost_usd":   verdict.get("cost_usd"),
                    "model":      judge_model,
                },
            })
            print(f"[orchestrator] Judge selected {chosen['id']} "
                  f"from {len(passing_candidates)} candidates")

            builder.set_judge(
                selected_by="judge", candidate_count=len(passing_candidates),
                chosen_id=chosen["id"], rationale=judge_rationale,
                candidates=merged,
                usage=verdict.get("usage"), cost_usd=verdict.get("cost_usd", 0.0),
                model=judge_model,
            )

        # ── Prerequisite mapping (Level 1, within-chapter) + persist checkpoint ──
        prereq_model = _model_for(models, "prerequisite")
        final_csv, checkpoint, prereq_usage, prereq_cost = _run_prerequisite_phase(
            board, subject, grade, chapter, attempt, chosen["csv"], emit, model=prereq_model
        )
        builder.add_pipeline_usage("prerequisite", prereq_usage, prereq_cost, model=prereq_model)

        # ── Persist the structured run record (latest-only) ─────────────────────
        builder.finalize(
            final_status="passed", failed_check=None,
            final_csv=final_csv, final_csv_name="confirmed.csv",
            confirmed_checkpoint=bool(checkpoint),
            has_prereqs=confirmed_csv_has_prereqs(board, subject, grade, chapter),
        )
        record, artifacts = builder.build()
        _persist_run_record(board, subject, grade, chapter, record, artifacts,
                            render_report_md(record))

        emit("pipeline_passed", {
            "attempt":         attempt,
            "csv":             final_csv,
            "source":          chosen["source"],
            "selected_by":     selected_by,
            "candidate_count": len(passing_candidates),
            "judge_rationale": judge_rationale,
            "checkpoint":      checkpoint,
        })
        return {
            "passed":      True,
            "csv":         final_csv,
            "attempts":    attempt,
            "source":      chosen["source"],
            "selected_by": selected_by,
            "checkpoint":  checkpoint,
        }

    # ── Escalate ──────────────────────────────────────────────────────────────
    failed_check = _failed_check_label(c1["passed"], c2["passed"])

    builder.finalize(
        final_status="escalated", failed_check=failed_check,
        final_csv=current_csv or "", final_csv_name="last_csv.csv",
        confirmed_checkpoint=False, has_prereqs=False,
    )
    record, artifacts = builder.build()
    report_md = render_report_md(record)
    _persist_run_record(board, subject, grade, chapter, record, artifacts, report_md)

    folder = write_escalation(
        board=board, subject=subject, grade=grade, chapter=chapter,
        date=date.today().isoformat(),
        record=record, artifacts=artifacts,
    )

    print(f"\n{'='*60}")
    print(f"⚠  ESCALATION REQUIRED")
    print(f"Pipeline failed after {attempt} attempt(s).")
    print(f"Report folder: {folder}")
    print(f"{'='*60}\n")

    emit("pipeline_escalated", {
        "attempt":      attempt,
        "failed_check": failed_check,
        "folder":       folder,
        "last_feedback": {
            "check1": c1["feedback"],
            "check2": {
                "feedback":         c2.get("feedback", []),
                "missing_concepts": c2.get("missing_concepts", []),
                "missing_skills":   c2.get("missing_skills", []),
            },
        },
    })

    return {"passed": False, "csv": current_csv, "attempts": attempt}


# ─── Special handlers ─────────────────────────────────────────────────────────

def handle_reject(board, subject, grade, chapter, reason, emit=None, models: dict | None = None):
    emit = emit or _noop
    print(f"\n[orchestrator] Encoding rejection as grade rule: {reason}")
    append_grade_rule(board, subject, grade, reason)
    print(f"[orchestrator] Rule saved. Re-running pipeline...\n")
    return run_pipeline(board, subject, grade, chapter, models=models, emit=emit)


def handle_re_extract(board, subject, grade, chapter, map_guidance, emit=None, models: dict | None = None):
    emit = emit or _noop
    print(f"\n[orchestrator] Saving extraction guidance...")
    save_extraction_guidance(board, subject, grade, chapter, map_guidance)
    emit("agent_started", {
        "agent": "Map Extraction",
        "input": {"guidance": map_guidance[:100]},
    })
    map_model = _model_for(models, "map_extraction")
    result = run_map_extraction(board, subject, grade, chapter, guidance=map_guidance, model=map_model)
    emit("agent_completed", {
        "agent": "Map Extraction",
        "output": {
            "concepts": result["concepts"],
            "skills":   result["skills"],
            "usage":    result.get("usage"),
            "cost_usd": result.get("cost_usd"),
            "model":    map_model,
        },
    })
    print(f"[orchestrator] New map: {len(result['concepts'])} concepts, {len(result['skills'])} skills")
    return run_pipeline(board, subject, grade, chapter, models=models, emit=emit)


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Q-Matrix Curriculum CSV Pipeline")
    parser.add_argument("--board",          default=None)
    parser.add_argument("--subject",        default=None)
    parser.add_argument("--grade",          default=None)
    parser.add_argument("--chapter",        default=None)
    parser.add_argument("--human-feedback", default=None)
    parser.add_argument("--reject",         action="store_true")
    parser.add_argument("--reason",         default=None)
    parser.add_argument("--re-extract",     action="store_true")
    parser.add_argument("--map-guidance",   default=None)
    parser.add_argument("--prereq-csv",     default=None,
                        help="Path to a curriculum CSV; skips Stage 1 and runs only "
                             "prerequisite mapping (identifiers derived from the CSV).")
    parser.add_argument("--no-sync",        action="store_true")

    args = parser.parse_args()

    # The prereq-only path derives identifiers from the CSV; every other path needs them.
    if not args.prereq_csv:
        missing = [f"--{n}" for n in ("board", "subject", "grade", "chapter")
                   if not getattr(args, n)]
        if missing:
            parser.error(f"the following arguments are required: {', '.join(missing)}")
    if args.reject and not args.reason:
        parser.error("--reject requires --reason")
    if args.re_extract and not args.map_guidance:
        parser.error("--re-extract requires --map-guidance")

    if args.prereq_csv:
        with open(args.prereq_csv, "r", encoding="utf-8") as f:
            result = run_prerequisite_only(f.read())
        sys.exit(0 if result["passed"] else 1)

    if not args.no_sync:
        try:
            pull_kb()
        except Exception as e:
            print(f"[orchestrator] Warning: KB pull failed — {e}")

    if args.reject:
        result = handle_reject(args.board, args.subject, args.grade, args.chapter, args.reason)
    elif args.re_extract:
        result = handle_re_extract(args.board, args.subject, args.grade, args.chapter, args.map_guidance)
    else:
        result = run_pipeline(
            args.board, args.subject, args.grade, args.chapter,
            human_feedback=args.human_feedback,
        )

    # Push after every run (pass OR escalation) so the structured run record — which
    # is now written on escalations too — reaches the remote KB. Gated only by --no-sync.
    if not args.no_sync:
        try:
            push_kb(args.board, args.subject, args.grade, args.chapter)
        except Exception as e:
            print(f"[orchestrator] Warning: KB push failed — {e}")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()