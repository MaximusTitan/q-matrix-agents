import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from skills.kb_access import load_curriculum_docs

docs = load_curriculum_docs("CBSE", "Science", "Grade 8")

print(f"Curriculum docs total chars: {len(docs)}\n")

keywords = [
    "amplitude",
    "time period",
    "hearing impairment",
    "noise",
    "audible",
    "inaudible",
    "music",
    "frequency",
]

print("Keyword search in curriculum docs:")
for kw in keywords:
    found = kw.lower() in docs.lower()
    status = "FOUND" if found else "NOT FOUND"
    print(f"  {kw:<25} {status}")
