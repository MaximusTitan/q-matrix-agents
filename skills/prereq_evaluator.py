"""
skills/prereq_evaluator.py

Prerequisite mapping on an evaluation model (see skills/evaluate.py), shared by the
L1, L2 and L3 prerequisite agents.

A chat LLM is asked for a whole prerequisite map in one JSON response. An evaluation
model can only answer typed questions, so the same judgment is decomposed:

    screen_candidates — (L2/L3 only) one recall-biased yes/no per candidate item:
                        "could this be a prerequisite of anything in the target chapter?"
    judge_pairs       — one yes/no per (target item, candidate item) of the same kind:
                        "must a student already know <candidate> before <target>?"

The agents turn the resulting probabilities into exactly the JSON shape their chat-LLM
path parses, so validation, the skill→concept derivation and row enrichment are shared.
Edges produced here are still unverified model judgments, like the chat-LLM ones.
"""

from skills import evaluate
from skills.llm import add_usage

# A pair becomes an edge at or above this probability. High on purpose: the chat
# prompts say "when in doubt, leave it out", and most items have no prerequisites.
# Not the default path: calibration on 2026-09-27 (12 confirmed CBSE EVS Grade 3
# chapters, 171 stored skill edges) found Jev very conservative on these questions —
# 4 edges at 0.8, and only 18% of stored edges recovered (37% precision) even at 0.5.
# See orchestrator.AGENT_DEFAULT_MODELS.
EDGE_THRESHOLD = 0.8
# Stage-A screen keeps a candidate at or above this. Low on purpose: a wrongly kept
# candidate only costs a few more pair questions; a wrongly dropped one loses an edge.
SCREEN_THRESHOLD = 0.3

_TRUE = (
    "Genuine, specific learning dependency: the target's own procedure or reasoning step "
    "requires this item's content, so a student cannot learn the target without it."
)
_FALSE = (
    "No specific dependency: the items only share words, a topic, or a broad subject, or "
    "the target can be learned without ever having seen this item."
)
# Level-3 only (prompts/prerequisite_l3_prompt.md): long-consolidated basics from much
# earlier grades are assumed, not mapped.
FOUNDATIONAL_FALSE = (
    " Also false when the item is a long-consolidated foundational skill (generic "
    "numeracy, literacy, basic procedural fluency) that any student at the target grade "
    "already has."
)


def _describe(candidate: dict) -> str:
    source = candidate.get("source")
    return f'"{candidate["text"]}"' + (f" (from {source})" if source else "")


def screen_candidates(
    context: dict,
    target_concepts: list[str],
    target_skills: list[str],
    candidates: list[dict],
    model: str,
) -> tuple[set, dict, float]:
    """
    Stage A: keep candidate items plausibly prerequisite to anything in the target chapter.

    Args:
        context:    Identifiers shown in the state (board/subject/grade/chapter).
        candidates: [{"key", "kind": "concept"|"skill", "text", "source"}, ...]

    Returns:
        (kept_keys, usage, cost_usd)
    """
    state = {**context, "target_chapter_concepts": target_concepts,
             "target_chapter_skills": target_skills}
    questions = {
        f"c{i}": evaluate.boolean(
            f"Could the {c['kind']} {_describe(c)} be something a student must learn before "
            f"at least one of the target chapter's concepts or skills listed in the state?",
            true="Plausibly a specific prerequisite of one or more target items.",
            false="Unrelated to every target item, or related only by shared words or subject.",
        )
        for i, c in enumerate(candidates)
    }
    answers, usage, cost = evaluate.evaluate_many([(state, questions)], model)
    kept = {
        c["key"] for i, c in enumerate(candidates)
        if evaluate.probability(answers[f"c{i}"]) >= SCREEN_THRESHOLD
    }
    return kept, usage, cost


