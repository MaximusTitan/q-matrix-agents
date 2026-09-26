"""
tests/test_jev_offline.py

Offline checks for the evaluation-model (Jev) paths — no network, no cost.
`skills.evaluate.call_evaluate` is replaced with a scripted fake, so these exercise
everything around the model: request batching, the state-size guard, turning answers
into prerequisite edges (including cycle breaking), the L2/L3 screen → pairwise
cascade, the chapter-relevance threshold, judge selection, and the Check 1 / Check 2
output formats their consumers rely on.

Reads rulesets/universal_rules.md from KB_ROOT (read-only), like the other tests.

Run from repo root:
    python tests/test_jev_offline.py
"""

import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills import evaluate
from skills.evaluate import JEV_MODEL

_real_call_evaluate = evaluate.call_evaluate
CALLS = []


def install(answer_fn):
    """Route every evaluation request through answer_fn(state, qid, question) -> answer."""
    def fake(state, questions, model=JEV_MODEL):
        CALLS.append((state, questions))
        answers = {qid: answer_fn(state, qid, q) for qid, q in questions.items()}
        return answers, {"input_tokens": 10 * len(questions), "output_tokens": 0}, 0.001
    CALLS.clear()
    evaluate.call_evaluate = fake


def yes(p):
    return {"type": "boolean", "probability": p}


def pair_of(state, question):
    """(kind, candidate, target) from a judge_pairs question."""
    m = re.search(r'the (concept|skill) "(.+?)"(?: \(from .+?\))? before they can learn', question["instructions"])
    return m.group(1), m.group(2), state[f"target_{m.group(1)}"]


# ── Test 1: evaluate_many batching, id uniqueness, usage/cost merge ──────────
install(lambda s, qid, q: yes(0.5))
n = evaluate.MAX_QUESTIONS_PER_REQUEST * 2 + 22
questions = {f"q{i}": evaluate.boolean(f"Question {i}?") for i in range(n)}
answers, usage, cost = evaluate.evaluate_many([("state", questions)])
assert len(answers) == n
cap = evaluate.MAX_QUESTIONS_PER_REQUEST
assert sorted(len(q) for _, q in CALLS) == [22, cap, cap], [len(q) for _, q in CALLS]  # parallel: any order
assert usage["input_tokens"] == 10 * n and abs(cost - 0.003) < 1e-9
# Long questions are split by the request token budget, not just by count.
install(lambda s, qid, q: yes(0.5))
long_q = {f"l{i}": evaluate.boolean("x" * 3000) for i in range(100)}   # ~1k tokens each
evaluate.evaluate_many([("state", long_q)])
assert len(CALLS) > 1 and all(
    sum(evaluate.estimate_tokens(q) for q in qs.values()) <= evaluate.REQUEST_TOKEN_BUDGET for _, qs in CALLS
)
try:
    evaluate.evaluate_many([("a", {"x": evaluate.boolean("?")}), ("b", {"x": evaluate.boolean("?")})])
    raise AssertionError("duplicate question ids should raise")
except ValueError:
    pass
print("Test 1 passed: evaluate_many batching")


# ── Test 2: state-size guard fires before any network call ───────────────────
try:
    _real_call_evaluate("x" * 200_000, {"q": evaluate.boolean("Is it long?")})
    raise AssertionError("oversized state should raise ValueError")
except ValueError as e:
    assert "too large" in str(e)
assert evaluate.probability({"probability": 0.2}) == 0.2
assert evaluate.probability({"noul": 0.7}) == 0.7   # TypeSafe-native shape
assert evaluate.is_evaluation_model("typesafe-ai/jev")
assert not evaluate.is_evaluation_model("anthropic/claude-sonnet-5")
print("Test 2 passed: size guard and answer readers")


# ── Test 3: L1 edges, cycle breaking, skill→concept derivation ───────────────
from agents.prerequisite import run as run_l1

