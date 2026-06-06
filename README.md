# q-matrix-agents

> Orchestrator, agents, and skills for the Q-Matrix curriculum generation system — part of [AI Ready School](https://github.com/MaximusTitan/q-matrix-kb) by Intelliana.

This repository is the **code layer** of the Q-Matrix system. It contains the orchestrator, four LLM-powered agents, and the skill modules they use to read from and write to the knowledge base.

---

## What Q-Matrix Does

Given curriculum documentation from any education board, Q-Matrix produces a validated curriculum CSV that maps:

```
Board → Subject → Grade → Chapter → Concept → Skill
```

This is a multi-agent system. Four specialized agents — each with their own skills, prompt, and responsibilities — coordinate through a thin orchestrator to generate, evaluate, and refine curriculum CSVs automatically.

---

## System Architecture

```
orchestrator.py              ← Thin coordinator. No LLM calls. Pure control flow.
│
├── agents/
│   ├── map_extraction.py    ← Extracts concepts + skills from chapter PDFs
│   ├── generator.py         ← Produces curriculum CSV from docs + prompt/rules
│   ├── eval.py              ← Validates CSV against rules and concept-skill-map
│   └── revision.py          ← Rewrites prompts when eval fails
│
└── skills/
    ├── file_io.py           ← read_file, write_file, file_exists, create_directory
    ├── kb_access.py         ← load/save prompts, rules, maps, curriculum docs
    ├── pdf_reader.py        ← extract_text_from_pdf
    ├── llm.py               ← call_llm (Anthropic API wrapper)
    ├── csv_utils.py         ← parse_csv, validate_csv_schema
    ├── diff.py              ← diff_concepts, diff_skills
    └── git_sync.py          ← pull_kb, push_kb
```

---

## Agent Roster

### Map Extraction Agent
Extracts a `concept-skill-map.json` from a chapter PDF. Runs in parallel with the Generator Agent when no map exists for a chapter.

**Input:** `chapter.pdf` path
**Output:** `concept-skill-map.json` written to the KB

### Generator Agent
Produces a curriculum CSV from curriculum documentation and either an existing prompt or universal rules (cold start). Input type is always one or the other — never both.

**Input:** `{ input_type: "prompt" | "rules", prompt | rules, curriculum_docs, board, subject, grade, chapter }`
**Output:** `{ csv }`

### Eval Agent
Runs two sequential checks against the generated CSV. Check 2 only runs after Check 1 passes. The concept-skill-map is always present at this stage.

**Check 1:** Validates against universal rules → structured feedback
**Check 2:** Diffs CSV against concept-skill-map → missing_concepts + missing_skills

**Input:** `{ csv, rules, concept_skill_map }`
**Output:** `{ check1: { passed, feedback }, check2: { passed, feedback, missing_concepts, missing_skills } }`

### Revision Agent
Rewrites the current prompt based on structured eval feedback. Has two modes: subject-level (cold start failure) and grade-level (grade-specific failure). Never sees the CSV directly — only the feedback.

**Input:** `{ current_prompt, feedback, failed_check, mode: "subject" | "grade" }`
**Output:** `{ revised_prompt }`

---

## Orchestration Flow

```
START: Board · Subject · Grade · Chapter
  |
  ├── concept-skill-map missing?
  │     YES → Map Extraction Agent + Generator Agent run in PARALLEL
  │           Orchestrator waits for both
  │     NO  → Generator Agent only
  |
  ├── Prompt resolution (orchestrator decides before calling Generator):
  │     ① grade/prompt.md exists   → input_type: prompt (grade-specific)
  │     ② base_prompt.md exists    → input_type: prompt (subject-level)
  │     ③ neither exists           → input_type: rules  [Cold Start]
  |
  ├── Eval Agent (CSV + concept-skill-map)
  │     Check 1 fail → Revision Agent → Generator → Eval (max 3 attempts)
  │     Check 2 fail → Revision Agent → Generator → Eval (max 3 attempts)
  │     Either exhausted → ESCALATE TO HUMAN
  |
  └── Save logic:
        Cold start + no revision  → save rules as base_prompt.md (subject)
        Cold start + revision     → save revised prompt as base_prompt.md (subject)
        Grade failure + revision  → save revised prompt as grade/prompt.md (grade only)
        Prompt used + no revision → no save needed
```

---

## Cold Start Logic

Base prompts are never manually written. They emerge from the system:

1. No prompt exists → Generator runs with `universal_rules.md`
2. If both checks pass → `universal_rules.md` is saved as `base_prompt.md`
3. If either check fails → Revision Agent adapts it into `base_prompt.md`
4. If `base_prompt.md` works for most grades but fails one specific grade → Revision Agent writes a `grade/prompt.md` for that grade only, leaving `base_prompt.md` unchanged

The only manually authored input is `universal_rules.md`.

---

## Setup

### Prerequisites

- Python 3.10+
- Git with Git LFS
- An Anthropic API key
- A local clone of [q-matrix-kb](https://github.com/MaximusTitan/q-matrix-kb)

### Installation

```bash
git clone https://github.com/MaximusTitan/q-matrix-agents.git
cd q-matrix-agents
pip install -r requirements.txt
```

### Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
KB_ROOT=D:\path\to\your\clone\of\q-matrix-kb
ANTHROPIC_API_KEY=sk-...
```

`KB_ROOT` is the local path to wherever you cloned `q-matrix-kb`. Every person on the team sets their own path here. Never commit `.env`.

---

## Running the Pipeline

**Normal run:**
```bash
python orchestrator.py --board CBSE --subject Science --grade Grade8 --chapter Chapter3
```

**Resume after escalation with human feedback:**
```bash
python orchestrator.py --board CBSE --subject Science --grade Grade8 --chapter Chapter3 --human-feedback "Add pressure as a concept with max 3 skills"
```

**Reject a passed CSV and encode a new rule:**
```bash
python orchestrator.py --reject --board CBSE --subject Science --grade Grade8 --chapter Chapter3 --reason "Max 3 skills per concept"
```

The orchestrator pulls the latest KB state at the start of every run and pushes any new files back to remote on completion.

---

## Human-in-the-Loop

There are two moments where a human intervenes:

**Moment 1 — Eval loop exhausted (3 failed attempts)**

The orchestrator writes an escalation report to `q-matrix-kb/escalations/` and prints a terminal message. The human reads the report, then re-runs with `--human-feedback`. The feedback is injected into the Revision Agent as additional context for one final cycle.

**Moment 2 — Human rejects a passed CSV**

The human runs `--reject` with a reason. The orchestrator writes that reason as a new rule into `rulesets/{board}/{subject}/{grade}/rules.md` and re-runs the pipeline. The Eval Agent will enforce this rule automatically on all future runs for that grade.

The human never edits prompts or agent code directly. All feedback enters the system as text and is encoded into the KB by the orchestrator.

---

## Knowledge Base

This repo never writes to itself. All outputs (prompts, concept-skill-maps, CSVs) go to the KB repo at `KB_ROOT`. See [q-matrix-kb](https://github.com/MaximusTitan/q-matrix-kb) for the KB structure and schema.

---

## Live Dashboard

The pipeline dashboard is a Next.js app in [`dashboard/`](dashboard/) that streams live events from the FastAPI backend via SSE.

```bash
# Terminal 1 — API backend
uvicorn api:app --reload --port 8000

# Terminal 2 — Dashboard UI
cd dashboard && npm run dev
```

Open **http://localhost:3000**. API requests are proxied to FastAPI on port 8000 via Next.js rewrites.

The legacy single-file UI in [`static/index.html`](static/index.html) is deprecated.

---

## Project Status

| Component | Status |
|---|---|
| Agent roster + architecture | ✅ Designed |
| Skill contracts | 🔄 In progress |
| Map Extraction Agent | 🔄 In progress |
| Generator Agent | 🔄 In progress |
| Eval Agent | 🔄 In progress |
| Revision Agent | 🔄 In progress |
| Orchestrator | 🔄 In progress |

---

## Related

- **[q-matrix-kb](https://github.com/MaximusTitan/q-matrix-kb)** — Knowledge base (the data layer)