"""
agents/prerequisite_l3.py

Prerequisite Agent — Level 3 (cross-grade, same subject).

Runs after every chapter in every grade EARLIER than the target's grade (same
board+subject, plus any prerequisite-alias subject — e.g. Science pulls in
Environmental Science's Grades 3-5, since CBSE only introduces Science as a
standalone subject from Grade 6; see skills.kb_access._PREREQ_SUBJECT_ALIASES)
has Level-1 prerequisites mapped (skills.kb_access.subject_prior_grades_l1_complete).
Given one TARGET chapter's confirmed CSV plus a candidate pool of concepts/skills
from chapters in earlier grades of the same subject (or alias subject) — already
narrowed down to just the (grade, chapter)
pairs agents.chapter_relevance.screen flagged as plausibly related, screened once
per earlier grade so each screening call stays the same size as an L2 call
regardless of how many prior grades exist — it asks the LLM which candidate items
are genuine cross-grade prerequisites of the target chapter's concepts/skills,
then enriches every target row with two columns:

    prereq_concepts_L3_prior_grade — prior-grade concepts prerequisite to the row's concept
    prereq_skills_L3_prior_grade   — prior-grade skills   prerequisite to the row's skill

Each cell is a Python list of {"grade": ..., "chapter": ..., "concept"|"skill": ...,
"reason": ...} dicts (grade is needed in addition to chapter since chapter names are
not guaranteed unique across grades) — JSON-encoded at serialization time by
skills.csv_utils.enriched_csv_to_text, same as L1/L2.

Direction: an item in a row's prereq column is a prerequisite OF that row's concept/
skill, never the reverse. Edges are recorded only on the target (downstream)
chapter's CSV — earlier-grade chapters are read-only inputs here, never written back to.

Rule enforced deterministically (not by the LLM), mirroring L1/L2: if skill A (in
grade G, chapter X) is a prerequisite of skill B (in the target chapter), then
concept(A, G, X) is a prerequisite of concept(B, target chapter). Concept edges are
the union of this derivation and any concept edges the LLM returned directly.

Per product decision, this level deliberately does NOT map long-assumed foundational
dependencies (e.g. "uses basic arithmetic") even when technically true — see
prompts/prerequisite_l3_prompt.md for the guardrail. The candidate pool and screen
still consider every earlier grade; only the fine-grained judgment call is tuned to
reject generic/foundational edges.

Input:  target_rows, candidate_pool, sibling_rows_by_grade_chapter, board, subject, grade, chapter
Output: dict {"rows", "concept_edges", "skill_edges", "warnings", "usage", "cost_usd"}

Skills used:
    llm — call_llm
"""

import json
import os
from skills.llm import call_llm, add_usage, DEFAULT_MODEL

L3_CONCEPT_COL = "prereq_concepts_L3_prior_grade"
L3_SKILL_COL   = "prereq_skills_L3_prior_grade"
L3_COLUMNS     = [L3_CONCEPT_COL, L3_SKILL_COL]

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "prerequisite_l3_prompt.md"
)

with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


def _parse_llm_json(raw: str) -> dict | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[prerequisite_l3] LLM returned invalid JSON. Error: {e}\nRaw:\n{raw[:500]}")
        return None


def _ordered_unique(items):
    """Dedupe preserving first-appearance order."""
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _edge_key(grade: str, chapter: str, item: str) -> str:
    return f"{grade}␟{chapter}␟{item}"


def _extract_cross_grade_edges(
    parsed: dict, key: str, target_field: str, target_valid: set, pool_valid: set
) -> tuple[dict, list]:
    """
    Turn the LLM's
        [{<target_field>: T, "prerequisites": [{"grade": G, "chapter": C, <target_field>: P, "reason": R}, ...]}, ...]
    into {T: [{"grade": G, "chapter": C, target_field: P, "reason": R}, ...]}, keeping
    only T present in `target_valid` (the target chapter's own items) and (G, C, P)
    triples present in `pool_valid` (the screened candidate pool). Drops anything
    else, with a warning.
    """
    edges: dict[str, list[dict]] = {}
    warnings = []
    for entry in parsed.get(key, []) or []:
        if not isinstance(entry, dict):
            continue
        target = entry.get(target_field)
        prereqs = entry.get("prerequisites", []) or []
        if target not in target_valid:
            if target is not None:
                warnings.append(f"target {target_field} not in target chapter (dropped): {target!r}")
            continue
        kept = []
        seen_keys = set()
        for p in prereqs:
            if not isinstance(p, dict):
                warnings.append(f"prerequisite for {target!r} was not an object (dropped): {p!r}")
                continue
            p_grade = p.get("grade")
            p_chapter = p.get("chapter")
            p_item = p.get(target_field)
            p_reason = p.get("reason", "")
            if _edge_key(p_grade, p_chapter, p_item) not in pool_valid:
                warnings.append(
                    f"prerequisite {target_field} not in candidate pool (dropped): "
                    f"{p_item!r} (from {p_grade!r}/{p_chapter!r})"
                )
                continue
            k = _edge_key(p_grade, p_chapter, p_item)
            if k in seen_keys:
                continue
            seen_keys.add(k)
            kept.append({"grade": p_grade, "chapter": p_chapter, target_field: p_item, "reason": p_reason})
        if kept:
            edges.setdefault(target, [])
            edges[target].extend(kept)
    return edges, warnings


