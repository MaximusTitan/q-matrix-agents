"""
tests/test_check2_mode.py

Offline checks for orchestrator.run_pipeline's --check2-mode. Every agent that would
call an LLM is replaced with a stub, KB_ROOT points at a throwaway temp directory, and
the Gateway client is swapped for one that raises on any use — so an unstubbed call
fails the test instead of spending money. Costs $0 and needs no .env.

Report mode must: run Check 2 exactly once (on the final candidate), never call the
Doctor, keep every Check 2 item out of Generator and Revision inputs, never fail a run
on a Check 2 mismatch, and write both lists to run.json. Gate mode (the default) must
behave as before.

Run from repo root:
    python tests/test_check2_mode.py
"""

import json
import os
import sys
import tempfile

# Must be set before any project import: kb_access reads KB_ROOT at import time and
# load_dotenv() never overrides a variable that is already set.
os.environ["KB_ROOT"] = tempfile.mkdtemp(prefix="qm-check2-mode-")
os.environ["AI_GATEWAY_API_KEY"] = "offline-test-invalid-key"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skills.llm


class _NoNetwork:
    def __getattr__(self, name):
        raise AssertionError(f"unstubbed LLM call attempted (client.{name})")


skills.llm._client = _NoNetwork()

import agents.eval
import orchestrator
from skills import kb_access

BOARD, SUBJECT, GRADE = "CBSE", "Maths", "Grade 3"
MAP = {
    "concepts": ["Barter system and exchange of goods", "Counting coins and notes"],
    "skills": ["Exchange items of equal value", "Add coin values up to 100"],
}
MAP_ITEMS = MAP["concepts"] + MAP["skills"]
EXTRA = {"concepts": ["Money basics"], "skills": ["Identify a coin"]}
CHECK1_COST, CHECK2_COST = 0.001, 0.5


def _csv(chapter: str, tag: str) -> tuple[str, list[dict]]:
    """A generator-shaped CSV that shares no text with the map. `tag` identifies it."""
    rows = [
        {"board": BOARD, "subject": SUBJECT, "grade": GRADE, "chapter": chapter,
         "concept": "Money basics", "skill": f"Identify a coin ({tag})"},
    ]
    header = "board,subject,grade,chapter,concept,skill"
    lines = [header] + [",".join(r[k] for k in header.split(",")) for r in rows]
    return "\n".join(lines) + "\n", rows