L1_P = {
    ("skill", "Define speed", "Calculate speed"): 0.95,
    ("skill", "Calculate speed", "Define speed"): 0.85,   # cycle — weaker edge must go
    ("skill", "Calculate speed", "Plot a distance-time graph"): 0.9,
}
install(lambda s, qid, q: yes(L1_P.get(pair_of(s, q), 0.1)))
rows = [
    {"board": "B", "subject": "S", "grade": "G", "chapter": "C", "concept": "Speed", "skill": "Define speed"},
    {"board": "B", "subject": "S", "grade": "G", "chapter": "C", "concept": "Speed", "skill": "Calculate speed"},
    {"board": "B", "subject": "S", "grade": "G", "chapter": "C", "concept": "Graphs", "skill": "Plot a distance-time graph"},
]
res = run_l1(rows, "B", "S", "G", "C", model=JEV_MODEL)
skill_edges = {t: [e["item"] for e in es] for t, es in res["skill_edges"].items()}
assert skill_edges == {"Calculate speed": ["Define speed"], "Plot a distance-time graph": ["Calculate speed"]}, skill_edges
assert any("dropped cyclic prerequisite" in w for w in res["warnings"]), res["warnings"]
assert [e["item"] for e in res["concept_edges"]["Graphs"]] == ["Speed"]   # derived
assert "p=0.95" in res["skill_edges"]["Calculate speed"][0]["reason"]
asked = {pair_of(s, q) for s, qs in CALLS for q in qs.values()}
assert not any(c == t for _, c, t in asked), "self-pairs must not be asked"
assert res["cost_usd"] > 0
print("Test 3 passed: L1 pairwise edges")


# ── Test 4: L1 evaluation failure → empty columns + warning, never raises ────
def boom(*a, **k):
    raise evaluate.EvaluationError("HTTP 402: insufficient funds")
evaluate.call_evaluate = boom
res = run_l1(rows, "B", "S", "G", "C", model=JEV_MODEL)
assert res["skill_edges"] == {} and res["concept_edges"] == {}
assert any("Evaluation model call failed" in w for w in res["warnings"])
assert all(r["prereq_skills_L1_same_chapter"] == [] for r in res["rows"])
print("Test 4 passed: L1 failure falls back to empty columns")


# ── Test 5: L2 screen → pairwise cascade ─────────────────────────────────────
from agents.prerequisite_l2 import run as run_l2


def l2_answer(state, qid, q):
    if q["instructions"].startswith("Could the"):     # stage-A screen
        return yes(0.9 if '"Measure length"' in q["instructions"] else 0.05)
    return yes(0.92 if pair_of(state, q)[1] == "Measure length" else 0.1)


install(l2_answer)
target_rows = [{"board": "B", "subject": "S", "grade": "G", "chapter": "Motion",
                "concept": "Speed", "skill": "Calculate speed"}]
pool = {"Measurement": {"concepts": ["Units"], "skills": ["Measure length", "Read a clock"]}}
res = run_l2(target_rows, pool, {"Measurement": []}, "B", "S", "G", "Motion", model=JEV_MODEL)
assert res["skill_edges"] == {"Calculate speed": [
    {"chapter": "Measurement", "skill": "Measure length", "reason": res["skill_edges"]["Calculate speed"][0]["reason"]}
]}, res["skill_edges"]
pair_candidates = {pair_of(s, q)[1] for s, qs in CALLS for q in qs.values() if not q["instructions"].startswith("Could the")}
assert pair_candidates == {"Measure length"}, f"screened-out items must not reach stage B: {pair_candidates}"
print("Test 5 passed: L2 cascade")


# ── Test 6: L3 carries grade + the foundational-skill criterion ──────────────
from agents.prerequisite_l3 import run as run_l3

install(l2_answer)
pool3 = {"Grade 3": {"Measurement": {"concepts": [], "skills": ["Measure length"]}}}
res = run_l3(target_rows, pool3, {"Grade 3": {"Measurement": []}}, "B", "S", "Grade 4", "Motion", model=JEV_MODEL)
edge = res["skill_edges"]["Calculate speed"][0]
assert (edge["grade"], edge["chapter"], edge["skill"]) == ("Grade 3", "Measurement", "Measure length"), edge
pair_q = [q for _, qs in CALLS for q in qs.values() if not q["instructions"].startswith("Could the")]
assert all("long-consolidated foundational" in q["criteria"]["false"] for q in pair_q)
print("Test 6 passed: L3 cascade")


