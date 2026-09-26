"""
agents/eval.py

Eval Agent.
Runs Check 1 and Check 2 in PARALLEL — both always run regardless of outcome.

Check 1 — Universal rules compliance (LLM-judged)
Check 2 — Concept-skill-map coverage (LLM-judged via diff.py)

Both checks are independent. Running them simultaneously means the Revision
Agent always receives full feedback from both checks in a single pass.

Input:  csv (str), board, subject, grade, chapter
Output: dict with check1 and check2 results — always both present

With an evaluation model (skills.evaluate.is_evaluation_model), Check 1 asks one yes/no
question per (rule, row) or (rule, concept) instead of one structured call, and builds
the same one-line "R-XX: ..." feedback strings from the answers.

Skills used:
    kb_access  — load_rules, load_rules_structured, load_concept_skill_map
    llm        — call_llm_structured (Check 1, chat models)
    evaluate   — evaluate_many (Check 1, evaluation models)
    diff       — diff_full (Check 2)
"""

import csv as csv_module
import os
import re
from concurrent.futures import ThreadPoolExecutor

from skills.kb_access import load_rules, load_rules_structured, load_concept_skill_map
from skills.llm import call_llm_structured, add_usage, DEFAULT_MODEL
from skills.csv_utils import RULES_CHECK_TOOL, parse_csv, structural_check
from skills.diff import diff_full
from skills import evaluate

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "eval_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