class Harness:
    """Installs stubs on the orchestrator and records what each agent received."""

    def __init__(self, chapter, check1_feedback, check2_result=None, rules_doctor_passes=False):
        self.chapter = chapter
        self.check1_feedback = check1_feedback      # csv -> list of blocking violations
        self.check2_result = check2_result          # call index -> check2 dict
        self.rules_doctor_passes = rules_doctor_passes
        self.generator_calls, self.revision_calls = [], []
        self.check2_csvs, self.doctor_calls, self.rules_doctor_calls = [], [], []
        self.events = []

    # ── Stubs ────────────────────────────────────────────────────────────────
    def generator(self, board, subject, grade, chapter, prompt_override=None,
                  input_type_override=None, previous_csv=None, feedback=None, model=None):
        n = len(self.generator_calls) + 1
        self.generator_calls.append({
            "previous_csv": previous_csv, "feedback": list(feedback or []),
            "prompt": prompt_override,
        })
        csv, rows = _csv(chapter, f"gen-attempt-{n}")
        return {"csv": csv, "rows": rows, "input_type": input_type_override or "base_prompt",
                "usage": {}, "cost_usd": 0.0}

    def check1(self, csv, board, subject, grade, chapter, model=None):
        feedback = list(self.check1_feedback(csv))
        return {"passed": not feedback, "feedback": feedback, "flags": [],
                "usage": {}, "cost_usd": CHECK1_COST, "model": model}

    def check2(self, csv, board, subject, grade, chapter, model=None):
        self.check2_csvs.append(csv)
        return {"usage": {}, "cost_usd": CHECK2_COST, "model": model,
                **self.check2_result(len(self.check2_csvs))}

    def revision(self, current_prompt, feedback, failed_check, mode, human_feedback=None, model=None):
        self.revision_calls.append({"feedback": list(feedback), "failed_check": failed_check})
        return f"REVISED PROMPT {len(self.revision_calls)}", {}, 0.0

    def doctor(self, **kwargs):
        self.doctor_calls.append(kwargs)
        return {"csv": None, "error": "stub doctor produces no CSV", "usage": {}, "cost_usd": 0.0}

    def rules_doctor(self, **kwargs):
        self.rules_doctor_calls.append(kwargs)
        if not self.rules_doctor_passes:
            return {"csv": None, "error": "stub rules doctor produces no CSV", "usage": {}, "cost_usd": 0.0}
        csv, rows = _csv(kwargs["chapter"], "rules-doctored")
        return {"csv": csv, "rows": rows, "usage": {}, "cost_usd": 0.0}

    @staticmethod
    def judge(**kwargs):
        raise AssertionError("Judge must not run: at most one candidate per run")

    @staticmethod
    def map_extraction(*args, **kwargs):
        raise AssertionError("Map Extraction must not run: the map exists")

    @staticmethod
    def prerequisite(rows, board, subject, grade, chapter, model=None):
        enriched = [{**r, orchestrator.L1_COLUMNS[0]: [], orchestrator.L1_COLUMNS[1]: []} for r in rows]
        return {"rows": enriched, "concept_edges": {}, "skill_edges": {}, "warnings": [],
                "usage": {}, "cost_usd": 0.0}

    # ── Run ──────────────────────────────────────────────────────────────────
    def run(self, **kwargs):
        stubs = {
            (orchestrator, "run_generator"): self.generator,
            (orchestrator, "run_revision"): self.revision,
            (orchestrator, "run_doctor"): self.doctor,
            (orchestrator, "run_rules_doctor"): self.rules_doctor,
            (orchestrator, "run_judge"): self.judge,
            (orchestrator, "run_map_extraction"): self.map_extraction,
            (orchestrator, "run_prerequisite"): self.prerequisite,
            (orchestrator, "run_check2"): self.check2,
            (orchestrator, "concept_skill_map_exists"): lambda *a: True,
            (orchestrator, "load_concept_skill_map"): lambda *a: MAP,
            (orchestrator, "load_prompt"): lambda *a: ("BASE PROMPT", "base_prompt"),
            (orchestrator, "load_rules"): lambda *a: "RULES",
            # eval.run looks these up as module globals of agents.eval.
            (agents.eval, "run_check1"): self.check1,
            (agents.eval, "run_check2"): self.check2,
        }
        originals = {key: getattr(*key) for key in stubs}
        for (module, name), stub in stubs.items():
            setattr(module, name, stub)
        try:
            return orchestrator.run_pipeline(
                BOARD, SUBJECT, GRADE, self.chapter,
                emit=lambda event, data: self.events.append((event, data)), **kwargs,
            )
        finally:
            for (module, name), original in originals.items():
                setattr(module, name, original)

    # ── Readback ─────────────────────────────────────────────────────────────
    def run_dir(self):
        return kb_access._run_stage_dir_path(BOARD, SUBJECT, GRADE, self.chapter, "full")

    def run_json(self):
        with open(os.path.join(self.run_dir(), "run.json"), encoding="utf-8") as f:
            return json.load(f)

    def report_md(self):
        with open(os.path.join(self.run_dir(), "report.md"), encoding="utf-8") as f:
            return f.read()

    def agent_inputs_text(self):
        """Everything the Generator and Revision were given, as one string."""
        parts = []
        for c in self.generator_calls:
            parts += [c["previous_csv"] or "", c["prompt"] or "", *c["feedback"]]
        for c in self.revision_calls:
            parts += c["feedback"]
        return "\n".join(parts)


def _always_missing(_call):
    return {"passed": False, "missing_concepts": list(MAP["concepts"]),
            "missing_skills": list(MAP["skills"]), "matched_concepts": {}, "matched_skills": {},
            "extra_concepts": list(EXTRA["concepts"]), "extra_skills": list(EXTRA["skills"]),
            "feedback": ["2 concept(s) not semantically covered"]}


def _violations(n):
    return [f"R-SK1: skill {i} is not measurable" for i in range(n)]


