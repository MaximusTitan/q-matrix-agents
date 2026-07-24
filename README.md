# q-matrix-agents

> Orchestrator, agents, and skills for the Q-Matrix curriculum generation system — part of AI Ready School by Intelliana.

This repository is the **code layer** of the Q-Matrix system. It contains the orchestrator, eleven LLM-powered agents, a FastAPI backend, a live Next.js dashboard, and the skill modules that read from and write to the knowledge base.

Licensed under **[Apache 2.0](LICENSE)**. See **[CONTRIBUTING.md](CONTRIBUTING.md)**, **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**, and **[SECURITY.md](SECURITY.md)**.

> For the full system design (control-flow diagrams, KB layout, model routing, runtime topology) see **[ARCHITECTURE.md](ARCHITECTURE.md)** — this README is a quick-start overview.
>
> New here? **[docs/SETUP.md](docs/SETUP.md)** is the zero-to-running guide; **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** covers common failures.

---

## What Q-Matrix Does

Given curriculum documentation from any education board, Q-Matrix produces a validated curriculum CSV that maps:

```
Board → Subject → Grade → Chapter → Concept → Skill   (+ L1/L2/L3 prerequisite columns)
```

The six base columns are always present. Each prerequisite level appends two more
(`prereq_concepts_L{n}_*`, `prereq_skills_L{n}_*`) when that level has been run.

This is a multi-agent system. Specialized agents — each with their own skills, prompt, and responsibilities — coordinate through a thin orchestrator to generate, evaluate, repair, and enrich curriculum CSVs automatically, with a human in the loop only on escalation.

---

## System Architecture

```
orchestrator.py              ← Thin coordinator. No LLM calls. Pure control flow.
api.py                       ← FastAPI backend (:8000) — SSE streaming, analytics
│
├── agents/                  ← 11 single-responsibility LLM agents (see roster below)
├── prompts/                 ← one system prompt per agent (11 files)
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
├── utils/events.py          ← in-process pub/sub bus behind the SSE stream
├── tests/                   ← executable assert scripts (see "Tests" below)
├── scripts/                 ← sync_textbooks_from_drive.py (Google Drive → KB)
└── dashboard/               ← Next.js live console + analytics (:3000)
```

---

## Agent Roster