# ── Check 1 on an evaluation model ────────────────────────────────────────────
# Where each content rule is asked (rule text comes from universal_rules.md itself).
_ROW_RULES          = ("R-SK1", "R-SK2", "R-SK3", "R-SK5")
_CONCEPT_RULES      = ("R-C2", "R-C4", "R-SK6")
_CONCEPT_FLAG_RULES = ("R-SK7",)
# Never asked of the evaluator:
#   R-S*/R-F*        structural/format — verified in code by structural_check
#   R-P*             prerequisite rules — not judged by the chat-LLM Check 1 either
#   R-C1/R-C5/R-CV1/R-CV2/R-CV4  need the source document — Check 2 owns coverage
#   R-C3/R-SK4       counts — done in code below (evaluation models don't count reliably)
#   R-CV3            compares against other chapters, which Check 1 never sees
_NOT_ASKED = {"R-C1", "R-C3", "R-C5", "R-CV1", "R-CV2", "R-CV3", "R-CV4", "R-SK4"}
_NOT_ASKED_PATTERN = re.compile(r"R-[SFP]\d+")
# A rule is violated when p(satisfied) falls below this. Low on purpose: Check 1
# reports only violations it can point to, not borderline cases.
# Not the default path: calibration on 2026-09-27 (63 escalated attempts with Sonnet 5
# verdicts + 12 confirmed CBSE EVS Grade 3 chapters) found no threshold that separates
# Sonnet-passed from Sonnet-failed CSVs — at 0.3, 37% false fails and 39% of failures
# caught; R-SK6 (duplicate skills) was never flagged. See orchestrator.AGENT_DEFAULT_MODELS.
RULE_PASS_THRESHOLD = 0.3


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _rules_check_with_evaluator(csv, board, subject, grade, chapter, model):
    """
    Returns (feedback, flags, usage, cost_usd). Feedback/flag strings keep the chat-LLM
    convention — one line, starting with the rule ID, naming the concept/skill — because
    Revision, Rules Doctor and the report parser consume them verbatim.
    """
    rules = load_rules_structured(board, subject, grade)
    universal = rules["universal"]
    try:
        rows = parse_csv(csv)
    except (ValueError, csv_module.Error):
        return [], [], {}, 0.0  # unparseable CSV is already an R-S1 structural violation

    concepts: dict[str, list[str]] = {}
    for r in rows:
        concepts.setdefault(r.get("concept", "").strip(), []).append(r.get("skill", "").strip())

    feedback, flags = [], []

    # Counts, in code.
    if "R-C3" in universal and len(concepts) < 2:
        feedback.append(f"R-C3: only {len(concepts)} distinct concept(s) in the chapter; at least 2 are required")
    if "R-SK4" in universal:
        for c, skills in concepts.items():
            if len(skills) == 1 or len(skills) >= 8:
                flags.append(f"R-SK4: Concept '{c}' has {len(skills)} skill(s) — flagged for human review (1 or 8+)")

    row_rules = [r for r in _ROW_RULES if r in universal]
    for rid in universal:
        known = rid in _NOT_ASKED or _NOT_ASKED_PATTERN.fullmatch(rid) or rid in (
            _ROW_RULES + _CONCEPT_RULES + _CONCEPT_FLAG_RULES
        )
        if not known:
            print(f"[eval] Rule {rid} has no Check 1 scope — asking it per row")
            row_rules.append(rid)

    def rule_question(rid, subject_text):
        rule = universal[rid]
        return evaluate.boolean(
            f"Rule {rid} — {rule['title']}: {rule['text']}\n\nDoes {subject_text} satisfy this rule?",
            true="It satisfies the rule.",
            false="It clearly violates the rule.",
        )

    ids = {"board": board, "subject": subject, "grade": grade, "chapter": chapter}
    requests, meaning = [], {}
    for i, r in enumerate(rows):
        c, sk = r.get("concept", "").strip(), r.get("skill", "").strip()
        questions = {}
        for k, rid in enumerate(row_rules):
            qid = f"r{i}_{k}"
            questions[qid] = rule_question(rid, "the `skill`, listed under `concept`,")
            meaning[qid] = ("feedback", f"{rid}: Concept '{c}' skill '{sk}' — does not satisfy "
                                        f"\"{universal[rid]['title']}\"")
        if questions:
            requests.append(({**ids, "concept": c, "skill": sk}, questions))

    concept_rules = [(rid, "feedback") for rid in _CONCEPT_RULES if rid in universal] + \
                    [(rid, "flag") for rid in _CONCEPT_FLAG_RULES if rid in universal]
    all_concepts = list(concepts)
    for j, (c, skills) in enumerate(concepts.items()):
        questions = {}
        for k, (rid, kind) in enumerate(concept_rules):
            qid = f"c{j}_{k}"
            questions[qid] = rule_question(rid, "the `concept`, together with its `skills_under_concept`,")
            meaning[qid] = (kind, f"{rid}: Concept '{c}' — does not satisfy \"{universal[rid]['title']}\"")
        if questions:
            requests.append((
                {**ids, "concept": c, "skills_under_concept": skills,
                 "all_concepts_in_chapter": all_concepts},
                questions,
            ))

    # Grade rules come from human rejections (--reject) and carry no ID or scope, so
    # each is asked once against the whole CSV.
    if rules["grade"]:
        state = {**ids, "csv_rows": [{"concept": r.get("concept", ""), "skill": r.get("skill", "")}
                                     for r in rows]}
        questions = {}
        for n, bullet in enumerate(rules["grade"], start=1):
            qid = f"g{n}"
            questions[qid] = evaluate.boolean(
                f"Grade-specific rule (from a human reviewer): {bullet}\n\n"
                f"Does the curriculum in `csv_rows` comply with this rule?",
                true="It complies with the rule.",
                false="It clearly does not comply with the rule.",
            )
            meaning[qid] = ("feedback", f"R-G{n}: CSV does not comply with grade rule \"{bullet}\"")
        requests.append((state, questions))

    answers, usage, cost = evaluate.evaluate_many(requests, model)
    for qid, (kind, message) in meaning.items():
        p = evaluate.probability(answers[qid])
        if p < RULE_PASS_THRESHOLD:
            (feedback if kind == "feedback" else flags).append(_one_line(f"{message} (p={p:.2f})"))
    return feedback, flags, usage, cost


def _rules_check_with_llm(csv, board, subject, grade, chapter, model):
    """One structured chat-LLM call. Returns (feedback, flags, usage, cost_usd)."""
    rules = load_rules(board, subject, grade)

    user_content = f"""CHECK: 1

INPUT IDENTIFIERS (already verified in code — do NOT re-evaluate board/subject/grade/chapter):
board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- RULES ---
{rules}

--- GENERATED CSV ---
{csv}"""

    result, usage, cost_usd = call_llm_structured(SYSTEM_PROMPT, user_content, RULES_CHECK_TOOL, model=model)

    llm_feedback = result.get("feedback", []) or []
    flags        = result.get("flags", []) or []
    return llm_feedback, flags, usage, cost_usd