# ── Test 1 — report: Check 1 fails, fails, passes; Check 2 always has gaps ──────
print("TEST 1: report mode — Check 2 runs once, never gates, never reaches retries")
h = Harness(
    "Chapter91_Report_Pass",
    # Decreasing violation counts so the plateau stop can't fire before attempt 3.
    check1_feedback=lambda csv: {"gen-attempt-1": _violations(3), "gen-attempt-2": _violations(1)}.get(
        next((t for t in ("gen-attempt-1", "gen-attempt-2") if t in csv), ""), []),
    check2_result=_always_missing,
)
result = h.run(check2_mode="report")
assert result["passed"] is True and result["attempts"] == 3, result
assert len(h.check2_csvs) == 1, f"Check 2 ran {len(h.check2_csvs)}x, expected 1"
assert "gen-attempt-3" in h.check2_csvs[0], "Check 2 must run on the final candidate"
assert h.doctor_calls == [], "Doctor must never run in report mode"
assert len(h.rules_doctor_calls) == 2, h.rules_doctor_calls
for call in h.rules_doctor_calls:
    assert call["concept_skill_map"] is None and call["check2"] == {}, "map must be withheld"
assert h.generator_calls[0]["previous_csv"] is None
inputs = h.agent_inputs_text()
for item in MAP_ITEMS:
    assert item not in inputs, f"map item reached Generator/Revision: {item!r}"
assert "[Check 2]" not in inputs
assert all(f.startswith("[Check 1]") for c in h.generator_calls[1:] for f in c["feedback"])
assert [c["failed_check"] for c in h.revision_calls] == ["check1", "check1"], h.revision_calls
print("  ✓ passed on attempt 3 despite Check 2 gaps; Check 2 1x on final CSV; Doctor 0x; "
      "no map item in any Generator/Revision input")

rec = h.run_json()
assert rec["final_status"] == "passed" and rec["failed_check"] is None
assert rec["check2_mode"] == "report"
rep = rec["check2_report"]
assert rep["ran"] is True and rep["candidate_id"] == "cycle3-generated", rep
assert rep["missing_concepts"] == MAP["concepts"] and rep["missing_skills"] == MAP["skills"], rep
assert rep["extra_concepts"] == EXTRA["concepts"] and rep["extra_skills"] == EXTRA["skills"], rep
assert all(a["generator"]["check2"] is None for a in rec["attempts"])
assert abs(rec["total_cost_usd"] - (3 * CHECK1_COST + CHECK2_COST)) < 1e-9, rec["total_cost_usd"]
report = h.report_md()
assert "**Check 2 Mode:** report" in report and "## Check 2 Report" in report
assert all(item in report for item in MAP_ITEMS + EXTRA["concepts"] + EXTRA["skills"])
parsed = kb_access._parse_report_attempts(report)
assert len(parsed) == 3 and all(a["check2_passed"] is None for a in parsed), parsed
assert sum(1 for e, d in h.events if e == "agent_completed" and d["agent"] == "Check 2 (report)") == 1
print("  ✓ run.json: check2_mode=report, missing + extra lists, Check 2 cost in total; "
      "report.md lists both, per-attempt Check 2 parses as not-run")

# ── Test 2 — report: Rules Doctor rescue ──────────────────────────────────────
print("TEST 2: report mode — Check 1 failure → Rules Doctor rescue → Check 2 on doctored CSV")
h = Harness(
    "Chapter92_Report_Rules_Doctor",
    check1_feedback=lambda csv: [] if "rules-doctored" in csv else _violations(2),
    check2_result=_always_missing,
    rules_doctor_passes=True,
)
result = h.run(check2_mode="report")
assert result["passed"] is True and result["attempts"] == 1 and result["source"] == "rules_doctored", result
assert len(h.generator_calls) == 1 and h.revision_calls == [] and h.doctor_calls == []
assert len(h.check2_csvs) == 1 and "rules-doctored" in h.check2_csvs[0]
rec = h.run_json()
assert rec["check2_report"]["candidate_id"] == "cycle1-rules_doctored"
doctor_entry = rec["attempts"][0]["doctors"][0]
assert doctor_entry["kind"] == "rules" and doctor_entry["reeval"]["check2"] is None
print("  ✓ rules-doctored CSV chosen; its re-eval ran Check 1 only; Check 2 1x on it")

