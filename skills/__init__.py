"""
skills/

Callable skill modules used by Q-Matrix agents.
Each module is a collection of discrete, testable functions.
Agents import only the skills they need — never the whole package.

Skill modules:
    file_io     — Base file operations (read, write, exists, mkdir)
    kb_access   — Knowledge base read/write (prompts, rules, maps, docs)
    pdf_reader  — Extract text from PDF files
    llm         — Anthropic API wrapper (call_llm)
    csv_utils   — Parse and validate curriculum CSVs
    diff        — Semantic diff of CSV vs concept-skill-map (LLM-powered)
    git_sync    — Pull and push the KB repo (orchestrator only)

Usage:
    from skills.kb_access import load_prompt, load_rules
    from skills.llm import call_llm
    from skills.csv_utils import validate_csv_schema
"""