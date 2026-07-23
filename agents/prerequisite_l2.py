"""
agents/prerequisite_l2.py

Prerequisite Agent — Level 2 (cross-chapter, same grade+subject).

Runs after every chapter in a board/subject/grade has Level-1 (within-chapter)
prerequisites mapped (skills.kb_access.grade_subject_l1_complete). Given one
TARGET chapter's confirmed CSV plus a candidate pool of concepts/skills from OTHER
chapters in the same grade+subject — already narrowed down to just the chapters
agents.chapter_relevance.screen flagged as plausibly related (a cheap, recall-biased
LLM pre-screen, not a lexical/keyword gate — it catches semantically related chapters
that share no vocabulary) — it asks the LLM which candidate items are genuine
cross-chapter prerequisites of the target chapter's concepts/skills, then
enriches every target row with two columns:

    prereq_concepts_L2_cross_chapter — cross-chapter concepts prerequisite to the row's concept
    prereq_skills_L2_cross_chapter   — cross-chapter skills   prerequisite to the row's skill

Each cell is a Python list of {"chapter": ..., "concept"|"skill": ..., "reason": ...} dicts
(a bare string isn't chapter-unique the way it is for L1) — JSON-encoded at serialization
time by skills.csv_utils.enriched_csv_to_text, same as L1.

Direction: an item in a row's prereq column is a prerequisite OF that row's concept/skill,
never the reverse. Edges are recorded only on the target (downstream) chapter's CSV — sibling
chapters are read-only inputs here, never written back to.

Rule enforced deterministically (not by the LLM), mirroring L1: if skill A (in chapter X) is a
prerequisite of skill B (in the target chapter), then concept(A, chapter X) is a prerequisite of
concept(B, target chapter). Concept edges are the union of this derivation and any concept
edges the LLM returned directly.

Input:  target_rows, candidate_pool, sibling_rows_by_chapter, board, subject, grade, chapter
Output: dict {"rows", "concept_edges", "skill_edges", "warnings", "usage", "cost_usd"}

Skills used:
    llm — call_llm
"""

import json
import os
from skills.llm import call_llm, add_usage, DEFAULT_MODEL

L2_CONCEPT_COL = "prereq_concepts_L2_cross_chapter"
L2_SKILL_COL   = "prereq_skills_L2_cross_chapter"
L2_COLUMNS     = [L2_CONCEPT_COL, L2_SKILL_COL]

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "prerequisite_l2_prompt.md"
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
        print(f"[prerequisite_l2] LLM returned invalid JSON. Error: {e}\nRaw:\n{raw[:500]}")
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


def _edge_key(chapter: str, item: str) -> str:
    return f"{chapter}␟{item}"


def _extract_cross_chapter_edges(
    parsed: dict, key: str, target_field: str, target_valid: set, pool_valid: set
) -> tuple[dict, list]:
    """
    Turn the LLM's
        [{<target_field>: T, "prerequisites": [{"chapter": C, <target_field>: P, "reason": R}, ...]}, ...]
    into {T: [{"chapter": C, target_field: P, "reason": R}, ...]}, keeping only T present in
    `target_valid` (the target chapter's own items) and (C, P) pairs present in
    `pool_valid` (the screened candidate pool). Drops anything else, with a warning.
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
            p_chapter = p.get("chapter")
            p_item = p.get(target_field)
            p_reason = p.get("reason", "")
            if _edge_key(p_chapter, p_item) not in pool_valid:
                warnings.append(
                    f"prerequisite {target_field} not in candidate pool (dropped): "
                    f"{p_item!r} (from {p_chapter!r})"
                )
                continue
            k = _edge_key(p_chapter, p_item)
            if k in seen_keys:
                continue
            seen_keys.add(k)
            kept.append({"chapter": p_chapter, target_field: p_item, "reason": p_reason})
        if kept:
            edges.setdefault(target, [])
            edges[target].extend(kept)
    return edges, warnings


def run(
    target_rows: list[dict],
    candidate_pool: dict[str, dict],
    sibling_rows_by_chapter: dict[str, list[dict]],
    board: str,
    subject: str,
    grade: str,
    chapter: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Map cross-chapter (Level 2) prerequisites for `chapter`'s concepts/skills.

    Args:
        target_rows:              Parsed confirmed CSV rows for the target chapter.
        candidate_pool:           {sibling_chapter: {"concepts": [...], "skills": [...]}} —
                                   already narrowed to chapters agents.chapter_relevance.screen
                                   flagged as relevant; this function never sees the full
                                   grade/subject, only these candidates, to keep the LLM
                                   prompt (and cost) bounded.
        sibling_rows_by_chapter:  {sibling_chapter: rows} — full confirmed rows for every
                                   sibling, used only for the deterministic skill->concept
                                   derivation lookup below (not shown to the LLM).
        board, subject, grade, chapter: Target identifiers.

    Returns:
        {
          "rows": <target_rows with L2_CONCEPT_COL / L2_SKILL_COL added (list-valued)>,
          "concept_edges": {target_concept: [{"chapter", "concept", "reason"}, ...]},
          "skill_edges":   {target_skill:   [{"chapter", "skill", "reason"},   ...]},
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
        _edge_key(ch, item) for ch, pool in candidate_pool.items() for item in pool.get("concepts", [])
    }
    pool_skill_valid = {
        _edge_key(ch, item) for ch, pool in candidate_pool.items() for item in pool.get("skills", [])
    }

    total_candidates = sum(
        len(p.get("concepts", [])) + len(p.get("skills", [])) for p in candidate_pool.values()
    )
    print(f"[prerequisite_l2] Mapping L2 cross-chapter prerequisites for {chapter} "
          f"({len(target_concepts)} concepts, {len(target_skills)} skills against "
          f"{total_candidates} candidate(s) from {len(candidate_pool)} chapter(s))")

    if not candidate_pool:
        # No chapter survived the relevance screen — no LLM call needed at all.
        return {
            "rows": [
                {**r, L2_CONCEPT_COL: [], L2_SKILL_COL: []} for r in target_rows
            ],
            "concept_edges": {},
            "skill_edges": {},
            "warnings": ["No sibling chapters survived the chapter-relevance screen."],
            "usage": {},
            "cost_usd": 0.0,
        }

    candidate_lines = []
    for sibling_chapter, pool in candidate_pool.items():
        for c in pool.get("concepts", []):
            candidate_lines.append(f'CONCEPT: "{c}" (from {sibling_chapter})')
        for s in pool.get("skills", []):
            candidate_lines.append(f'SKILL: "{s}" (from {sibling_chapter})')

    user_content = f"""board: {board}
