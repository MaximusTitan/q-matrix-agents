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

from skills.kb_access import (
    concept_skill_map_exists,
    load_concept_skill_map,
    load_prompt,
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

    map_exists         = concept_skill_map_exists(board, subject, grade, chapter)
    current_csv        = None
    current_input_type = None
    eval_result        = None
    revision_occurred  = False
    attempt_history    = []
    attempt            = 0

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        print(f"\n── Attempt {attempt}/{MAX_ATTEMPTS} ──────────────────────────────────────")

        prompt_snapshot, _ = load_prompt(board, subject, grade)

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
            gen_result = run_generator(board, subject, grade, chapter)

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
            break

        if attempt == MAX_ATTEMPTS:
            break

        # ── Revise ────────────────────────────────────────────────────────────
        failed_check = _failed_check_label(c1["passed"], c2["passed"])
        feedback     = _collect_feedback(c1, c2)
        mode         = _revision_mode(current_input_type, c1["passed"], c2["passed"])

        if current_input_type == "cold_start":
            prompt_to_revise = (
                "Generate a curriculum CSV for the given chapter using the "
                "rules and curriculum documentation provided."
            )
        else:
            prompt_to_revise = prompt_snapshot

        emit("agent_started", {
            "agent": "Revision",
            "attempt": attempt,
            "input": {
                "failed_check": failed_check,
                "mode":         mode,
                "feedback":     feedback,
            },
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

    # ── Post-loop ─────────────────────────────────────────────────────────────
    c1     = eval_result["check1"]
    c2     = eval_result["check2"]
    passed = c1["passed"] and c2["passed"]

    if passed:
        if current_input_type == "cold_start" and not revision_occurred:
            universal, _ = load_prompt(board, subject, grade)
            save_prompt(board, subject, universal, mode="base_prompt")
            print("[orchestrator] Saved universal_rules as base_prompt.md")

        emit("pipeline_passed", {
            "attempt":  attempt,
            "rows":     len(gen_result["rows"]),
            "csv":      current_csv,
        })
        return {"passed": True, "csv": current_csv, "attempts": attempt}

    # ── Escalate ──────────────────────────────────────────────────────────────
    failed_check = _failed_check_label(c1["passed"], c2["passed"])

    folder = write_escalation(
        board=board, subject=subject, grade=grade, chapter=chapter,
        date=date.today().isoformat(),
        failed_check=failed_check,
        attempts=attempt,
        last_csv=current_csv or "",
        attempt_history=attempt_history,
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