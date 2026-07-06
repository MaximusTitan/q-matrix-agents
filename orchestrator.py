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
from agents.prerequisite   import run as run_prerequisite, L1_COLUMNS

from skills.kb_access import (
    concept_skill_map_exists,
    load_concept_skill_map,
    load_prompt,
    load_prompt_at_level,
    load_rules,
    save_prompt,
    append_grade_rule,
    write_escalation,
    save_extraction_guidance,
    save_confirmed_csv,
)
from skills.csv_utils import parse_csv, enriched_csv_to_text, validate_csv_schema
from skills.git_sync import pull_kb, push_kb

MAX_ATTEMPTS = 3


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _noop(*args, **kwargs):
    pass


def _revision_mode(input_type: str, c1_passed: bool, c2_passed: bool) -> str:
    if not c1_passed:
        return "subject" if input_type in ("cold_start", "base_prompt") else "grade"
    return "grade"


def _run_prerequisite_phase(board, subject, grade, chapter, attempt, csv_text, emit):
    """
    Run Level-1 (within-chapter) prerequisite mapping on a confirmed CSV, persist the
    enriched CSV checkpoint, and emit Prerequisites agent events.

    A failure here must NOT escalate an already-confirmed run: on any error we persist the
    base CSV with empty prerequisite columns and continue.

    Returns:
        (final_csv: str, checkpoint_path: str | None)
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
        return csv_text, None

    try:
        result = run_prerequisite(rows, board, subject, grade, chapter)
        enriched_rows = result["rows"]
        warnings      = result.get("warnings", [])
        concept_edges = result.get("concept_edges", {})
        skill_edges   = result.get("skill_edges", {})
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
        },
    })
    return final_csv, checkpoint


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


def run_prerequisite_only(csv_text: str, emit=None) -> dict:
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

    final_csv, checkpoint = _run_prerequisite_phase(
        board, subject, grade, chapter, attempt=1, csv_text=csv_text, emit=emit
    )

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
) -> dict:
    """
    Doctor a Check-2-only failing CSV and re-verify it through both checks.

    Used on the Check-2-only path: the generated CSV already passed Check 1, so rather
    than regenerate, we surgically patch it to close coverage gaps and re-evaluate.

    Returns:
        {"csv": str|None, "passed": bool} — csv is None if doctoring produced an
        invalid CSV or errored. Never raises.
    """
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

    try:
        doc = run_doctor(
            failing_csv=csv,
            check2=check2,
            concept_skill_map=csm_data,
            universal_rules=universal_rules,
            board=board, subject=subject, grade=grade, chapter=chapter,
        )
    except Exception as e:
        print(f"[orchestrator] CSV doctoring errored — {e}")
        emit("agent_completed", {"agent": "Doctor", "output": {"error": str(e)}})
        return {"csv": None, "passed": False}

    if doc.get("csv") is None:
        emit("agent_completed", {
            "agent":  "Doctor",
            "output": {"error": doc.get("error", "invalid CSV after retry")},
        })
        return {"csv": None, "passed": False}

    doctored_csv = doc["csv"]
    emit("agent_completed", {
        "agent":  "Doctor",
        "output": {"rows": len(doc["rows"]), "csv_preview": doctored_csv},
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
    doc_eval = run_eval(doctored_csv, board, subject, grade, chapter)
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
            },
        },
    })
    print(f"[orchestrator] Doctored CSV re-verify — "
          f"check1 {'✓' if dc1['passed'] else '✗'}, check2 {'✓' if dc2['passed'] else '✗'}"
          f"{' (REGRESSED)' if regressed else ''}")

    # ── Doctor chain: coverage fixed but rules broke → Rules Doctor ─────────────
    # The coverage Doctor closed the Check-2 gap but introduced a Check-1 (rules)
    # violation — a CSV one rule-fix away from passing. Hand it to the Rules Doctor,
    # which fixes rules WHILE preserving coverage (its own regression guard protects
    # the coverage just gained). One bounded extra pass — no loop. Only chain when the
    # coverage gain is real (not regressed); a regressed CSV is not worth rescuing.
    if dc2["passed"] and not dc1["passed"] and not regressed:
        print("[orchestrator] Coverage Doctor fixed Check 2 but broke Check 1 — "
              "chaining Rules Doctor to repair rules while preserving coverage")
        chained = _rules_doctor_and_record(
            emit,
            csv=doctored_csv, check1=dc1, check2=dc2, csm_data=csm_data,
            universal_rules=universal_rules,
            board=board, subject=subject, grade=grade, chapter=chapter,
            attempt=attempt,
        )
        if chained.get("csv") is not None:
            # The chained result (rules-repaired) supersedes the coverage-only output.
            return chained

    return {
        "csv":                doctored_csv,
        "passed":             doc_eval["passed"],
        "rows":               doc["rows"],
        "regressed":          regressed,
        "regressed_concepts": regressions["concepts"],
        "regressed_skills":   regressions["skills"],
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
    emit("agent_started", {
        "agent":   "Doctor (rules)",
        "attempt": attempt,
        "input": {
            "violations":  check1.get("feedback", []),
            "csv_preview": csv,
        },
    })

    try:
        doc = run_rules_doctor(
            failing_csv=csv,
            check1=check1,
            universal_rules=universal_rules,
            concept_skill_map=csm_data,
            check2=check2,
            board=board, subject=subject, grade=grade, chapter=chapter,
        )
    except Exception as e:
        print(f"[orchestrator] Rules doctoring errored — {e}")
        emit("agent_completed", {"agent": "Doctor (rules)", "output": {"error": str(e)}})
        return {"csv": None, "passed": False}

    if doc.get("csv") is None:
        emit("agent_completed", {
            "agent":  "Doctor (rules)",
            "output": {"error": doc.get("error", "invalid CSV after retry")},
        })
        return {"csv": None, "passed": False}

    doctored_csv = doc["csv"]
    emit("agent_completed", {
        "agent":  "Doctor (rules)",
        "output": {"rows": len(doc["rows"]), "csv_preview": doctored_csv},
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
    doc_eval = run_eval(doctored_csv, board, subject, grade, chapter)
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
            },
        },
    })
    print(f"[orchestrator] Rules-doctored CSV re-verify — "
          f"check1 {'✓' if dc1['passed'] else '✗'}, check2 {'✓' if dc2['passed'] else '✗'}"
          f"{' (REGRESSED)' if regressed else ''}")

    return {
        "csv":                doctored_csv,
        "passed":             doc_eval["passed"],
        "rows":               doc["rows"],
        "regressed":          regressed,
        "regressed_concepts": regressions["concepts"],
        "regressed_skills":   regressions["skills"],
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
    emit=None,
) -> dict:
    """
    Run the full pipeline for one chapter.

    Args:
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
    revision_occurred     = False
    attempt_history       = []
    attempt               = 0

    # ── Check-2-only path state ────────────────────────────────────────────────
    check2_only_revisions = 0     # drives subject(1st) → grade(2nd) specialization degree
    forced_level          = None  # forces the NEXT generation to a specific prompt level
    passing_candidates    = []    # every CSV that passed BOTH checks (generated + doctored)
    doctored_artifacts    = []    # [{attempt, csv, passed}] — persisted on escalation

    def _escalate_generation_failure(err: Exception) -> dict:
        """Escalate (rather than crash) when generation can't yield a valid CSV.

        Records progress in the KB and emits a terminal escalation so the dashboard —
        and any queued batch — advances. Called from both generation call sites.
        """
        print(f"[orchestrator] Generation failed on attempt {attempt} — escalating: {err}")
        emit("agent_completed", {"agent": "Generator", "output": {"error": str(err)}})
        folder = write_escalation(
            board=board, subject=subject, grade=grade, chapter=chapter,
            date=date.today().isoformat(),
            failed_check="generation",
            attempts=attempt,
            last_csv=current_csv or "",
            attempt_history=attempt_history,
            doctored_artifacts=doctored_artifacts,
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

        if forced_level is None:
            prompt_snapshot, _ = load_prompt(board, subject, grade)
        else:
            prompt_snapshot, _ = load_prompt_at_level(board, subject, grade, forced_level)

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
                future_map = executor.submit(run_map_extraction, board, subject, grade, chapter)
                future_gen = executor.submit(run_generator,      board, subject, grade, chapter)
                map_result = future_map.result()
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
                gen_result = run_generator(board, subject, grade, chapter, forced_level=forced_level)
            except (ValueError, FileNotFoundError) as e:
                return _escalate_generation_failure(e)

        forced_level       = None  # consumed — each forcing applies to exactly one regeneration
        current_csv        = gen_result["csv"]
        current_input_type = gen_result["input_type"]

        emit("agent_completed", {
            "agent": "Generator",
            "output": {
                "rows":       len(gen_result["rows"]),
                "input_type": current_input_type,
                "csv_preview": current_csv,
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

        eval_result = run_eval(current_csv, board, subject, grade, chapter)
        c1 = eval_result["check1"]
        c2 = eval_result["check2"]

        emit("agent_completed", {
            "agent": "Eval",
            "output": {
                "check1": {
                    "passed":   c1["passed"],
                    "feedback": c1["feedback"],
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
                },
            },
        })

        print(f"[orchestrator] Check 1: {'✓ PASSED' if c1['passed'] else '✗ FAILED'}")
        print(f"[orchestrator] Check 2: {'✓ PASSED' if c2['passed'] else '✗ FAILED'}")

        attempt_history.append({
            "attempt":    attempt,
            "input_type": current_input_type,
            "check1":     c1,
            "check2":     c2,
            "prompt":     prompt_snapshot,
        })

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
                    attempt=attempt,
                )
                doctored_artifacts.append({
                    "attempt":   attempt,
                    "csv":       doctored_this_attempt["csv"],
                    "passed":    doctored_this_attempt["passed"],
                    "regressed": doctored_this_attempt.get("regressed", False),
                })
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
                attempt=attempt,
            )
            doctored_artifacts.append({
                "attempt":   attempt,
                "kind":      "rules",
                "csv":       rules_doctored["csv"],
                "passed":    rules_doctored["passed"],
                "regressed": rules_doctored.get("regressed", False),
            })
            if rules_doctored["passed"]:
                passing_candidates.append(
                    _candidate("rules_doctored", attempt,
                               rules_doctored["csv"],
                               rules_doctored.get("rows", []))
                )
                print(f"[orchestrator] Rules-doctored CSV from attempt {attempt} "
                      f"passed both checks — added as candidate")

        if attempt == MAX_ATTEMPTS:
            break

        # ── Revise ────────────────────────────────────────────────────────────
        feedback = _collect_feedback(c1, c2)

        if current_input_type == "cold_start":
            prompt_to_revise = (
                "Generate a curriculum CSV for the given chapter using the "
                "rules and curriculum documentation provided."
            )
        else:
            prompt_to_revise = prompt_snapshot

        if check2_only and doctored_this_attempt is not None:
            # ── Branch B — Check-2-only: subject-first specialization ladder ────
            # Use the doctored CSV as a worked reference and write a generalized
            # prompt whose degree escalates: 1st check-2-only revision → subject,
            # 2nd → grade. Force the next generation to that exact level.
            check2_only_revisions += 1
            degree    = "subject" if check2_only_revisions == 1 else "grade"
            save_mode = "base_prompt" if degree == "subject" else "grade_prompt"

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

            revised = run_revision(
                current_prompt=prompt_to_revise,
                feedback=ref_feedback,
                failed_check="check2",
                mode=degree,
                human_feedback=human_feedback if attempt == 1 else None,
            )
            save_prompt(board, subject, revised, mode=save_mode, grade=grade)
            revision_occurred = True
            forced_level      = save_mode  # next generation must use this exact level

            emit("agent_completed", {
                "agent": "Revision",
                "output": {
                    "mode":           degree,
                    "save_mode":      save_mode,
                    "prompt_length":  len(revised),
                    "revised_prompt": revised,
                },
            })
            print(f"[orchestrator] Saved revised prompt ({save_mode}); "
                  f"forcing next generation to '{forced_level}'")

        else:
            # ── Branch A — check1 failed or both failed (UNCHANGED behavior) ────
            failed_check = _failed_check_label(c1["passed"], c2["passed"])
            mode         = _revision_mode(current_input_type, c1["passed"], c2["passed"])

            emit("agent_started", {
                "agent":   "Revision",
                "attempt": attempt,
                "input":   {"failed_check": failed_check, "mode": mode, "feedback": feedback},
            })

            revised = run_revision(
                current_prompt=prompt_to_revise,
                feedback=feedback,
                failed_check=failed_check,
                mode=mode,
                human_feedback=human_feedback if attempt == 1 else None,
            )

            save_mode = "grade_prompt" if mode == "grade" else "base_prompt"
            save_prompt(board, subject, revised, mode=save_mode, grade=grade)
            revision_occurred = True

            emit("agent_completed", {
                "agent": "Revision",
                "output": {
                    "mode":           mode,
                    "save_mode":      save_mode,
                    "prompt_length":  len(revised),
                    "revised_prompt": revised,
                },
            })
            print(f"[orchestrator] Saved revised prompt ({save_mode})")

    # ── Post-loop selection ─────────────────────────────────────────────────────
    c1 = eval_result["check1"]
    c2 = eval_result["check2"]
    generated_passed = c1["passed"] and c2["passed"]

    # Learn a reusable base_prompt from a clean cold-start generated pass (unchanged).
    if generated_passed and current_input_type == "cold_start" and not revision_occurred:
        universal, _ = load_prompt(board, subject, grade)
        save_prompt(board, subject, universal, mode="base_prompt")
        print("[orchestrator] Saved universal_rules as base_prompt.md")

    if passing_candidates:
        if len(passing_candidates) == 1:
            chosen          = passing_candidates[0]
            selected_by     = "single"
            judge_rationale = None
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

            verdict = run_judge(
                candidates=passing_candidates,
                concept_skill_map=judge_csm,
                universal_rules=judge_rules,
                board=board, subject=subject, grade=grade, chapter=chapter,
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
                },
            })
            print(f"[orchestrator] Judge selected {chosen['id']} "
                  f"from {len(passing_candidates)} candidates")

        # ── Prerequisite mapping (Level 1, within-chapter) + persist checkpoint ──
        final_csv, checkpoint = _run_prerequisite_phase(
            board, subject, grade, chapter, attempt, chosen["csv"], emit
        )

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

    folder = write_escalation(
        board=board, subject=subject, grade=grade, chapter=chapter,
        date=date.today().isoformat(),
        failed_check=failed_check,
        attempts=attempt,
        last_csv=current_csv or "",
        attempt_history=attempt_history,
        doctored_artifacts=doctored_artifacts,
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

def handle_reject(board, subject, grade, chapter, reason, emit=None):
    emit = emit or _noop
    print(f"\n[orchestrator] Encoding rejection as grade rule: {reason}")
    append_grade_rule(board, subject, grade, reason)
    print(f"[orchestrator] Rule saved. Re-running pipeline...\n")
    return run_pipeline(board, subject, grade, chapter, emit=emit)


def handle_re_extract(board, subject, grade, chapter, map_guidance, emit=None):
    emit = emit or _noop
    print(f"\n[orchestrator] Saving extraction guidance...")
    save_extraction_guidance(board, subject, grade, chapter, map_guidance)
    emit("agent_started", {
        "agent": "Map Extraction",
        "input": {"guidance": map_guidance[:100]},
    })
    result = run_map_extraction(board, subject, grade, chapter, guidance=map_guidance)
    emit("agent_completed", {
        "agent": "Map Extraction",
        "output": {
            "concepts": result["concepts"],
            "skills":   result["skills"],
        },
    })
    print(f"[orchestrator] New map: {len(result['concepts'])} concepts, {len(result['skills'])} skills")
    return run_pipeline(board, subject, grade, chapter, emit=emit)


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

    if not args.no_sync and (result["passed"] or args.reject):
        try:
            push_kb(args.board, args.subject, args.grade, args.chapter)
        except Exception as e:
            print(f"[orchestrator] Warning: KB push failed — {e}")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()