def run(
    target_rows: list[dict],
    candidate_pool: dict[str, dict[str, dict]],
    sibling_rows_by_grade_chapter: dict[str, dict[str, list[dict]]],
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Map cross-grade (Level 3) prerequisites for `chapter`'s concepts/skills.

    Args:
        target_rows:      Parsed confirmed CSV rows for the target chapter.
        candidate_pool:    {earlier_grade: {chapter: {"concepts": [...], "skills": [...]}}} —
                           already narrowed to (grade, chapter) pairs
                           agents.chapter_relevance.screen flagged as relevant (screened
                           once per earlier grade); this function never sees the full
                           multi-grade history, only these candidates, to keep the LLM
                           prompt (and cost) bounded.
        sibling_rows_by_grade_chapter: {earlier_grade: {chapter: rows}} — full confirmed
                           rows for every earlier-grade chapter, used only for the
                           deterministic skill->concept derivation lookup below (not
                           shown to the LLM).
        board, subject, grade, chapter: Target identifiers.

    Returns:
        {
          "rows": <target_rows with L3_CONCEPT_COL / L3_SKILL_COL added (list-valued)>,
          "concept_edges": {target_concept: [{"grade", "chapter", "concept", "reason"}, ...]},
          "skill_edges":   {target_skill:   [{"grade", "chapter", "skill", "reason"},   ...]},
          "warnings": [str, ...],
          "usage": {...}, "cost_usd": float,
        }

    Never raises on LLM/parse failure: falls back to empty prerequisite columns so the
    confirmed CSV is still persisted as a checkpoint.
    """
    target_concepts = _ordered_unique(r.get("concept", "") for r in target_rows)
    target_skills   = _ordered_unique(r.get("skill", "")   for r in target_rows)
    target_concept_set = set(target_concepts)
    target_skill_set   = set(target_skills)

    pool_concept_valid = {
        _edge_key(g, ch, item)
        for g, chapters in candidate_pool.items()
        for ch, pool in chapters.items()
        for item in pool.get("concepts", [])
    }
    pool_skill_valid = {
        _edge_key(g, ch, item)
        for g, chapters in candidate_pool.items()
        for ch, pool in chapters.items()
        for item in pool.get("skills", [])
    }

    total_candidates = sum(
        len(pool.get("concepts", [])) + len(pool.get("skills", []))
        for chapters in candidate_pool.values()
        for pool in chapters.values()
    )
    candidate_chapter_count = sum(len(chapters) for chapters in candidate_pool.values())
    print(f"[prerequisite_l3] Mapping L3 cross-grade prerequisites for {chapter} "
          f"({len(target_concepts)} concepts, {len(target_skills)} skills against "
          f"{total_candidates} candidate(s) from {candidate_chapter_count} chapter(s) "
          f"across {len(candidate_pool)} earlier grade(s))")

    if not candidate_pool or candidate_chapter_count == 0:
        # No chapter survived the relevance screen in any earlier grade — no LLM
        # call needed at all.
        return {
            "rows": [
                {**r, L3_CONCEPT_COL: [], L3_SKILL_COL: []} for r in target_rows
            ],
            "concept_edges": {},
            "skill_edges": {},
            "warnings": ["No chapter in any earlier grade survived the chapter-relevance screen."],
            "usage": {},
            "cost_usd": 0.0,
        }

    candidate_lines = []
    for sibling_grade, chapters in candidate_pool.items():
        for sibling_chapter, pool in chapters.items():
            for c in pool.get("concepts", []):
                candidate_lines.append(f'CONCEPT: "{c}" (from {sibling_grade} / {sibling_chapter})')
            for s in pool.get("skills", []):
                candidate_lines.append(f'SKILL: "{s}" (from {sibling_grade} / {sibling_chapter})')

    user_content = f"""board: {board}
subject: {subject}
target grade: {grade}
target chapter: {chapter}

--- TARGET CHAPTER CONCEPTS ---
{json.dumps(target_concepts, indent=2)}

--- TARGET CHAPTER SKILLS ---
{json.dumps(target_skills, indent=2)}

--- CANDIDATE POOL (from earlier grades, already screened for relevance) ---
{chr(10).join(candidate_lines)}"""

    parsed = None
    usage_total = {}
    cost_total = 0.0
    for attempt in range(2):
        raw, usage, cost = call_llm(SYSTEM_PROMPT, user_content, model=model)
        usage_total = add_usage(usage_total, usage)
        cost_total += cost
        parsed = _parse_llm_json(raw)
        if isinstance(parsed, dict):
            break
        print(f"[prerequisite_l3] Retrying — invalid output ({attempt + 1}/2)")
        parsed = None

    warnings = []
    if parsed is None:
        warnings.append("LLM output unusable after retry — wrote empty L3 prerequisite columns.")
        concept_edges: dict[str, list[dict]] = {}
        skill_edges: dict[str, list[dict]] = {}
    else:
        skill_edges, w_s = _extract_cross_grade_edges(
            parsed, "skill_prerequisites", "skill", target_skill_set, pool_skill_valid
        )
        concept_edges, w_c = _extract_cross_grade_edges(
            parsed, "concept_prerequisites", "concept", target_concept_set, pool_concept_valid
        )
        warnings.extend(w_c)
        warnings.extend(w_s)

        # ── Deterministic rule: skill A (grade G, chapter X) prereq of skill B
        #    (target) ⇒ concept(A, G, X) prereq of concept(B, target) ──────────
        target_skill_to_concepts: dict[str, list[str]] = {}
        for r in target_rows:
            sk, cc = r.get("skill", ""), r.get("concept", "")
            target_skill_to_concepts.setdefault(sk, [])
            if cc not in target_skill_to_concepts[sk]:
                target_skill_to_concepts[sk].append(cc)

        sibling_skill_to_concepts: dict[tuple[str, str], dict[str, list[str]]] = {}
        for sib_grade, chapters in sibling_rows_by_grade_chapter.items():
            for sib_chapter, sib_rows in chapters.items():
                mapping: dict[str, list[str]] = {}
                for r in sib_rows:
                    sk, cc = r.get("skill", ""), r.get("concept", "")
                    mapping.setdefault(sk, [])
                    if cc not in mapping[sk]:
                        mapping[sk].append(cc)
                sibling_skill_to_concepts[(sib_grade, sib_chapter)] = mapping

        for target_skill, prereqs in skill_edges.items():
            for tc in target_skill_to_concepts.get(target_skill, []):
                existing_keys = {
                    (e["grade"], e["chapter"], e["concept"]) for e in concept_edges.get(tc, [])
                }
                for prereq in prereqs:
                    prereq_grade = prereq["grade"]
                    prereq_chapter = prereq["chapter"]
                    prereq_skill = prereq["skill"]
                    for pc in sibling_skill_to_concepts.get((prereq_grade, prereq_chapter), {}).get(prereq_skill, []):
                        key = (prereq_grade, prereq_chapter, pc)
                        if key in existing_keys:
                            continue
                        concept_edges.setdefault(tc, [])
                        concept_edges[tc].append({
                            "grade": prereq_grade,
                            "chapter": prereq_chapter,
                            "concept": pc,
                            "reason": f"Derived from skill prerequisite: '{prereq_skill}' "
                                      f"(in {prereq_grade}/{prereq_chapter}) is a prerequisite of a "
                                      f"skill under this concept.",
                        })
                        existing_keys.add(key)

    # ── Enrich target rows ───────────────────────────────────────────────────
    enriched = []
    for r in target_rows:
        new_row = dict(r)
        new_row[L3_CONCEPT_COL] = list(concept_edges.get(r.get("concept", ""), []))
        new_row[L3_SKILL_COL]   = list(skill_edges.get(r.get("skill", ""), []))
        enriched.append(new_row)

    concept_edge_count = sum(len(v) for v in concept_edges.values())
    skill_edge_count   = sum(len(v) for v in skill_edges.values())
    print(f"[prerequisite_l3] {skill_edge_count} skill edge(s), "
          f"{concept_edge_count} concept edge(s), {len(warnings)} warning(s)")

    return {
        "rows": enriched,
        "concept_edges": concept_edges,
        "skill_edges": skill_edges,
        "warnings": warnings,
        "usage": usage_total,
        "cost_usd": cost_total,
    }