# ── Test 7: chapter relevance — recall threshold, one sibling per state ──────
from agents.chapter_relevance import screen, RELEVANCE_THRESHOLD

install(lambda s, qid, q: yes(0.35 if s["other_chapter"]["chapter"] == "Measurement" else 0.1))
res = screen("Motion", ["Speed"], ["Calculate speed"],
             {"Measurement": {"concepts": ["Units"], "skills": []},
              "Plants": {"concepts": ["Leaves"], "skills": []}}, model=JEV_MODEL)
assert RELEVANCE_THRESHOLD <= 0.35
assert res["relevant_chapters"] == ["Measurement"], res
assert all(len(qs) == 1 for _, qs in CALLS) and len(CALLS) == 2
evaluate.call_evaluate = boom
res = screen("Motion", ["Speed"], [], {"Plants": {"concepts": [], "skills": []}}, model=JEV_MODEL)
assert res["relevant_chapters"] == [] and "failed" in res["warnings"][0]
print("Test 7 passed: chapter relevance screen")


# ── Test 8: judge — best weighted score wins; ties prefer generated ──────────
from agents.judge import run as run_judge

cands = [
    {"id": "gen-2", "source": "generated", "cycle": 2, "csv": "a"},
    {"id": "doc-1", "source": "doctored",  "cycle": 1, "csv": "b"},
]
install(lambda s, qid, q: {"type": "score", "score": 3.0 if s["candidate_csv"] == "b" else 2.0})
res = run_judge(cands, {"concepts": [], "skills": []}, "", "B", "S", "G", "C", model=JEV_MODEL)
assert res["chosen_id"] == "doc-1", res["chosen_id"]
assert {c["id"]: c["verdict"] for c in res["candidates"]} == {"gen-2": "rejected", "doc-1": "chosen"}
assert res["candidates"][1]["strengths"] and not res["candidates"][1]["concerns"]
install(lambda s, qid, q: {"type": "score", "score": 2.5})
res = run_judge(cands, {"concepts": [], "skills": []}, "", "B", "S", "G", "C", model=JEV_MODEL)
assert res["chosen_id"] == "gen-2" and "tie broken" in res["rationale"]
evaluate.call_evaluate = boom
res = run_judge(cands, {"concepts": [], "skills": []}, "", "B", "S", "G", "C", model=JEV_MODEL)
assert res["chosen_id"] == "gen-2" and res["rationale"].startswith("(fallback)")
print("Test 8 passed: judge")


# ── Test 9: Check 1 — feedback format survives the report round-trip ─────────
from agents.eval import run_check1
from skills.kb_access import _parse_report_attempts
from skills.report_render import _attempt_section

CSV = """board,subject,grade,chapter,concept,skill
B,S,G,C,Motion,Understanding of motion
B,S,G,C,Motion,Describe uniform motion with an example
B,S,G,C,Speed,Calculate speed from distance and time"""


def c1_answer(state, qid, q):
    if state.get("skill") == "Understanding of motion" and "Rule R-SK1 " in q["instructions"]:
        return yes(0.05)
    return yes(0.95)


install(c1_answer)
c1 = run_check1(CSV, "B", "S", "G", "C", model=JEV_MODEL)
assert not c1["passed"]
assert len(c1["feedback"]) == 1, c1["feedback"]
fb = c1["feedback"][0]
assert fb.startswith("R-SK1: Concept 'Motion' skill 'Understanding of motion'") and "\n" not in fb, fb
assert any(f.startswith("R-SK4: Concept 'Speed' has 1 skill(s)") for f in c1["flags"]), c1["flags"]
asked_rules = {re.match(r"Rule (\S+)", q["instructions"]).group(1)
               for _, qs in CALLS for q in qs.values() if q["instructions"].startswith("Rule ")}
