"""
skills/diff.py

Semantic diff of a generated CSV against a concept-skill-map.
Used by the Eval Agent for Check 2.

The concept-skill-map now contains two flat lists:
    concepts: ["Sound", "Propagation of Sound", ...]
    skills:   ["Identify sources of sound", "Calculate speed of sound", ...]

The Eval Agent diffs all CSV concepts against the concepts list,
and all CSV skills against the skills list — independently.

Pure string matching is insufficient — "Identify types of friction" and
"Identify friction types" are semantically the same. The LLM judges coverage.
"""

import json
from skills.csv_utils import parse_csv
from skills.llm import call_llm


SYSTEM_PROMPT = """You are a curriculum coverage auditor.

You will be given:
1. EXPECTED — two flat lists: all concepts and all skills from a chapter map
2. ACTUAL — all concepts and all skills present in a generated CSV

Your job is to identify which expected concepts and skills are NOT adequately
covered in the actual CSV — based on meaning, not exact wording.

Rules:
- Two concepts are equivalent if they refer to the same topic, even if worded differently.
  Example: "Types of friction" and "Friction types" are equivalent.
- A skill is covered if the CSV contains a skill with the same intent, even if phrased differently.
  Example: "Calculate frictional force" and "Compute friction force" are equivalent.
- Do NOT flag minor wording differences as missing — only flag genuinely absent concepts or skills.

Respond ONLY with a valid JSON object. No explanation, no markdown, no preamble.

Format:
{
  "missing_concepts": ["concept as it appears in expected list"],
  "missing_skills": ["skill as it appears in expected list"],
  "reasoning": "one sentence explaining your decision"
}"""


def diff_full(raw_csv: str, concept_skill_map: dict) -> dict:
    """
    Semantically diff a generated CSV against a concept-skill-map.
    Uses the LLM to judge coverage rather than exact string matching.

    Args:
        raw_csv:           Raw CSV string from the Generator Agent.
        concept_skill_map: Parsed concept-skill-map dict from the KB.
                           Expected keys: "concepts" (list), "skills" (list)

    Returns:
        Dict with keys:
            passed           (bool)  — True if no semantic gaps found
            missing_concepts (list)  — Concepts not covered in CSV
            missing_skills   (list)  — Skills not covered in CSV
            feedback         (list)  — Human-readable summary strings
            reasoning        (str)   — LLM's one-line reasoning
    """
    rows = parse_csv(raw_csv)

    # Extract flat lists from the new map structure
    expected_concepts = concept_skill_map.get("concepts", [])
    expected_skills   = concept_skill_map.get("skills",   [])

    # Extract flat lists from CSV
    actual_concepts = list({row["concept"].strip() for row in rows})
    actual_skills   = list({row["skill"].strip()   for row in rows})

    user_content = f"""EXPECTED (from chapter map):
Concepts: {json.dumps(expected_concepts, indent=2)}
Skills:   {json.dumps(expected_skills, indent=2)}

ACTUAL (from generated CSV):
Concepts: {json.dumps(actual_concepts, indent=2)}
Skills:   {json.dumps(actual_skills, indent=2)}"""

    raw_response = call_llm(SYSTEM_PROMPT, user_content)

    # Strip markdown fences if present
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "passed":           False,
            "missing_concepts": [],
            "missing_skills":   [],
            "feedback":         ["Check 2 evaluation failed — LLM returned unparseable output."],
            "reasoning":        "Parse error",
        }

    missing_concepts = result.get("missing_concepts", [])
    missing_skills   = result.get("missing_skills",   [])
    reasoning        = result.get("reasoning",         "")

    feedback = []
    if missing_concepts:
        feedback.append(
            f"{len(missing_concepts)} concept(s) not semantically covered: "
            + ", ".join(missing_concepts)
        )
    if missing_skills:
        feedback.append(
            f"{len(missing_skills)} skill(s) not semantically covered: "
            + ", ".join(missing_skills[:10])
            + (" ..." if len(missing_skills) > 10 else "")
        )

    return {
        "passed":           len(missing_concepts) == 0 and len(missing_skills) == 0,
        "missing_concepts": missing_concepts,
        "missing_skills":   missing_skills,
        "feedback":         feedback,
        "reasoning":        reasoning,
    }