def run_check1(
    csv: str, board: str, subject: str, grade: str, chapter: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Check 1 — Universal rules compliance.

    Structural + identifier-fidelity rules (R-S*, R-F2) are verified deterministically
    in code (``structural_check``) — the LLM is never given the input identifiers, so
    asking it to judge them produced false "cannot verify" failures. The LLM judges only
    content-quality rules, and the flag-only rules (R-SK4/R-SK7/R-CV3) are returned as
    non-blocking ``flags`` rather than failures, per universal_rules Appendix A.

    ``passed`` is derived from BLOCKING items only: a run passes Check 1 when there are
    no structural violations and the LLM reports no content violations. Advisory flags
    never block.

    Returns:
        Dict with keys: passed (bool), feedback (list), flags (list)
    """
    print(f"[eval] Running Check 1 — universal rules")

    # Mechanical rules first — exact, free, and impossible for the LLM to hedge on.
    structural_violations = structural_check(csv, board, subject, grade, chapter)

    if evaluate.is_evaluation_model(model):
        llm_feedback, flags, usage, cost_usd = _rules_check_with_evaluator(
            csv, board, subject, grade, chapter, model
        )
    else:
        llm_feedback, flags, usage, cost_usd = _rules_check_with_llm(
            csv, board, subject, grade, chapter, model
        )

    # Blocking = code-verified structural violations + LLM content violations. `passed`
    # is derived from presence of blocking items, not the model's boolean — a cautious
    # model that sets passed=false while listing only flags no longer fails the run.
    feedback = structural_violations + llm_feedback
    passed   = not feedback

    print(f"[eval] Check 1: {'PASSED' if passed else 'FAILED'} "
          f"({len(feedback)} blocking, {len(flags)} flag(s))")
    return {
        "passed": passed, "feedback": feedback, "flags": flags,
        "usage": usage, "cost_usd": cost_usd, "model": model,
    }


def run_check2(
    csv: str, board: str, subject: str, grade: str, chapter: str, model: str = DEFAULT_MODEL
) -> dict:
    """
    Check 2 — Concept-skill-map coverage.

    Returns:
        Dict with keys: passed (bool), missing_concepts (list),
                        missing_skills (list), feedback (list)
    """
    print(f"[eval] Running Check 2 — CSM coverage")
    concept_skill_map = load_concept_skill_map(board, subject, grade, chapter)
    result = diff_full(csv, concept_skill_map, model=model)

    print(f"[eval] Check 2: {'PASSED' if result['passed'] else 'FAILED'} "
          f"({len(result['missing_concepts'])} missing concepts, "
          f"{len(result['missing_skills'])} missing skills)")
    return result


def run(
    csv: str,
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    model: str = DEFAULT_MODEL,
    coverage_model: str | None = None,
) -> dict:
    """
    Run Check 1 and Check 2 in parallel.
    Both checks always run — neither is skipped based on the other's outcome.

    `model` runs Check 1; `coverage_model` runs Check 2 (defaults to `model`).

    Returns:
        Dict with keys:
            check1 (dict) — always present
            check2 (dict) — always present
            passed (bool) — True only if both checks pass
    """
    print(f"[eval] Starting: {board}/{subject}/{grade}/{chapter}")
    print(f"[eval] Running Check 1 and Check 2 in parallel...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_c1 = executor.submit(run_check1, csv, board, subject, grade, chapter, model)
        future_c2 = executor.submit(run_check2, csv, board, subject, grade, chapter,
                                    coverage_model or model)

        check1 = future_c1.result()
        check2 = future_c2.result()

    passed = check1["passed"] and check2["passed"]
    print(f"[eval] Overall: {'✓ PASSED' if passed else '✗ FAILED'}")

    usage = add_usage(check1.get("usage") or {}, check2.get("usage") or {})
    cost_total = check1.get("cost_usd", 0.0) + check2.get("cost_usd", 0.0)
    return {
        "check1": check1,
        "check2": check2,
        "passed": passed,
        "usage": usage,
        "cost_usd": cost_total,
        "model": model,
    }