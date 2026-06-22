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
from agents.judge          import run as run_judge

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
)
from skills.git_sync import pull_kb, push_kb

MAX_ATTEMPTS = 3


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _noop(*args, **kwargs):
    pass


def _revision_mode(input_type: str, c1_passed: bool, c2_passed: bool) -> str:
    if not c1_passed:
        return "subject" if input_type in ("cold_start", "base_prompt") else "grade"
    return "grade"


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
    emit("agent_completed", {
        "agent":  "Eval (doctored)",
        "output": {
            "check1": {
                "passed":   dc1["passed"],
                "feedback": dc1["feedback"],
            },
            "check2": {
                "passed":           dc2["passed"],
                "feedback":         dc2.get("feedback",         []),
                "missing_concepts": dc2.get("missing_concepts", []),
                "missing_skills":   dc2.get("missing_skills",   []),
                "matched_concepts": dc2.get("matched_concepts", {}),
                "matched_skills":   dc2.get("matched_skills",   {}),
                "extra_concepts":   dc2.get("extra_concepts",   []),
                "extra_skills":     dc2.get("extra_skills",     []),
                "reconciliation":   dc2.get("reconciliation",   {"concepts": {}, "skills": {}}),
            },
        },
    })
    print(f"[orchestrator] Doctored CSV re-verify — "
          f"check1 {'✓' if dc1['passed'] else '✗'}, check2 {'✓' if dc2['passed'] else '✗'}")

    return {"csv": doctored_csv, "passed": doc_eval["passed"], "rows": doc["rows"]}


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
                gen_result = future_gen.result()

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
            gen_result = run_generator(board, subject, grade, chapter, forced_level=forced_level)

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
                    "attempt": attempt,
                    "csv":     doctored_this_attempt["csv"],
                    "passed":  doctored_this_attempt["passed"],
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

            reference_csv = doctored_this_attempt["csv"] or current_csv
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

        emit("pipeline_passed", {
            "attempt":         attempt,
            "csv":             chosen["csv"],
            "source":          chosen["source"],
            "selected_by":     selected_by,
            "candidate_count": len(passing_candidates),
            "judge_rationale": judge_rationale,
        })
        return {
            "passed":      True,
            "csv":         chosen["csv"],
            "attempts":    attempt,
            "source":      chosen["source"],
            "selected_by": selected_by,
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
    parser.add_argument("--board",          required=True)
    parser.add_argument("--subject",        required=True)
    parser.add_argument("--grade",          required=True)
    parser.add_argument("--chapter",        required=True)
    parser.add_argument("--human-feedback", default=None)
    parser.add_argument("--reject",         action="store_true")
    parser.add_argument("--reason",         default=None)
    parser.add_argument("--re-extract",     action="store_true")
    parser.add_argument("--map-guidance",   default=None)
    parser.add_argument("--no-sync",        action="store_true")

    args = parser.parse_args()

    if args.reject and not args.reason:
        parser.error("--reject requires --reason")
    if args.re_extract and not args.map_guidance:
        parser.error("--re-extract requires --map-guidance")

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