Eleven agents, each loading its system prompt from `prompts/<name>_prompt.md`. Full responsibilities, I/O shapes, and the flowchart of how they connect are in **[ARCHITECTURE.md §4](ARCHITECTURE.md#4-the-agent-roster)**.

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
| **Prerequisite (L3)** | Map cross-grade (same subject) prerequisite edges — target chapter ← chapters in earlier grades, screened once per earlier grade |

Chapter Relevance has no model key of its own: the screen runs on whichever model the
L2 or L3 run is using (`orchestrator.AGENT_KEYS` covers ten keys — `map_extraction`,
`generator`, `eval`, `doctor`, `rules_doctor`, `revision`, `judge`, `prerequisite`,
`prerequisite_l2`, `prerequisite_l3`).

### Prerequisite levels

| Level | Scope | Columns added | Precondition |
|---|---|---|---|
| L1 | Within one chapter | `prereq_concepts_L1_same_chapter`, `prereq_skills_L1_same_chapter` | Runs inline at the end of every full pipeline run |
| L2 | Cross-chapter, same grade + subject | `prereq_concepts_L2_cross_chapter`, `prereq_skills_L2_cross_chapter` | **Every** chapter in the grade+subject already has L1 edges |
| L3 | Cross-grade, same subject | `prereq_concepts_L3_prior_grade`, `prereq_skills_L3_prior_grade` | Every chapter in **every earlier grade** of the subject already has L1 edges (plus the L2 precondition on the target's own grade) |

L3 edges are written only onto the target (downstream) chapter's CSV — earlier-grade
chapters are read-only inputs. Each L3 cell holds `{"grade", "chapter",
"concept"|"skill", "reason"}` entries; `grade` is carried because chapter names are not
unique across grades.

Two L3 specifics worth knowing:

- **Subject aliasing.** For L3 only, `skills/kb_access.py:_PREREQ_SUBJECT_ALIASES` maps
  `Science → ("Environmental Science",)`, so an L3 run for Science also scans
  Environmental Science grades. CBSE only introduces Science as a standalone subject
  from Grade 6; Grades 3–5 cover the same ground as EVS. L1 and L2 stay exact-match on
  subject.
- **Deliberate omission.** L3 does not assert long-assumed foundational dependencies
  ("uses basic arithmetic") even when technically true — a guardrail in
  `prompts/prerequisite_l3_prompt.md`, not a code filter.

---

## Orchestration Flow

The core generate → evaluate → repair/revise loop (bounded, adaptive). L2 (cross-chapter) and L3 (cross-grade) prerequisite mapping run as separate passes once their preconditions are met. See **[ARCHITECTURE.md §5](ARCHITECTURE.md#5-the-pipeline-control-flow)** for the full flowchart including Doctor/Judge/escalation paths.

```
START: Board · Subject · Grade · Chapter
  |
  ├── git pull KB                                    (CLI only — see "KB sync" below)
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
  └── Save confirmed CSV + run record, git push      (push: CLI only)

LATER, as separate runs (API/dashboard only — no CLI flags):
  L2: every chapter in the grade+subject has L1  → Chapter Relevance screen → Prerequisite L2
  L3: every chapter in every EARLIER grade of the subject has L1
                                                → Chapter Relevance screen, once per
                                                  earlier grade → Prerequisite L3
```

---

## Prompt Resolution & Cold Start

`skills/kb_access.py:load_prompt` resolves the generation prompt in a fixed order and
returns which level it came from:

1. `prompt-library/{board}/{subject}/{grade}/prompt.md` → `grade_prompt`
2. `prompt-library/{board}/{subject}/base_prompt.md` → `base_prompt`
3. `rulesets/universal_rules.md` → `cold_start` (raises if this file is missing)

`universal_rules.md` is the only manually authored input, and the only file the cold-start
path needs.

**Revised prompts are ephemeral — the pipeline never writes to the prompt library.** When
Eval fails, the Revision Agent's rewritten prompt is threaded through the rest of the run
in memory only (`working_prompt` in `orchestrator.py`, `prompt_override` on the Generator).
Commit `84151f7` removed every `save_prompt` call from the pipeline to stop cross-chapter
prompt contamination and batch races; the prompt library is read-only during a run.
`skills/kb_access.py:save_prompt` still exists but its only remaining caller in the repo is
`tests/test_revision_loop.py`.

Practical consequence: unless you author `base_prompt.md` or a `{grade}/prompt.md`
yourself, **every run starts from `universal_rules.md`** and learns nothing across runs
about generation prompts. Persistent learning happens only through the rejection path,
which writes grade `rules.md` (see Human-in-the-Loop).

---

## Setup

Full walkthrough: **[docs/SETUP.md](docs/SETUP.md)**. Stuck? **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**.

### Prerequisites

- Python 3.10+
- Node.js — required for the dashboard (Next.js 16.2.7; `dashboard/package.json` declares no `engines` field, see [docs/SETUP.md](docs/SETUP.md) for the version this is tested against)
- Git with Git LFS
- A [Vercel AI Gateway](https://vercel.com/docs/ai-gateway) API key (routes to Anthropic, OpenAI, Google, etc. from one client)
- A local clone of the KB template, **[q-matrix-kb-template](https://github.com/MaximusTitan/q-matrix-kb-template)** — it ships the directory structure only, with no curriculum content. You supply your own curriculum documentation and textbook PDFs, and you are responsible for having the rights to use them.

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
KB_ROOT=/path/to/your/clone/of/q-matrix-kb-template
AI_GATEWAY_API_KEY=...
```

`KB_ROOT` is the local path to wherever you cloned your KB. Every person sets their own path here. Never commit `.env`.

### Naming convention (matters)

KB lookups are **exact string matches on folder names** — there is no normalization or
fuzzy matching. Use the same names the KB template uses:

| Argument | Convention | Example |
|---|---|---|
| `--board` | Board folder name | `CBSE` |
| `--subject` | Subject folder name | `Science` |
| `--grade` | `Grade` + space + number | `"Grade 8"` (quote it — it contains a space) |
| `--chapter` | Chapter folder name verbatim | `"Chapter04_Exploring_Forces"` |

`--grade Grade8` will silently find nothing.

---

## Running the Pipeline

### How each stage is invoked

Not every stage has a CLI. `orchestrator.py`'s argparse exposes exactly these flags:
`--board --subject --grade --chapter --human-feedback --reject --reason --re-extract
--map-guidance --prereq-csv --no-sync`. **There are no `--l2` / `--l3` flags.**

| Stage | CLI | API endpoint | Entry function |
|---|---|---|---|
| Full pipeline (incl. L1) | ✅ `python orchestrator.py …` | `POST /run` | `run_pipeline` |
| L1 prereqs only, from a CSV file | ✅ `--prereq-csv path.csv` | `POST /run-prerequisite-only` | `run_prerequisite_only` |
| L2 (cross-chapter) | ❌ none | `POST /run-l2-prerequisite` | `run_l2_prerequisite_only` |
| L3 (cross-grade) | ❌ none | `POST /run-l3-prerequisite` | `run_l3_prerequisite_only` |
| Reject + encode rule | ✅ `--reject --reason "…"` | `POST /reject` | `handle_reject` |
| Re-extract concept-skill-map | ✅ `--re-extract --map-guidance "…"` | `POST /re-extract` | `handle_re_extract` |

So in practice L2 and L3 are run **from the dashboard**, or by POSTing to the API yourself.
Both entry functions are importable from `orchestrator` if you'd rather script them.
Eligibility can be checked first via `GET /kb/l2-eligible-chapters` and
`GET /kb/l3-eligible-chapters`; both run endpoints also re-check and return HTTP 400 if the
precondition isn't met.

**Normal run:**
```bash
python orchestrator.py --board CBSE --subject Science --grade "Grade 8" --chapter "Chapter04_Exploring_Forces"
```

**Resume after escalation with human feedback:**
```bash
python orchestrator.py --board CBSE --subject Science --grade "Grade 8" --chapter "Chapter04_Exploring_Forces" --human-feedback "Add pressure as a concept with max 3 skills"
```

**Reject a passed CSV and encode a new rule:**
```bash
python orchestrator.py --reject --board CBSE --subject Science --grade "Grade 8" --chapter "Chapter04_Exploring_Forces" --reason "Max 3 skills per concept"
```

**Re-extract the concept-skill-map with guidance, then re-run:**
```bash
python orchestrator.py --re-extract --board CBSE --subject Science --grade "Grade 8" --chapter "Chapter04_Exploring_Forces" --map-guidance "Split 'Motion' and 'Force' into separate concepts"
```

### KB sync — CLI only

`pull_kb()` and `push_kb()` are called from `orchestrator.main()` and nowhere else.
`run_pipeline` itself never touches git. Consequences:

- **CLI runs** pull the KB before the run and push after it (pass `--no-sync` to skip both).
  The `--prereq-csv` path returns before either, so it never syncs.
- **Dashboard / API runs never pull or push.** Files are written to your local `KB_ROOT` and
  stay there until you commit and push them yourself. The `no_sync` field on the API request
  models defaults to `True` and is not forwarded to the orchestrator at all, so setting it
  to `False` changes nothing; `dashboard/src/lib/api.ts` hardcodes `no_sync: true` on every
  POST regardless.

If you run from the dashboard, treat committing the KB as a manual step.

---

## Cost

Measured from 685 recorded run records (`total_cost_usd` in `run.json`), at the default
model routing:

| Stage | Median | Notes |
|---|---|---|
| Full pipeline (generate → eval → repair → L1) | **$0.32** | mean $0.45 · p90 $0.96 · max $1.64 |
| L2 (cross-chapter) | **$0.11** | |
| L3 (cross-grade) | **$0.39** | scales with how many earlier grades exist |
| All three stages for one chapter | **≈ $0.82** | sum of medians |

Costs come straight from the Gateway's per-call `cost` field, so they track whatever models
you route to. See **[docs/SETUP.md](docs/SETUP.md)** for cost control and model-selection guidance.

---

## Tests

`tests/` holds **executable scripts, not a pytest suite** — there are no `def test_*`
functions and `pytest` is not a dependency. Run them individually:

```bash
python tests/test_skills.py
python tests/test_prerequisite_l3.py
```

Most load `.env` and hit the real KB and/or the real Gateway, so they need a populated
`.env` and will cost money. `tests/test_prerequisite_l3.py` is the exception — it stubs the
LLM and runs offline.

---

## Human-in-the-Loop

There are two moments where a human intervenes:

**Moment 1 — Eval loop exhausted (attempt budget spent or gains plateaued)**

The orchestrator writes an escalation report to `$KB_ROOT/escalations/` and prints a terminal message. The human reads the report, then re-runs with `--human-feedback`. The feedback is injected into the Revision Agent as additional context for one final cycle.

**Moment 2 — Human rejects a passed CSV**

The human runs `--reject` with a reason. The orchestrator writes that reason as a new rule into `rulesets/{board}/{subject}/{grade}/rules.md` and re-runs the pipeline. The Eval Agent will enforce this rule automatically on all future runs for that grade.

The human never edits prompts or agent code directly. All feedback enters the system as text and is encoded into the KB by the orchestrator.

---

## Knowledge Base

This repo never writes to itself. All outputs (concept-skill-maps, CSVs, run records, escalations) go to the KB repo at `KB_ROOT`. See **[q-matrix-kb-template](https://github.com/MaximusTitan/q-matrix-kb-template)** for the structure and schema — it ships empty. You populate `curriculum-docs/` and `textbooks/` with material you have the right to use, seed `rulesets/universal_rules.md`, and point `KB_ROOT` at your clone.

Directories the code expects under `KB_ROOT` (all resolved in `skills/kb_access.py`):

```
curriculum-docs/{board}/{subject}/{grade}/
textbooks/{board}/{subject}/{grade}/{chapter}/     ← chapter.pdf, concept-skill-map.json,
                                                      confirmed_curriculum.csv, run/{full,l1_prereq,l2,l3}/
prompt-library/{board}/{subject}/                  ← base_prompt.md, {grade}/prompt.md
rulesets/                                          ← universal_rules.md, {board}/{subject}/{grade}/rules.md
run_history/{board}/{subject}/{grade}/{chapter}/   ← archived run records, one JSON per run_id
escalations/{board}/{subject}/{grade}/{chapter}/{date}/
```

---

## Live Dashboard

The pipeline dashboard is a Next.js app in [`dashboard/`](dashboard/) that streams live events from the FastAPI backend via SSE.

First-time setup — the dashboard needs its own dependencies and its own env file:

```bash
cd dashboard
npm install
cp .env.local.example .env.local     # sets NEXT_PUBLIC_API_URL=http://localhost:8000
```

`NEXT_PUBLIC_API_URL` is not optional in practice: `dashboard/src/lib/api.ts` falls back to
`""` (relative paths) when it is unset, so requests hit the Next server instead of FastAPI
and the UI comes up empty with no error.

Then, in two terminals:

```bash
# Terminal 1 — API backend
uvicorn api:app --reload --port 8000

# Terminal 2 — Dashboard UI
cd dashboard && npm run dev
```

Open **http://localhost:3000**. The dashboard calls the FastAPI backend cross-origin directly (CORS-allowlisted), not through Next's rewrite proxy, so the SSE stream isn't buffered.

- **`/`** — pipeline console: a run form with four modes (**Generate** from the KB, **CSV** for L1-prereqs-only on a pasted CSV, **L2 Prerequisites**, **L3 Prerequisites**), per-agent model overrides, a sequentially drained chapter queue, live agent timeline, CSV compare/diff, prerequisite-mapping summary, run history, and an escalation panel.
- **`/analytics`** — run history, model-performance rollup (pass rate, avg tokens/cost per agent+model), and per-chapter drill-down.

### This backend is not deployable as-is

`api.py` is **localhost-development-only**:

- **No authentication or authorization on any endpoint** — including the six write/run
  endpoints (`/run`, `/reject`, `/run-prerequisite-only`, `/run-l2-prerequisite`,
  `/run-l3-prerequisite`, `/re-extract`), which spend API credits, mutate the KB, and can
  `git push`.
- The only access control is CORS, allowlisted to `http://localhost:3000`. CORS is a
  browser policy, not a server-side guard — it stops nothing that isn't a browser.
- Bind it to `127.0.0.1` and do not expose it to a network or the internet. See
  **[SECURITY.md](SECURITY.md)**.

---

## Project Status

| Component | Status |
|---|---|
| Orchestrator + core loop (Generator, Eval, Revision) | ✅ Shipped |
| Doctor / Rules Doctor (surgical repair) | ✅ Shipped |
| Judge (candidate selection) | ✅ Shipped |
| Prerequisites L1 (within-chapter) | ✅ Shipped |
| Chapter Relevance + Prerequisites L2 (cross-chapter) | ✅ Shipped |
| Prerequisites L3 (cross-grade, same subject) | ✅ Shipped |
| Prerequisites L4 (cross-subject) | 🔲 Planned — not implemented |
| FastAPI backend + SSE streaming | ✅ Shipped (localhost only, unauthenticated) |
| Live dashboard (pipeline console + analytics) | ✅ Shipped |
| Prompt-library persistence of revised prompts | ⚠️ Intentionally disabled since `84151f7` — see Prompt Resolution |

---

## Related

- **[q-matrix-kb-template](https://github.com/MaximusTitan/q-matrix-kb-template)** — Knowledge base template (the data layer); structure only, you supply the curriculum material