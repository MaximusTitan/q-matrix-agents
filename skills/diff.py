"""
skills/diff.py

Semantic diff of a generated CSV against a concept-skill-map.
Used by the Eval Agent for Check 2.

Pure string matching is insufficient — "Identify types of friction" and
"Identify friction types" are the same concept expressed differently.
The LLM judges semantic coverage, not exact string equality.
"""

import json
from skills.csv_utils import parse_csv
from skills.llm import call_llm


SYSTEM_PROMPT = """You are a curriculum coverage auditor.

You will be given:
1. A list of EXPECTED concepts and skills from a chapter map
2. A list of ACTUAL concepts and skills from a generated CSV

Your job is to identify which expected concepts and skills are NOT adequately
covered in the actual CSV — based on meaning, not exact wording.

Rules:
- Two concepts are equivalent if they refer to the same topic, even if worded differently.
  Example: "Types of friction" and "Friction types" are equivalent.
- A skill is covered if the CSV contains a skill with the same intent, even if phrased differently.
  Example: "Calculate frictional force" and "Compute friction force" are equivalent.
- Do NOT flag minor wording differences as missing — only flag genuinely absent concepts or skills.
- A concept is covered even if only some of its skills appear, but flag the specific missing skills.

Respond ONLY with a valid JSON object. No explanation, no markdown, no preamble.

Format:
{
  "missing_concepts": ["concept name as it appears in expected list"],
  "missing_skills": ["skill text as it appears in expected list"],
  "reasoning": "one sentence explaining your decision"
}"""


def diff_full(raw_csv: str, concept_skill_map: dict) -> dict:
    """
    Semantically diff a generated CSV against a concept-skill-map.
    Uses the LLM to judge coverage rather than exact string matching.

    Args:
        raw_csv:           Raw CSV string from the Generator Agent.
        concept_skill_map: Parsed concept-skill-map dict from the KB.

    Returns:
        Dict with keys:
            passed           (bool)  — True if no semantic gaps found
            missing_concepts (list)  — Concepts not covered in CSV
            missing_skills   (list)  — Skills not covered in CSV
            feedback         (list)  — Human-readable summary strings
            reasoning        (str)   — LLM's one-line reasoning
    """
    rows = parse_csv(raw_csv)

    # Build compact representations for the LLM
    expected = concept_skill_map.get("concepts", [])

    actual_concepts = list({row["concept"].strip() for row in rows})
    actual_skills   = list({row["skill"].strip()   for row in rows})

    user_content = f"""EXPECTED (from chapter map):
{json.dumps(expected, indent=2)}

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
        # Fallback — treat as total failure if LLM output is unparseable
        return {
            "passed":           False,
            "missing_concepts": [],
            "missing_skills":   [],
            "feedback":         ["Check 2 evaluation failed — LLM returned unparseable output."],
            "reasoning":        "Parse error",
        }

    missing_concepts = result.get("missing_concepts", [])
    missing_skills   = result.get("missing_skills", [])
    reasoning        = result.get("reasoning", "")

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
