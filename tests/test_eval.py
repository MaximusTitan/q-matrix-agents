"""
tests/test_eval.py

Test the Eval Agent against the generated CSV from test_generator.py.
Run from repo root: python tests/test_eval.py

Requires:
  - concept-skill-map to exist in KB (run test_map_extraction.py first)
  - A CSV to evaluate (hardcoded below for testing)
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agents.eval import run

# ── Configure to match a real chapter in your KB ───────────────────────────
BOARD   = "CBSE"
SUBJECT = "Science"
GRADE   = "Grade 8"
CHAPTER = "Chapter10_Sound"
# ───────────────────────────────────────────────────────────────────────────

# Paste the CSV output from test_generator.py here
SAMPLE_CSV = """board,subject,grade,chapter,concept,skill
CBSE,Science,Grade 8,Chapter10_Sound,Properties of Sound,Differentiate between frequency and amplitude to describe factors responsible for loudness and pitch of sound
CBSE,Science,Grade 8,Chapter10_Sound,Properties of Sound,List examples of body moving in to and fro motion to explain vibration
CBSE,Science,Grade 8,Chapter10_Sound,Sound Production,List commonly known musical instruments and identify parts that vibrate to explain that vibration produces sound
CBSE,Science,Grade 8,Chapter10_Sound,Sound Production,List and identify functions of parts of human body that produce sound to explain the process of sound production
CBSE,Science,Grade 8,Chapter10_Sound,Sound Propagation,Provide examples where sound travels from one point to another to establish that sound needs a medium to propagate
CBSE,Science,Grade 8,Chapter10_Sound,Sound Propagation,Recall the audible range of sound for humans to explain why certain sounds cannot be heard by humans
CBSE,Science,Grade 8,Chapter10_Sound,Structure and Function of Human Ear,Describe the structure and function of an eardrum to explain how humans hear sound
CBSE,Science,Grade 8,Chapter10_Sound,Noise Pollution,List the harmful effects of noise pollution in order to mitigate it"""

print(f"\nTesting Eval Agent")
print(f"Target: {BOARD}/{SUBJECT}/{GRADE}/{CHAPTER}\n")

result = run(SAMPLE_CSV, BOARD, SUBJECT, GRADE, CHAPTER)

print(f"\n── Check 1 ────────────────────────────────────────────")
print(f"Passed: {result['check1']['passed']}")
if result['check1']['feedback']:
    print("Feedback:")
    for f in result['check1']['feedback']:
        print(f"  - {f}")

if "check2" in result:
    print(f"\n── Check 2 ────────────────────────────────────────────")
    print(f"Passed: {result['check2']['passed']}")
    if result['check2'].get('missing_concepts'):
        print(f"Missing concepts:")
        for c in result['check2']['missing_concepts']:
            print(f"  - {c}")
    if result['check2'].get('missing_skills'):
        print(f"Missing skills:")
        for s in result['check2']['missing_skills']:
            print(f"  - {s}")
    if result['check2'].get('feedback'):
        print(f"Feedback:")
        for f in result['check2']['feedback']:
            print(f"  - {f}")
else:
    print(f"\n── Check 2 ────────────────────────────────────────────")
    print("Skipped (Check 1 failed)")

print(f"\n── Full result JSON ───────────────────────────────────")
print(json.dumps(result, indent=2))
