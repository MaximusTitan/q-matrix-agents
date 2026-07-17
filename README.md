# q-matrix-agents

> Orchestrator, agents, and skills for the Q-Matrix curriculum generation system — part of [AI Ready School](https://github.com/MaximusTitan/q-matrix-kb) by Intelliana.

This repository is the **code layer** of the Q-Matrix system. It contains the orchestrator, ten LLM-powered agents, a FastAPI backend, a live Next.js dashboard, and the skill modules that read from and write to the knowledge base.

> For the full system design (control-flow diagrams, KB layout, model routing, runtime topology) see **[ARCHITECTURE.md](ARCHITECTURE.md)** — this README is a quick-start overview.

---

## What Q-Matrix Does

Given curriculum documentation from any education board, Q-Matrix produces a validated curriculum CSV that maps:

```
Board → Subject → Grade → Chapter → Concept → Skill   (+ L1 and L2 prerequisite columns)
```

This is a multi-agent system. Specialized agents — each with their own skills, prompt, and responsibilities — coordinate through a thin orchestrator to generate, evaluate, repair, and enrich curriculum CSVs automatically, with a human in the loop only on escalation.

---

## System Architecture

```
orchestrator.py              ← Thin coordinator. No LLM calls. Pure control flow.
api.py                       ← FastAPI backend (:8000) — SSE streaming, analytics
│
├── agents/                  ← 10 single-responsibility LLM agents (see roster below)
│
├── skills/
│   ├── file_io.py           ← read_file, write_file, file_exists, create_directory
│   ├── kb_access.py         ← sole owner of the KB on-disk layout; load/save everything
│   ├── pdf_reader.py        ← extract_text_from_pdf
│   ├── llm.py               ← call_llm / call_llm_structured (Vercel AI Gateway wrapper)
│   ├── csv_utils.py         ← parse_csv, validate_csv_schema, tool-call JSON schemas
│   ├── diff.py              ← semantic coverage diff (CSV vs. concept-skill-map)
│   ├── git_sync.py          ← pull_kb, push_kb
│   ├── run_record.py        ← builds the structured run.json (schema v3)
│   ├── report_render.py     ← renders human-readable report.md
│   └── model_stats.py       ← aggregates run records for the analytics dashboard
│
└── dashboard/                ← Next.js live console + analytics (:3000)
```

---

## Agent Roster

Ten agents, each loading its system prompt from `prompts/<name>_prompt.md`. Full responsibilities, I/O shapes, and the flowchart of how they connect are in **[ARCHITECTURE.md §4](ARCHITECTURE.md#4-the-agent-roster)**.

| Agent | Responsibility |
|---|---|
| **Map Extraction** | Extract concepts + skills from a chapter PDF → `concept-skill-map.json` |
| **Generator** | Produce curriculum CSV rows from docs + prompt/rules (cold start or existing prompt) |
| **Eval** | Check 1 (universal rules) + Check 2 (concept-skill-map coverage), run in parallel |
| **Revision** | Rewrite the generation prompt so a reported failure won't recur (subject or grade mode) |
| **Doctor** | Surgically patch a CSV that passed Check 1 but failed Check 2 |
| **Rules Doctor** | Mirror of Doctor — fix Check 1 rule violations without losing Check 2 coverage |
| **Judge** | Choose the single best CSV when ≥2 candidates already pass both checks |
| **Prerequisites (L1)** | Map within-chapter concept→concept and skill→skill prerequisite edges |
| **Chapter Relevance** | Cheap, recall-biased pre-filter that flags sibling chapters worth the full L2 pass |
| **Prerequisite (L2)** | Map cross-chapter (same grade+subject) prerequisite edges, using the relevance-screened candidate pool |

---

## Orchestration Flow

The core generate → evaluate → repair/revise loop (bounded, adaptive). Cross-chapter (L2) prerequisite mapping runs separately, after every chapter in a grade+subject has L1 prerequisites. See **[ARCHITECTURE.md §5](ARCHITECTURE.md#5-the-pipeline-control-flow)** for the full flowchart including Doctor/Judge/escalation paths.

```
START: Board · Subject · Grade · Chapter
  |
  ├── git pull KB
  ├── concept-skill-map missing?
  │     YES → Map Extraction Agent + Generator Agent run in PARALLEL
  │     NO  → Generator Agent only
  |
  ├── Eval (Check 1 + Check 2, parallel)
  │     both pass          → candidate
  │     one check fails    → Doctor / Rules Doctor patches it surgically → candidate
  │     both/still failing → Revision rewrites prompt (in-memory) → Generator → Eval
  │     budget exhausted or plateaued → ESCALATE TO HUMAN
  |
  ├── ≥2 passing candidates → Judge picks the best; 1 candidate → use it
  ├── Prerequisites (L1): add within-chapter prereq edges
  └── Save confirmed CSV + run record, git push
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
- A [Vercel AI Gateway](https://vercel.com/docs/ai-gateway) API key (routes to Anthropic, OpenAI, Google, etc. from one client)
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
AI_GATEWAY_API_KEY=...
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

**Re-extract the concept-skill-map with guidance, then re-run:**
```bash
python orchestrator.py --re-extract --board CBSE --subject Science --grade Grade8 --chapter Chapter3 --map-guidance "Split 'Motion' and 'Force' into separate concepts"
```

The orchestrator pulls the latest KB state at the start of every run and pushes any new files back to remote on completion (pass `--no-sync` to skip both).

---

## Human-in-the-Loop

There are two moments where a human intervenes:

**Moment 1 — Eval loop exhausted (attempt budget spent or gains plateaued)**

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

Open **http://localhost:3000**. The dashboard calls the FastAPI backend cross-origin directly (CORS-allowlisted), not through Next's rewrite proxy, so the SSE stream isn't buffered.

- **`/`** — pipeline console: run form, chapter queue (batch runs), live agent timeline, CSV compare/diff, escalation panel, and an L2 (cross-chapter) prerequisite run form.
- **`/analytics`** — run history, model-performance rollup (pass rate, avg tokens/cost per agent+model), and per-chapter drill-down.

---

## Project Status

| Component | Status |
|---|---|
| Orchestrator + core loop (Generator, Eval, Revision) | ✅ Shipped |
| Doctor / Rules Doctor (surgical repair) | ✅ Shipped |
| Judge (candidate selection) | ✅ Shipped |
| Prerequisites L1 (within-chapter) | ✅ Shipped |
| Chapter Relevance + Prerequisites L2 (cross-chapter) | ✅ Shipped |
| FastAPI backend + SSE streaming | ✅ Shipped |
| Live dashboard (pipeline console + analytics) | ✅ Shipped |

---

## Related

- **[q-matrix-kb](https://github.com/MaximusTitan/q-matrix-kb)** — Knowledge base (the data layer)