# ── Test 3 — report: plateau counts Check 1 only ──────────────────────────────
print("TEST 3: report mode — plateau stop on constant Check 1 violations; escalation")
h = Harness(
    "Chapter93_Report_Plateau",
    check1_feedback=lambda csv: _violations(2),
    check2_result=_always_missing,
)
result = h.run(check2_mode="report")
assert orchestrator.MAX_ATTEMPTS == 6 and orchestrator.MAX_PLATEAU_ROUNDS == 2
assert result["passed"] is False and result["attempts"] == 3, result
assert h.check2_csvs == [], "Check 2 must not run when no candidate passed Check 1"
assert h.doctor_calls == []
rec = h.run_json()
assert rec["final_status"] == "escalated" and rec["failed_check"] == "check1", rec["failed_check"]
assert rec["check2_report"] == {"ran": False, "reason": "no candidate passed Check 1"}
escalated = [d for e, d in h.events if e == "pipeline_escalated"]
assert escalated and escalated[0]["last_feedback"]["check2"] is None
print("  ✓ early stop after 3 of 6 attempts; failed_check=check1; Check 2 0x; "
      "check2_report.ran=false")

# ── Test 4 — gate (default): unchanged behaviour ──────────────────────────────
print("TEST 4: gate mode (default) — Check 2 gates, drives the Doctor, feeds retries")
gaps = {"passed": False, "missing_concepts": MAP["concepts"][:1], "missing_skills": MAP["skills"][:1],
        "matched_concepts": {}, "matched_skills": {}, "extra_concepts": [], "extra_skills": [],
        "feedback": ["1 concept(s) not semantically covered"]}
covered = {"passed": True, "missing_concepts": [], "missing_skills": [],
           "matched_concepts": {c: "Money basics" for c in MAP["concepts"]},
           "matched_skills": {s: "Identify a coin" for s in MAP["skills"]},
           "extra_concepts": [], "extra_skills": [], "feedback": []}
h = Harness(
    "Chapter94_Gate_Default",
    check1_feedback=lambda csv: [],
    check2_result=lambda call: gaps if call == 1 else covered,
)
result = h.run()  # no check2_mode argument: the default
assert result["passed"] is True and result["attempts"] == 2, result
assert len(h.check2_csvs) == 2, "gate mode runs Check 2 on every attempt"
assert len(h.doctor_calls) == 1 and h.doctor_calls[0]["check2"]["missing_concepts"] == MAP["concepts"][:1]
expected_feedback = [
    "[Check 2] 1 concept(s) not covered in the CSV:",
    f"[Check 2]   - {MAP['concepts'][0]}",
    "[Check 2] 1 skill(s) not covered in the CSV:",
    f"[Check 2]   - {MAP['skills'][0]}",
]
assert h.generator_calls[1]["feedback"] == expected_feedback, h.generator_calls[1]["feedback"]
assert h.revision_calls[0]["failed_check"] == "check2"
rec = h.run_json()
assert rec["check2_mode"] == "gate" and rec["check2_report"] is None
assert rec["attempts"][0]["generator"]["check2"]["missing_concepts"] == MAP["concepts"][:1]
report = h.report_md()
assert "Check 2 Mode" not in report and "## Check 2 Report" not in report
assert "**Check 2 — CSM Coverage:**" in report
print("  ✓ Doctor on Check-2-only failure; missing names reach the Generator verbatim; "
      "check2_mode=gate, check2_report=null; report.md unchanged in shape")

print("TEST 4b: gate mode — plateau counts Check 1 + Check 2 (shrinking Check 2 gap keeps going)")
shrinking = lambda call: {**_always_missing(call), "missing_skills": [f"skill {i}" for i in range(10 - call)]}
h = Harness("Chapter95_Gate_No_Plateau", check1_feedback=lambda csv: _violations(2), check2_result=shrinking)
result = h.run(check2_mode="gate")
assert result["passed"] is False and result["attempts"] == 6, result
assert len(h.check2_csvs) == 6
print("  ✓ same constant Check 1 violations run all 6 attempts in gate mode (vs. 3 in report)")

# ── Test 5 — _collect_feedback and argument validation ────────────────────────
print("TEST 5: _collect_feedback and check2_mode validation")
c1 = {"feedback": ["R-SK1: vague skill"]}
assert orchestrator._collect_feedback(c1, None) == ["[Check 1] R-SK1: vague skill"]
assert orchestrator._collect_feedback(c1, gaps) == ["[Check 1] R-SK1: vague skill"] + expected_feedback
try:
    orchestrator.run_pipeline(BOARD, SUBJECT, GRADE, "Chapter96_Bad_Mode", check2_mode="advisory")
    raise AssertionError("an unknown check2_mode must raise")
except ValueError:
    pass
print("  ✓ report-mode feedback is Check 1 only; gate feedback matches the original format; "
      "unknown mode rejected")

print("\nAll tests passed.")
