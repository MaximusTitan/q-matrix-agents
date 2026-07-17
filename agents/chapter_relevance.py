"""
agents/chapter_relevance.py

Chapter Relevance Screen — the pre-filter for Level-2 (cross-chapter) prerequisite
mapping.

Replaces a naive O(chapters^2 x items^2) comparison (or a purely lexical token-overlap
gate, which misses semantically-related-but-differently-worded chapters, e.g. "Newton's
Laws of Motion" vs "Conservation of Momentum") with ONE cheap LLM call per L2 run: given
the target chapter's concepts/skills and every sibling chapter's concepts/skills (titles
only, no full CSV), the LLM flags which siblings are topically plausible enough to deserve
the full (more expensive, more careful) prerequisite-mapping pass in agents/prerequisite_l2.

This call is deliberately biased toward recall — the prompt instructs the LLM to include
a chapter whenever unsure, because a wrongly-included chapter only costs a slightly larger
downstream prompt (which agents/prerequisite_l2 will resolve properly), while a wrongly-
excluded chapter permanently loses any real prerequisite relationship it might contain.

Input:  target_chapter, target_concepts, target_skills, sibling_items (chapter -> {concepts, skills})
Output: dict {"relevant_chapters", "warnings", "usage", "cost_usd"}

Skills used:
    llm — call_llm
"""

import json
import os
from skills.llm import call_llm, add_usage, DEFAULT_MODEL

_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts", "chapter_relevance_prompt.md"
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
        print(f"[chapter_relevance] LLM returned invalid JSON. Error: {e}\nRaw:\n{raw[:500]}")
        return None


def screen(
    target_chapter: str,
    target_concepts: list[str],
    target_skills: list[str],
    sibling_items: dict[str, dict],
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Flag which sibling chapters are plausibly related to the target chapter.

    Args:
        target_chapter:  Target chapter name (for the prompt only).
        target_concepts, target_skills: Target chapter's unique concepts/skills.
        sibling_items:   {chapter_name: {"concepts": [...], "skills": [...]}} for every
                          sibling chapter in the same grade+subject.
        model:           Should be a fast/cheap model — this is a coarse screen, not the
                          actual prerequisite judgment.

    Returns:
        {
          "relevant_chapters": [chapter_name, ...],  # subset of sibling_items keys
          "warnings": [str, ...],
          "usage": {...}, "cost_usd": float,
        }

    Never raises: on any LLM/parse failure, falls back to an EMPTY relevant-chapters list
    (conservative — mirrors agents/prerequisite.py's fail-to-empty pattern) with a warning,
    so a screening failure never silently balloons into a full O(chapters^2) LLM sweep.
    """
    if not sibling_items:
        return {"relevant_chapters": [], "warnings": [], "usage": {}, "cost_usd": 0.0}

    other_chapters_block = "\n\n".join(
        f'CHAPTER: "{chapter}"\n'
        f"  Concepts: {json.dumps(items.get('concepts', []))}\n"
        f"  Skills:   {json.dumps(items.get('skills', []))}"
        for chapter, items in sibling_items.items()
    )

    user_content = f"""TARGET CHAPTER: "{target_chapter}"
  Concepts: {json.dumps(target_concepts)}
  Skills:   {json.dumps(target_skills)}

--- OTHER CHAPTERS ---
{other_chapters_block}"""

    print(f"[chapter_relevance] Screening {len(sibling_items)} sibling chapter(s) "
          f"for relevance to {target_chapter!r}")

    raw, usage, cost = call_llm(SYSTEM_PROMPT, user_content, model=model)
    parsed = _parse_llm_json(raw)

    if not isinstance(parsed, dict):
        return {
            "relevant_chapters": [],
            "warnings": ["Chapter relevance screen returned unusable output — no candidate chapters."],
            "usage": usage,
            "cost_usd": cost,
        }

    valid_chapters = set(sibling_items.keys())
    warnings = []
    relevant = []
    for ch in parsed.get("relevant_chapters", []) or []:
        if ch in valid_chapters:
            if ch not in relevant:
                relevant.append(ch)
        else:
            warnings.append(f"relevant chapter not in sibling set (dropped): {ch!r}")

    print(f"[chapter_relevance] {len(relevant)}/{len(sibling_items)} chapter(s) flagged relevant")

    return {
        "relevant_chapters": relevant,
        "warnings": warnings,
        "usage": usage,
        "cost_usd": cost,
    }