subject: {subject}
grade: {grade}
target chapter: {chapter}

--- TARGET CHAPTER CONCEPTS ---
{json.dumps(target_concepts, indent=2)}

--- TARGET CHAPTER SKILLS ---
{json.dumps(target_skills, indent=2)}

--- CANDIDATE POOL (from other chapters, already screened for relevance) ---
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
        print(f"[prerequisite_l2] Retrying — invalid output ({attempt + 1}/2)")
        parsed = None

    warnings = []
    if parsed is None:
        warnings.append("LLM output unusable after retry — wrote empty L2 prerequisite columns.")
        concept_edges: dict[str, list[dict]] = {}
        skill_edges: dict[str, list[dict]] = {}
    else:
        skill_edges, w_s = _extract_cross_chapter_edges(
            parsed, "skill_prerequisites", "skill", target_skill_set, pool_skill_valid
        )
        concept_edges, w_c = _extract_cross_chapter_edges(
            parsed, "concept_prerequisites", "concept", target_concept_set, pool_concept_valid
        )
        warnings.extend(w_c)
        warnings.extend(w_s)

        # ── Deterministic rule: skill A (chapter X) prereq of skill B (target)
        #    ⇒ concept(A, chapter X) prereq of concept(B, target) ──────────────
        target_skill_to_concepts: dict[str, list[str]] = {}
        for r in target_rows:
            sk, cc = r.get("skill", ""), r.get("concept", "")
            target_skill_to_concepts.setdefault(sk, [])
            if cc not in target_skill_to_concepts[sk]:
                target_skill_to_concepts[sk].append(cc)

        sibling_skill_to_concepts: dict[str, dict[str, list[str]]] = {}
        for sib_chapter, sib_rows in sibling_rows_by_chapter.items():
            mapping: dict[str, list[str]] = {}
            for r in sib_rows:
                sk, cc = r.get("skill", ""), r.get("concept", "")
                mapping.setdefault(sk, [])
                if cc not in mapping[sk]:
                    mapping[sk].append(cc)
            sibling_skill_to_concepts[sib_chapter] = mapping

        for target_skill, prereqs in skill_edges.items():
            for tc in target_skill_to_concepts.get(target_skill, []):
                existing_keys = {
                    (e["chapter"], e["concept"]) for e in concept_edges.get(tc, [])
                }
                for prereq in prereqs:
                    prereq_chapter = prereq["chapter"]
                    prereq_skill = prereq["skill"]
                    for pc in sibling_skill_to_concepts.get(prereq_chapter, {}).get(prereq_skill, []):
                        key = (prereq_chapter, pc)
                        if key in existing_keys:
                            continue
                        concept_edges.setdefault(tc, [])
                        concept_edges[tc].append({
                            "chapter": prereq_chapter,
                            "concept": pc,
                            "reason": f"Derived from skill prerequisite: '{prereq_skill}' "
                                      f"(in {prereq_chapter}) is a prerequisite of a skill "
                                      f"under this concept.",
                        })
                        existing_keys.add(key)

    # ── Enrich target rows ───────────────────────────────────────────────────
    enriched = []
    for r in target_rows:
        new_row = dict(r)
        new_row[L2_CONCEPT_COL] = list(concept_edges.get(r.get("concept", ""), []))
        new_row[L2_SKILL_COL]   = list(skill_edges.get(r.get("skill", ""), []))
        enriched.append(new_row)

    concept_edge_count = sum(len(v) for v in concept_edges.values())
    skill_edge_count   = sum(len(v) for v in skill_edges.values())
    print(f"[prerequisite_l2] {skill_edge_count} skill edge(s), "
          f"{concept_edge_count} concept edge(s), {len(warnings)} warning(s)")

    return {
        "rows": enriched,
        "concept_edges": concept_edges,
        "skill_edges": skill_edges,
        "warnings": warnings,
        "usage": usage_total,
        "cost_usd": cost_total,
    }
