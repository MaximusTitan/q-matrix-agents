"""
tests/test_map_extraction.py

Run Map Extraction for every chapter in a Grade folder, skipping any that
already have a concept-skill-map.json in the KB.

Run from repo root: python tests/test_map_extraction.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.map_extraction import run
from skills.kb_access import concept_skill_map_exists

# ── Configure target grade ──────────────────────────────────────────────────
BOARD   = "CBSE"
SUBJECT = "Science"
GRADE   = "Grade 8"
# ───────────────────────────────────────────────────────────────────────────

KB_ROOT = os.getenv("KB_ROOT")
grade_path = os.path.join(KB_ROOT, "textbooks", BOARD, SUBJECT, GRADE)

chapters = sorted(
    d for d in os.listdir(grade_path)
    if os.path.isdir(os.path.join(grade_path, d))
)

print(f"\nMap Extraction — {BOARD}/{SUBJECT}/{GRADE}")
print(f"Found {len(chapters)} chapter(s)\n")

skipped = []
processed = []
failed = []

for chapter in chapters:
    if concept_skill_map_exists(BOARD, SUBJECT, GRADE, chapter):
        print(f"  [skip]  {chapter} — already has concept-skill-map.json")
        skipped.append(chapter)
        continue

    print(f"  [run]   {chapter}")
    try:
        result = run(BOARD, SUBJECT, GRADE, chapter)
        print(f"          -> {len(result['concepts'])} concepts, {len(result['skills'])} skills\n")
        processed.append(chapter)
    except Exception as e:
        print(f"          -> ERROR: {e}\n")
        failed.append((chapter, str(e)))

# ── Summary ─────────────────────────────────────────────────────────────────
print("\n── Summary ────────────────────────────────────────────")
print(f"  Processed : {len(processed)}")
print(f"  Skipped   : {len(skipped)}")
print(f"  Failed    : {len(failed)}")

if failed:
    print("\n── Failures ───────────────────────────────────────────")
    for chapter, err in failed:
        print(f"  {chapter}: {err}")
