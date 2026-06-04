"""
tests/test_generator_eval.py

Integration test — runs Generator Agent then immediately passes
its output to Eval Agent. This is how the pipeline actually works.

Prerequisites:
  - concept-skill-map exists for the chapter (run test_map_extraction.py first)
  - curriculum docs exist in KB

Run from repo root: python tests/test_generator_eval.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.generator import run as generate
from agents.eval import run as evaluate

# ── Configure to match a real chapter in your KB ───────────────────────────
BOARD   = "CBSE"
SUBJECT = "Science"
GRADE   = "Grade 8"
CHAPTER = "Chapter10_Sound"
# ───────────────────────────────────────────────────────────────────────────

print(f"\n{'='*55}")
print(f"Integration Test: Generator → Eval")
print(f"Target: {BOARD}/{SUBJECT}/{GRADE}/{CHAPTER}")
print(f"{'='*55}\n")

# Step 1 — Generate
print("── Step 1: Generator Agent ────────────────────────────")
gen_result = generate(BOARD, SUBJECT, GRADE, CHAPTER)
print(f"Generated {len(gen_result['rows'])} rows via {gen_result['input_type']}")

# Step 2 — Evaluate
print("\n── Step 2: Eval Agent ─────────────────────────────────")
eval_result = evaluate(gen_result["csv"], BOARD, SUBJECT, GRADE, CHAPTER)

# Step 3 — Report
print(f"\n── Results ────────────────────────────────────────────")

c1 = eval_result["check1"]
print(f"Check 1 — Universal Rules: {'✓ PASSED' if c1['passed'] else '✗ FAILED'}")
if c1["feedback"]:
    for f in c1["feedback"]:
        print(f"  - {f}")

if "check2" in eval_result:
    c2 = eval_result["check2"]
    print(f"Check 2 — CSM Coverage:    {'✓ PASSED' if c2['passed'] else '✗ FAILED'}")
    if c2.get("missing_concepts"):
        print(f"  Missing concepts ({len(c2['missing_concepts'])}):")
        for c in c2["missing_concepts"]:
            print(f"    - {c}")
    if c2.get("missing_skills"):
        print(f"  Missing skills ({len(c2['missing_skills'])}):")
        for s in c2["missing_skills"]:
            print(f"    - {s}")
    if c2.get("reasoning"):
        print(f"  Reasoning: {c2['reasoning']}")
else:
    print("Check 2 — Skipped (Check 1 failed)")

# Overall
both_passed = (
    eval_result["check1"]["passed"] and
    eval_result.get("check2", {}).get("passed", False)
)
print(f"\n{'✓ PIPELINE PASSED' if both_passed else '✗ PIPELINE FAILED — revision needed'}")