assert not any(re.fullmatch(r"R-[SFP]\d+", r) for r in asked_rules), asked_rules
assert {"R-SK1", "R-SK2", "R-C4"} <= asked_rules and "R-C1" not in asked_rules, asked_rules
report = "## Attempt History\n\n" + _attempt_section(
    {"attempt": 1, "input_type": "base", "generator": {"check1": c1, "check2": {"passed": True}}})
assert _parse_report_attempts(report)[0]["check1_feedback"] == c1["feedback"]
print("Test 9 passed: Check 1 feedback format")


# ── Test 10: Check 2 — exact matches skip the model, every other item is asked ─
from skills.diff import diff_full

actual_sorted = sorted(["Speed", "Velocity"])


def c2_answer(state, qid, q):
    if q["type"] == "choice":
        opts = {v: k for k, v in q["criteria"].items()}
        return {"type": "choice", "choice": opts["Speed"],
                "probabilities": {opts["Speed"]: 0.55, opts["Velocity"]: 0.4}}
    return yes(0.8 if "Speed and velocity" in q["instructions"] else 0.1)


install(c2_answer)
csv2 = """board,subject,grade,chapter,concept,skill
B,S,G,C,motion,Define motion
B,S,G,C,Speed,Calculate speed
B,S,G,C,Velocity,Calculate velocity"""
res = diff_full(csv2, {"concepts": ["Motion", "Speed and velocity"], "skills": ["Explain inertia"]}, model=JEV_MODEL)
assert res["matched_concepts"]["Motion"] == ["motion"]
assert sorted(res["matched_concepts"]["Speed and velocity"]) == actual_sorted, res["matched_concepts"]
assert res["missing_concepts"] == [] and res["missing_skills"] == ["Explain inertia"]
assert not res["passed"] and res["feedback"] == ["1 skill(s) not semantically covered: Explain inertia"]
asked = [q["instructions"] for _, qs in CALLS for q in qs.values() if q["type"] == "boolean"]
assert not any('"Motion"' in a for a in asked), "exact matches must not be asked"
print("Test 10 passed: Check 2 coverage")

# ── Test 11: model routing — defaults, eval → eval_coverage fallback, per-check models ─
from orchestrator import AGENT_KEYS, AGENT_DEFAULT_MODELS, _model_for
from agents.eval import run as run_eval

assert set(AGENT_DEFAULT_MODELS) == set(AGENT_KEYS)
assert {k for k, m in AGENT_DEFAULT_MODELS.items() if m == JEV_MODEL} == {"eval_coverage", "judge", "chapter_relevance"}
assert _model_for(None, "eval_coverage") == JEV_MODEL
assert _model_for({"eval": "openai/x"}, "eval_coverage") == "openai/x"       # pre-split callers
assert _model_for({"eval": "openai/x", "eval_coverage": "typesafe-ai/y"}, "eval_coverage") == "typesafe-ai/y"

seen_models = []
def routed(state, questions, model=JEV_MODEL):
    seen_models.append(model)
    return {qid: (yes(0.95) if q["type"] == "boolean" else
                  {"type": "choice", "choice": next(iter(q["criteria"])), "probabilities": {}})
            for qid, q in questions.items()}, {}, 0.0
evaluate.call_evaluate = routed
EVS = ("CBSE", "Environmental Science", "Grade 3", "Chapter09_Staying_Healthy_and_Happy")
csv3 = "board,subject,grade,chapter,concept,skill\n" + "\n".join(
    f"{','.join(EVS)},Personal hygiene habits,{s}" for s in ("Identify habits that keep the body clean", "List steps of washing hands"))
res = run_eval(csv3, *EVS, model="typesafe-ai/rules-model", coverage_model="typesafe-ai/coverage-model")
assert res["check1"]["model"] == "typesafe-ai/rules-model" and res["check2"]["model"] == "typesafe-ai/coverage-model"
assert set(seen_models) == {"typesafe-ai/rules-model", "typesafe-ai/coverage-model"}, set(seen_models)
print("Test 11 passed: model routing")

evaluate.call_evaluate = _real_call_evaluate
print("\nAll evaluation-model offline tests passed.")