def judge_pairs(
    context: dict,
    kind: str,
    targets: list[str],
    candidates: list[dict],
    model: str,
    extra_false: str = "",
) -> tuple[dict, dict, float]:
    """
    Stage B: one yes/no per (target, candidate) pair of the same `kind`.

    A candidate whose text equals the target (L1 self-pairs) is skipped.

    Returns:
        ({target: [(candidate, probability), ...] sorted by probability desc,
          only pairs ≥ EDGE_THRESHOLD}, usage, cost_usd)
    """
    requests = []
    index: dict[str, tuple[str, dict]] = {}
    for t_i, target in enumerate(targets):
        questions = {}
        for c_i, cand in enumerate(candidates):
            if cand.get("source") is None and cand["text"] == target:
                continue
            qid = f"t{t_i}_c{c_i}"
            index[qid] = (target, cand)
            questions[qid] = evaluate.boolean(
                f"Must a student already understand or be able to do the {kind} "
                f"{_describe(cand)} before they can learn the target {kind} "
                f'"{target}"?',
                true=_TRUE,
                false=_FALSE + extra_false,
            )
        if questions:
            requests.append(({**context, f"target_{kind}": target}, questions))

    answers, usage, cost = evaluate.evaluate_many(requests, model)

    edges: dict[str, list[tuple[dict, float]]] = {}
    for qid, (target, cand) in index.items():
        p = evaluate.probability(answers[qid])
        if p >= EDGE_THRESHOLD:
            edges.setdefault(target, []).append((cand, p))
    for pairs in edges.values():
        pairs.sort(key=lambda pair: -pair[1])
    return edges, usage, cost


def map_cross(
    context: dict,
    target_concepts: list[str],
    target_skills: list[str],
    candidates: list[dict],
    model: str,
    extra_false: str = "",
) -> tuple[dict, dict, float, int]:
    """
    Cross-chapter/cross-grade cascade: screen_candidates, then judge_pairs per kind on
    the survivors.

    Args:
        candidates: [{"key", "kind", "text", "source", "fields": {...}}, ...] — `fields`
                    are copied onto each resulting edge (e.g. chapter, grade).

    Returns:
        ({"concept": edges, "skill": edges}, usage, cost_usd, screened_in_count)
    """
    kept, usage_total, cost_total = screen_candidates(
        context, target_concepts, target_skills, candidates, model
    )
    survivors = [c for c in candidates if c["key"] in kept]
    by_kind = {}
    for kind, targets in (("concept", target_concepts), ("skill", target_skills)):
        pool = [c for c in survivors if c["kind"] == kind]
        if not pool:
            by_kind[kind] = {}
            continue
        edges, usage, cost = judge_pairs(context, kind, targets, pool, model, extra_false)
        usage_total = add_usage(usage_total, usage)
        cost_total += cost
        by_kind[kind] = edges
    return by_kind, usage_total, cost_total, len(survivors)


def break_cycles(edges: dict[str, list[tuple[dict, float]]]) -> list[str]:
    """
    Remove cycles from a within-chapter edge map in place, dropping the lowest-probability
    edge of each cycle found. Returns a warning per dropped edge.

    Edges point prerequisite → target; `edges[target]` lists the target's prerequisites.
    """
    warnings = []
    while True:
        cycle = _find_cycle(edges)
        if not cycle:
            return warnings
        weakest = min(cycle, key=lambda e: e[2])
        prereq, target, p = weakest
        edges[target] = [(c, q) for c, q in edges[target] if c["text"] != prereq]
        if not edges[target]:
            del edges[target]
        warnings.append(
            f"dropped cyclic prerequisite (weakest edge in cycle, p={p:.2f}): "
            f"{prereq!r} → {target!r}"
        )


def _find_cycle(edges) -> list[tuple[str, str, float]] | None:
    """Return one cycle as [(prereq, target, p), ...], or None if the graph is acyclic."""
    # prereq → [(target, p)]
    forward: dict[str, list[tuple[str, float]]] = {}
    for target, pairs in edges.items():
        for cand, p in pairs:
            forward.setdefault(cand["text"], []).append((target, p))

    state: dict[str, int] = {}  # 1 = on stack, 2 = done
    stack: list[tuple[str, str, float]] = []

    def visit(node):
        state[node] = 1
        for nxt, p in forward.get(node, []):
            stack.append((node, nxt, p))
            if state.get(nxt) == 1:
                start = next(i for i, e in enumerate(stack) if e[0] == nxt)
                return stack[start:]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
            stack.pop()
        state[node] = 2
        return None

    for node in sorted(forward):
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def reason(p: float) -> str:
    return f"Evaluation model judged a specific learning dependency (p={p:.2f})."


def cross_parsed(by_kind: dict) -> dict:
    """Format map_cross output as the L2/L3 chat-LLM JSON shape."""
    return {
        f"{kind}_prerequisites": [
            {kind: target, "prerequisites": [
                {**cand["fields"], kind: cand["text"], "reason": reason(p)} for cand, p in pairs
            ]}
            for target, pairs in edges.items()
        ]
        for kind, edges in by_kind.items()
    }
