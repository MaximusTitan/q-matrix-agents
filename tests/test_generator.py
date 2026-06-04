"""
tests/test_generator.py

Test the Generator Agent against a real chapter.
Run from repo root: python tests/test_generator.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.generator import run

# ── Configure to match a real chapter in your KB ───────────────────────────
BOARD   = "CBSE"
SUBJECT = "Science"
GRADE   = "Grade 8"
CHAPTER = "Chapter10_Sound"
# ───────────────────────────────────────────────────────────────────────────

print(f"\nTesting Generator Agent")
print(f"Target: {BOARD}/{SUBJECT}/{GRADE}/{CHAPTER}\n")

result = run(BOARD, SUBJECT, GRADE, CHAPTER)

print(f"\n── Result ─────────────────────────────────────────────")
print(f"input_type : {result['input_type']}")
print(f"rows       : {len(result['rows'])}")

print(f"\n── Generated CSV ──────────────────────────────────────")
print(result["csv"])

print(f"\n── Concept breakdown ──────────────────────────────────")
from collections import defaultdict
by_concept = defaultdict(list)
for row in result["rows"]:
    by_concept[row["concept"]].append(row["skill"])

for concept, skills in by_concept.items():
    print(f"\n  {concept} ({len(skills)} skills)")
    for s in skills:
        print(f"    - {s}")

# Basic checks
print(f"\n── Checks ─────────────────────────────────────────────")

non_verb = [r["skill"] for r in result["rows"] if not r["skill"][0].isupper()]
if non_verb:
    print(f"⚠ {len(non_verb)} skill(s) may not be verb-led:")
    for s in non_verb:
        print(f"  - {s}")
else:
    print(f"✓ All skills start with uppercase (verb-led check passed)")

empty = [r for r in result["rows"] if not all(r.get(c,"").strip() for c in ["board","subject","grade","chapter","concept","skill"])]
if empty:
    print(f"⚠ {len(empty)} row(s) have empty required fields")
else:
    print(f"✓ No empty required fields")

print(f"\n✓ Generator Agent test complete")
