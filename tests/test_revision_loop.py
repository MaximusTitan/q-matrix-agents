"""
tests/test_revision_loop.py

Integration test — runs the full revision loop:
Generator → Eval → Revision Agent → Generator → Eval

This simulates exactly what the orchestrator does on a failed run.

Prerequisites:
  - concept-skill-map exists for the chapter
  - curriculum docs exist in KB

Run from repo root: python tests/test_revision_loop.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.generator import run as generate
from agents.eval import run as evaluate
from agents.revision import run as revise

# ── Configure to match a real chapter in your KB ───────────────────────────
BOARD   = "CBSE"
SUBJECT = "Science"
GRADE   = "Grade 8"
CHAPTER = "Chapter10_Sound"
MAX_ATTEMPTS = 3
# ───────────────────────────────────────────────────────────────────────────

print(f"\n{'='*55}")
print(f"Revision Loop Test: Generator → Eval → Revision")
print(f"Target: {BOARD}/{SUBJECT}/{GRADE}/{CHAPTER}")
print(f"{'='*55}\n")

current_prompt = None  # will use KB prompt resolution on first run
attempt = 0
passed  = False

while attempt < MAX_ATTEMPTS:
    attempt += 1
    print(f"\n── Attempt {attempt}/{MAX_ATTEMPTS} ─────────────────────────────────")

    # Generate
    gen_result   = generate(BOARD, SUBJECT, GRADE, CHAPTER)
    current_csv  = gen_result["csv"]
    input_type   = gen_result["input_type"]
    print(f"Generated {len(gen_result['rows'])} rows via {input_type}")

    # Evaluate
    eval_result = evaluate(current_csv, BOARD, SUBJECT, GRADE, CHAPTER)
    c1 = eval_result["check1"]
    c2 = eval_result.get("check2", {})

    print(f"Check 1: {'✓ PASSED' if c1['passed'] else '✗ FAILED'}")
    if "check2" in eval_result:
        print(f"Check 2: {'✓ PASSED' if c2['passed'] else '✗ FAILED'}")

    # Check if both passed
    if c1["passed"] and c2.get("passed", False):
        passed = True
        print(f"\n✓ PIPELINE PASSED on attempt {attempt}")
        print(f"\n── Final CSV ──────────────────────────────────────────")
        print(current_csv)
        break

    # Determine what failed and collect feedback
    if not c1["passed"]:
        failed_check = "check1"
        feedback     = c1["feedback"]
    else:
        failed_check = "check2"
        feedback     = c2.get("feedback", [])

    print(f"\nFeedback ({len(feedback)} item(s)):")
    for f in feedback:
        print(f"  - {f}")

    if attempt == MAX_ATTEMPTS:
        print(f"\n✗ ESCALATE TO HUMAN — failed after {MAX_ATTEMPTS} attempts")
        break

    # Revise
    print(f"\n── Revision Agent ─────────────────────────────────────")

    # Load the current prompt for revision
    from skills.kb_access import load_prompt
    prompt_content, current_input_type = load_prompt(BOARD, SUBJECT, GRADE)

    # When cold start, don't pass universal_rules as the prompt to revise.
    # Give the Revision Agent a clean seed — it should write a new generation
    # prompt that fixes the failure, not rewrite the rules document.
    if current_input_type == "cold_start":
        prompt_to_revise = (
            "Generate a curriculum CSV for the given chapter using the "
            "rules and curriculum documentation provided."
        )
    else:
        prompt_to_revise = prompt_content

    revised = revise(
        current_prompt=prompt_to_revise,
        feedback=feedback,
        failed_check=failed_check,
        mode="subject",
    )

    print(f"Revised prompt ({len(revised)} chars)")
    print(f"\n── Revised Prompt Preview ─────────────────────────────")
    print(revised[:500] + ("..." if len(revised) > 500 else ""))

    # Save revised prompt as base_prompt for next iteration
    from skills.kb_access import save_prompt
    save_prompt(BOARD, SUBJECT, revised, mode="base_prompt")
    print(f"\nSaved revised prompt as base_prompt.md")

if not passed:
    print(f"\n── Summary ────────────────────────────────────────────")
    print(f"Pipeline did not pass in {MAX_ATTEMPTS} attempts.")
    print(f"Last eval result:")
    print(json.dumps(eval_result, indent=2))
