"""
agents/prerequisite.py

Prerequisite Agent — Level 1 (within-chapter).

Runs once after a CSV is confirmed. Given the confirmed chapter CSV, it asks the LLM
which concepts/skills are prerequisites of other concepts/skills WITHIN the same chapter,
then enriches every row with two columns:

    prereq_concepts_L1_same_chapter  — concepts that are prerequisites of the row's concept
    prereq_skills_L1_same_chapter    — skills   that are prerequisites of the row's skill

Each cell is a Python list here; it is JSON-encoded at serialization time by
skills.csv_utils.enriched_csv_to_text.

Direction: an item in a row's prereq column is a prerequisite OF that row's concept/skill,
never the reverse.

Rule enforced deterministically (not by the LLM): if skill A is a prerequisite of skill B,
then concept(A) is a prerequisite of concept(B). Concept edges are the union of this
derivation and any concept edges the LLM returned directly.

Input:  rows (parsed confirmed CSV), board, subject, grade, chapter
Output: dict {"rows", "concept_edges", "skill_edges", "warnings"}

Skills used:
    llm — call_llm
"""

import json
import os
from skills.llm import call_llm
from skills.csv_utils import csv_to_text

# Level-1 column names. Levels 2-4 will add their own (e.g. *_L2_cross_chapter).
L1_CONCEPT_COL = "prereq_concepts_L1_same_chapter"
L1_SKILL_COL   = "prereq_skills_L1_same_chapter"
L1_COLUMNS     = [L1_CONCEPT_COL, L1_SKILL_COL]

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "prerequisite_prompt.md"
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
        print(f"[prerequisite] LLM returned invalid JSON. Error: {e}\nRaw:\n{raw[:500]}")
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


def _extract_edges(parsed: dict, key: str, target_field: str, valid: set) -> dict:
    """
    Turn the LLM's [{<target_field>: T, "prerequisites": [P, ...]}, ...] into
    {T: [P, ...]} keeping only T and P that exist in `valid`. Drops self-edges.
    Returns (edges, warnings).
    """
    edges = {}
    warnings = []
    for entry in parsed.get(key, []) or []:
        if not isinstance(entry, dict):
            continue
        target = entry.get(target_field)
        prereqs = entry.get("prerequisites", []) or []
        if target not in valid:
            if target is not None:
                warnings.append(f"{target_field} not in CSV (dropped): {target!r}")
            continue
        kept = []
        for p in prereqs:
            if p == target:
                continue  # self-edge
            if p not in valid:
                warnings.append(f"prerequisite {target_field} not in CSV (dropped): {p!r}")
                continue
            kept.append(p)
        if kept:
            edges.setdefault(target, [])
            edges[target].extend(kept)
    return {t: _ordered_unique(ps) for t, ps in edges.items()}, warnings


def run(
    rows: list[dict],
    board: str,
    subject: str,
    grade: str,
    chapter: str,
) -> dict:
    """
    Map within-chapter (Level 1) prerequisites and enrich the rows.

    Args:
        rows: Parsed confirmed CSV rows (list of dicts with the base 6 columns).
        board, subject, grade, chapter: Target identifiers.

    Returns:
        {
          "rows": <rows with L1_CONCEPT_COL / L1_SKILL_COL added (list-valued)>,
          "concept_edges": {target_concept: [prereq_concept, ...]},
          "skill_edges":   {target_skill:   [prereq_skill, ...]},
          "warnings": [str, ...],
        }

    Never raises on LLM/parse failure: falls back to empty prerequisite columns so the
    confirmed CSV is still persisted as a checkpoint.
    """
    concepts = _ordered_unique(r.get("concept", "") for r in rows)
    skills   = _ordered_unique(r.get("skill", "")   for r in rows)
    concept_set = set(concepts)
    skill_set   = set(skills)

    print(f"[prerequisite] Mapping L1 within-chapter prerequisites "
          f"({len(concepts)} concepts, {len(skills)} skills)")

    user_content = f"""board: {board}
subject: {subject}
grade: {grade}
chapter: {chapter}

--- CONFIRMED CSV ---
{csv_to_text(rows)}"""

    parsed = None
    for attempt in range(2):
        raw = call_llm(SYSTEM_PROMPT, user_content)
        parsed = _parse_llm_json(raw)
        if isinstance(parsed, dict):
            break
        print(f"[prerequisite] Retrying — invalid output ({attempt + 1}/2)")
        parsed = None

    warnings = []
    if parsed is None:
        warnings.append("LLM output unusable after retry — wrote empty prerequisite columns.")
        concept_edges = {}
        skill_edges = {}
    else:
        skill_edges, w_s = _extract_edges(parsed, "skill_prerequisites", "skill", skill_set)
        concept_edges, w_c = _extract_edges(parsed, "concept_prerequisites", "concept", concept_set)
        warnings.extend(w_c)
        warnings.extend(w_s)

        # ── Deterministic rule: skill A prereq skill B ⇒ concept(A) prereq concept(B) ──
        # A skill may (rarely) belong to more than one concept across rows.
        skill_to_concepts: dict[str, list[str]] = {}
        for r in rows:
            sk = r.get("skill", "")
            cc = r.get("concept", "")
            skill_to_concepts.setdefault(sk, [])
            if cc not in skill_to_concepts[sk]:
                skill_to_concepts[sk].append(cc)

        for target_skill, prereq_skills in skill_edges.items():
            for tc in skill_to_concepts.get(target_skill, []):
                for prereq_skill in prereq_skills:
                    for pc in skill_to_concepts.get(prereq_skill, []):
                        if pc == tc:
                            continue  # same concept — no concept-level edge
                        concept_edges.setdefault(tc, [])
                        if pc not in concept_edges[tc]:
                            concept_edges[tc].append(pc)

    # ── Enrich rows ─────────────────────────────────────────────────────────────
    enriched = []
    for r in rows:
        new_row = dict(r)
        new_row[L1_CONCEPT_COL] = list(concept_edges.get(r.get("concept", ""), []))
        new_row[L1_SKILL_COL]   = list(skill_edges.get(r.get("skill", ""), []))
        enriched.append(new_row)

    concept_edge_count = sum(len(v) for v in concept_edges.values())
    skill_edge_count   = sum(len(v) for v in skill_edges.values())
    print(f"[prerequisite] {skill_edge_count} skill edge(s), "
          f"{concept_edge_count} concept edge(s), {len(warnings)} warning(s)")

    return {
        "rows": enriched,
        "concept_edges": concept_edges,
        "skill_edges": skill_edges,
        "warnings": warnings,
    }
