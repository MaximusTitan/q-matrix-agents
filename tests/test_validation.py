"""
tests/test_validation.py

Phase 6 Validation — runs the pipeline across multiple chapters and
verifies KB state after each run.

Run from repo root:
    python tests/test_validation.py

Reports:
  - Which chapters passed/failed/escalated
  - Prompt accumulation (cold start → base_prompt → grade_prompt)
  - KB state summary at the end
"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from orchestrator import run_pipeline
from skills.kb_access import load_prompt, list_escalations

KB_ROOT = os.getenv("KB_ROOT")

# ── Chapters to validate ───────────────────────────────────────────────────────
# Pick 4 real chapter folder names from your KB
# Mix of grades to validate grade-level prompt behavior
RUNS = [
    {"board": "CBSE", "subject": "Science", "grade": "Grade 8", "chapter": "Chapter9_Friction"},
    {"board": "CBSE", "subject": "Science", "grade": "Grade 8", "chapter": "Chapter11_Chemical_Effects_Of_Electric_Current"},
    {"board": "CBSE", "subject": "Science", "grade": "Grade 8", "chapter": "Chapter13_Light"},
    {"board": "CBSE", "subject": "Science", "grade": "Grade 9", "chapter": "Chapter7_Motion"},
]

# ── KB state checker ───────────────────────────────────────────────────────────

def check_kb_state(board, subject):
    """Check what exists in the prompt-library for a board/subject."""
    prompt_root = Path(KB_ROOT) / "prompt-library" / board / subject
    state = {}

    if not prompt_root.exists():
        return {"base_prompt": False, "grade_prompts": []}

    state["base_prompt"] = (prompt_root / "base_prompt.md").exists()
    state["grade_prompts"] = [
        d.name for d in prompt_root.iterdir()
        if d.is_dir() and (d / "prompt.md").exists()
    ]
    return state


def check_concept_maps(board, subject):
    """Check which chapters have concept-skill-maps."""
    textbook_root = Path(KB_ROOT) / "textbooks" / board / subject
    maps = []
    if not textbook_root.exists():
        return maps
    for grade_dir in textbook_root.iterdir():
        if grade_dir.is_dir():
            for chapter_dir in grade_dir.iterdir():
                if chapter_dir.is_dir():
                    csm = chapter_dir / "concept-skill-map.json"
                    if csm.exists():
                        maps.append(f"{grade_dir.name}/{chapter_dir.name}")
    return sorted(maps)


def check_escalations(board, subject):
    """Check for any escalation folders for the given board/subject."""
    return [
        esc["folder"] for esc in list_escalations()
        if esc["board"] == board and esc["subject"] == subject
    ]


# ── Run validation ─────────────────────────────────────────────────────────────

results = []

print(f"\n{'='*65}")
print(f"Phase 6 Validation — Q-Matrix Pipeline")
print(f"Chapters to run: {len(RUNS)}")
print(f"{'='*65}\n")

for i, run in enumerate(RUNS, 1):
    board, subject, grade, chapter = run["board"], run["subject"], run["grade"], run["chapter"]

    print(f"\n── Run {i}/{len(RUNS)}: {subject} / {grade} / {chapter} {'─'*20}")

    # Check input_type BEFORE running (to know if this is a cold start)
    _, input_type_before = load_prompt(board, subject, grade)
    print(f"   Prompt type before: {input_type_before}")

    start = time.time()
    try:
        result = run_pipeline(board, subject, grade, chapter)
        duration = round(time.time() - start, 1)

        # Check input_type AFTER running
        _, input_type_after = load_prompt(board, subject, grade)

        results.append({
            "chapter":          chapter,
            "grade":            grade,
            "passed":           result["passed"],
            "attempts":         result["attempts"],
            "input_type_before": input_type_before,
            "input_type_after":  input_type_after,
            "duration_s":       duration,
            "rows":             len(result["csv"].splitlines()) - 1 if result["csv"] else 0,
        })

        status = "✓ PASSED" if result["passed"] else "⚠ ESCALATED"
        print(f"   {status} in {result['attempts']} attempt(s) · {duration}s · {results[-1]['rows']} rows")
        print(f"   Prompt type after: {input_type_after}")

    except Exception as e:
        duration = round(time.time() - start, 1)
        results.append({
            "chapter":   chapter,
            "grade":     grade,
            "passed":    False,
            "attempts":  0,
            "input_type_before": input_type_before,
            "input_type_after":  "error",
            "duration_s": duration,
            "error":     str(e),
        })
        print(f"   ✗ ERROR: {e}")

# ── Summary ────────────────────────────────────────────────────────────────────

print(f"\n\n{'='*65}")
print(f"VALIDATION SUMMARY")
print(f"{'='*65}\n")

# Results table
print(f"{'Chapter':<45} {'Grade':<10} {'Status':<12} {'Attempts':<9} {'Rows'}")
print(f"{'─'*45} {'─'*10} {'─'*12} {'─'*9} {'─'*5}")
for r in results:
    status   = "✓ PASSED" if r["passed"] else ("✗ ERROR" if "error" in r else "⚠ ESCALATED")
    attempts = str(r["attempts"])
    rows     = str(r.get("rows", "-"))
    print(f"{r['chapter']:<45} {r['grade']:<10} {status:<12} {attempts:<9} {rows}")

# Prompt accumulation
print(f"\n── Prompt Library State ──────────────────────────────────────")
subjects_seen = set((r["board"] if "board" in r else "CBSE", RUNS[0]["subject"]) for r in results)
for board, subject in [("CBSE", RUNS[0]["subject"])]:
    kb = check_kb_state(board, subject)
    print(f"  {board}/{subject}:")
    print(f"    base_prompt.md:  {'✓ exists' if kb['base_prompt'] else '✗ missing'}")
    if kb["grade_prompts"]:
        print(f"    grade prompts:   {', '.join(kb['grade_prompts'])}")
    else:
        print(f"    grade prompts:   none (base_prompt was sufficient)")

# Concept-skill-maps
print(f"\n── Concept-Skill-Maps ────────────────────────────────────────")
maps = check_concept_maps("CBSE", RUNS[0]["subject"])
print(f"  {len(maps)} map(s) generated:")
for m in maps:
    print(f"    ✓ {m}")

# Escalations
print(f"\n── Escalations ───────────────────────────────────────────────")
escs = check_escalations("CBSE", RUNS[0]["subject"])
if escs:
    print(f"  {len(escs)} escalation(s):")
    for e in escs:
        print(f"    ⚠ {e}")
else:
    print(f"  None — all chapters resolved within 3 attempts")

# Prompt accumulation analysis
print(f"\n── Prompt Accumulation Analysis ──────────────────────────────")
for r in results:
    before = r["input_type_before"]
    after  = r["input_type_after"]
    if before == "cold_start" and after in ("base_prompt", "grade_prompt"):
        print(f"  ✓ {r['chapter']}: Cold start → {after} saved")
    elif before == after:
        print(f"  ✓ {r['chapter']}: Reused {before} (no cold start needed)")
    elif before == "base_prompt" and after == "grade_prompt":
        print(f"  ✓ {r['chapter']}: Grade-specific prompt created ({r['grade']})")
    else:
        print(f"  ? {r['chapter']}: {before} → {after}")

# Pass rate
passed   = sum(1 for r in results if r.get("passed"))
total    = len(results)
avg_time = round(sum(r["duration_s"] for r in results) / total, 1) if total else 0

print(f"\n── Final Numbers ─────────────────────────────────────────────")
print(f"  Passed:        {passed}/{total}")
print(f"  Avg duration:  {avg_time}s per chapter")
print(f"  Total time:    {round(sum(r['duration_s'] for r in results), 1)}s")
print(f"\n{'='*65}")
