# test_skills.py
import sys
import os
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()
KB_ROOT = os.getenv("KB_ROOT")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

from skills.file_io import read_file, file_exists
from skills.kb_access import load_rules, load_prompt, concept_skill_map_exists
from skills.pdf_reader import extract_text_from_pdf
from skills.csv_utils import parse_csv, validate_csv_schema
from skills.diff import diff_full

# Test 1 — file_io
print(f"KB_ROOT = {KB_ROOT}")
print("TEST 1: file_io")
assert file_exists(os.path.join(KB_ROOT, "rulesets", "universal_rules.md"))
print("  ✓ file_exists works")

# Test 2 — load_rules
print("TEST 2: load_rules")
rules = load_rules("CBSE", "Science", "Grade8")
print(f"  ✓ loaded rules ({len(rules)} chars)")

# Test 3 — load_prompt (cold start expected)
print("TEST 3: load_prompt")
content, input_type = load_prompt("CBSE", "Science", "Grade8")
print(f"  ✓ input_type: {input_type} ({len(content)} chars)")

# Test 4 — pdf_reader
print("TEST 4: pdf_reader")
import glob
# Handle space in grade folder name + variable chapter folder name
# Find any Chapter1_* folder under Grade 8 Science
pattern = os.path.join(KB_ROOT, "textbooks", "CBSE", "Science", "Grade 8", "Chapter*", "chapter.pdf")
matches = glob.glob(pattern)

if matches:
    pdf_path = matches[0]
    text = extract_text_from_pdf(pdf_path)
    print(f"  ✓ extracted {len(text)} chars from PDF")
    print(f"  ✓ path used: {pdf_path}")
else:
    print("  ⚠ skipped — no PDF found at test path")

# Test 5 — csv_utils
print("TEST 5: csv_utils")
sample_csv = "board,subject,grade,chapter,concept,skill\nCBSE,Science,Grade8,Chapter1,Friction,Identify types of friction"
rows = validate_csv_schema(sample_csv)
print(f"  ✓ validated {len(rows)} row(s)")

print("\nAll tests passed.")