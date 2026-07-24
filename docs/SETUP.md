# Setup

Zero to a running pipeline. Follow the steps in order — several of them (Git LFS,
`KB_ROOT`) fail in confusing ways if done out of sequence.

If something breaks, see **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)**.

> **Running this pipeline spends real money.** Every agent call bills your Vercel AI
> Gateway key. Median cost to take one chapter through all three prerequisite stages is
> about **$0.82**. Read [§10 Cost](#10-cost) before you start a batch.

---

## 1. Prerequisites

| Requirement | Version | Why |
|---|---|---|
| Python | **3.10+** | The codebase uses PEP 604 `X \| None` unions in runtime-evaluated annotations (e.g. `skills/kb_access.py`, `orchestrator.py`), which raise `TypeError` on 3.9. Developed against 3.12–3.14. |
| Git | any recent | The pipeline shells out to `git` inside `KB_ROOT`. |
| **Git LFS** | any recent | **Install before you clone or add any PDF.** See below. |
| Node.js | **20.9+** (22 LTS recommended) | Required by Next.js 16 (`dashboard/package.json`). Only needed for the dashboard. |

### Install Git LFS first

Chapter and curriculum PDFs in the KB are LFS-tracked (`*.pdf filter=lfs` in the KB
repo's `.gitattributes`). If you clone the KB **without** LFS installed, every `.pdf`
on disk is a ~130-byte text pointer file, not a PDF. `pdfplumber` then fails with:

```
PdfminerException: No /Root object! - Is this really a PDF?
```

Install it before cloning:

```bash
# macOS
brew install git-lfs
# Debian/Ubuntu
sudo apt-get install git-lfs
# Windows: https://git-lfs.com  (or: winget install GitHub.GitLFS)

git lfs install
```

If you already cloned without LFS, recover with `git lfs install && git lfs pull`.

---

## 2. Clone both repos

Q-Matrix is two repos: this one is the **code layer**, and a separate **knowledge base**
repo holds all curriculum material and every output the pipeline writes. This repo never
writes to itself.

```bash
# 1. The code
git clone https://github.com/MaximusTitan/q-matrix-agents.git

# 2. Your own KB. Fork q-matrix-kb-template on GitHub first, then clone your fork —
#    the pipeline commits and pushes to this repo, so it must be one you can push to.
git clone https://github.com/<your-username>/q-matrix-kb-template.git
```

The template ships **empty by design**: directory scaffolding, README files, and
`rulesets/universal_rules.md`. It contains no curriculum content. You supply your own
material, and you are responsible for having the legal right to use it.

> If you do not want to fork — for example you are just evaluating locally — clone the
> template directly and always pass `--no-sync`. Without a fork you have no push
> permission and the end-of-run push will fail.

---

## 3. Python environment

```bash
cd q-matrix-agents
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Dependencies are deliberately few: `openai` (the Gateway speaks the OpenAI
Chat Completions shape), `pdfplumber`, `python-dotenv`, `fastapi`, `uvicorn`.

---

## 4. Get a Vercel AI Gateway key

All ten agents call LLMs through a single wrapper, `skills/llm.py`, pointed at
`https://ai-gateway.vercel.sh/v1`. One key reaches Anthropic, OpenAI, Google, Mistral,
DeepSeek and others, and the Gateway returns a pre-computed USD `cost` per call — which
is where every cost figure in this repo comes from.

1. Create a key at **https://vercel.com/docs/ai-gateway**.
2. Make sure the account has credit. Agents fail mid-run if it does not.
3. Put it in `.env` as `AI_GATEWAY_API_KEY` (next step).

The default model is `anthropic/claude-sonnet-5` (`skills/llm.py:DEFAULT_MODEL`). The
dashboard's run form lets you override the model per agent; the CLI always uses the
default.

**This key is billable.** There is no dry-run mode.

---

## 5. Configure `.env`

```bash
cp .env.example .env
```

Then edit it. Two variables matter:

```env
KB_ROOT=/Users/you/code/q-matrix-kb-template
AI_GATEWAY_API_KEY=vck_your_gateway_key_here
```

On Windows:

```env
KB_ROOT=C:\Users\you\code\q-matrix-kb-template
AI_GATEWAY_API_KEY=vck_your_gateway_key_here
```

`KB_ROOT` must be the **absolute path to the root of your KB clone** — the directory
that directly contains `textbooks/`, `curriculum-docs/`, and `rulesets/`. Not
`textbooks/`, not a parent.

`skills/kb_access.py` reads it at import time and raises immediately if it is unset:

```
EnvironmentError: KB_ROOT is not set. Add it to your .env file.
```

`.env` is gitignored. Never commit it.

Two things that do **not** go in this file:

- `NEXT_PUBLIC_API_URL` → `dashboard/.env.local` (see [§9](#9-running-the-dashboard)).
- `ANTHROPIC_API_KEY` → test-only, read by `tests/test_skills.py` alone. The pipeline
  never uses it.

---

## 6. Populate the KB

Grade and chapter folder names are matched as **exact strings** against what you pass on
the command line. Two conventions to get right, and both are load-bearing:

| Thing | Canonical form | Notes |
|---|---|---|
| Grade | `Grade 8`, `Grade 10` | The word `Grade`, a **space**, then the number. Always quote it in shell commands: `--grade "Grade 8"`. |
| Chapter | `Chapter04_Exploring_Forces` | Zero-padded number, underscores. Quote it too. |
| Chapter PDF | `chapter.pdf` | That exact filename, inside the chapter folder. |

Avoid `:`, `?`, `*`, `<`, `>`, `|`, `"` and trailing dots/spaces in board, subject, grade
and chapter folder names. They are illegal on Windows, so a KB containing them cannot be
cloned there at all.

### Minimum to run one chapter

Three things, relative to `KB_ROOT`:

1. `rulesets/universal_rules.md` — **ships with the template**, nothing to do.
2. `curriculum-docs/{board}/{subject}/{grade}/` — at least one `.pdf`, `.md`, or `.txt`.
   These are the syllabus/framework documents the Generator writes rows from. All files
   in the folder are concatenated.
3. `textbooks/{board}/{subject}/{grade}/{chapter}/chapter.pdf` — the chapter source the
   Map Extraction agent reads.

A complete, literal example:

```
q-matrix-kb-template/
├── rulesets/
│   └── universal_rules.md                        ← shipped with the template
├── curriculum-docs/
│   └── EXAMPLE_BOARD/
│       └── EXAMPLE_SUBJECT/
│           └── Grade 8/
│               └── syllabus.pdf                  ← yours; any .pdf/.md/.txt name
└── textbooks/
    └── EXAMPLE_BOARD/
        └── EXAMPLE_SUBJECT/
            └── Grade 8/
                └── Chapter04_Exploring_Forces/
                    └── chapter.pdf               ← yours; this exact filename
```

Everything else — `concept-skill-map.json`, `confirmed_curriculum.csv`, `run/`,
`prompt-library/`, `escalations/` — is created by the pipeline. Do not hand-author it.

If you add PDFs to the KB, `git add` them **after** `git lfs install`, so they are stored
as LFS objects rather than committed as raw binary blobs.

---

## 7. Verify the install before spending money

The cheapest check — no LLM calls, no populated KB, no cost:

```bash
python tests/test_prerequisite_l3.py
```

It needs `KB_ROOT` to be *set* (the import of `skills/kb_access.py` demands it) but the
path does not need to contain anything. Expected output ends with:

```
All tests passed.
```

If you get `EnvironmentError: KB_ROOT is not set`, your `.env` is missing or you are not
running from the repo root — `load_dotenv()` resolves `.env` relative to the working
directory.

### About the test suite

`tests/` is **not pytest**. All eight files are executable scripts with module-level
`assert`s and `print`s; there are zero `def test_*` functions and `pytest` is not in
`requirements.txt`. Run them one at a time:

```bash
python tests/test_prerequisite_l3.py
```

| Test | Needs populated KB | Makes billable LLM calls |
|---|---|---|
| `test_prerequisite_l3.py` | no | no |
| `test_skills.py` | **yes** — fails without | no |
| `test_validation.py` | **yes** — fails without | no |
| `test_map_extraction.py` | **yes** — fails without | **yes** |
| `test_generator.py` | yes | **yes** |
| `test_eval.py` | yes | **yes** |
| `test_generator_eval.py` | yes | **yes** |
| `test_revision_loop.py` | yes | **yes** |

The KB-dependent ones **fail**, they do not skip. On a fresh clone with an empty KB, only
`test_prerequisite_l3.py` passes — that is expected, not a broken install.

---

## 8. Running the pipeline

The CLI is `orchestrator.py`. Its complete flag set:

```
--board  --subject  --grade  --chapter
--human-feedback  --reject  --reason  --re-extract  --map-guidance
--prereq-csv  --no-sync
```

`--board --subject --grade --chapter` are all required except on the `--prereq-csv` path.
Quote every value that contains a space.

### Single chapter (full pipeline)

Map Extraction (if needed) → Generator → Eval → Doctor/Revision loop → Judge →
Prerequisites L1 → save + push.

```bash
python orchestrator.py \
  --board EXAMPLE_BOARD \
  --subject EXAMPLE_SUBJECT \
  --grade "Grade 8" \
  --chapter Chapter04_Exploring_Forces \
  --no-sync
```

Exit code is `0` if the chapter passed both checks, `1` if it escalated.

### First run: use `--no-sync`

Without it, the orchestrator runs `git pull --rebase` in `KB_ROOT` before the run and
`git add`/`commit`/`push` after it. That mutates and publishes your KB repo. Use
`--no-sync` until you are sure `KB_ROOT` points at a repo you own and want committed to.

```bash
python orchestrator.py --board EXAMPLE_BOARD --subject EXAMPLE_SUBJECT \
  --grade "Grade 8" --chapter Chapter04_Exploring_Forces --no-sync
```

Sync failures are non-fatal — the orchestrator prints
`[orchestrator] Warning: KB pull failed — …` and continues — but a failed push means your
results exist only on local disk.

### Batch (multiple chapters)

**There is no CLI batch flag.** Batching is a dashboard feature: the run form has an
*enqueue* action backed by a client-side sequential queue
(`dashboard/src/hooks/use-chapter-queue.ts`) that drains one chapter at a time, advancing
on every terminal outcome — passed, escalated, or error. It handles full runs and L2/L3
runs. See [§9](#9-running-the-dashboard).

From the CLI, loop in your shell:

```bash
for ch in Chapter04_Exploring_Forces Chapter05_Sound Chapter06_Light; do
  python orchestrator.py --board EXAMPLE_BOARD --subject EXAMPLE_SUBJECT \
    --grade "Grade 8" --chapter "$ch" --no-sync
done
```

Run chapters **sequentially**, not in parallel. Concurrent runs sharing one `KB_ROOT`
interleave their git staging (`skills/git_sync.py` scopes `add`/`commit` by pathspec
specifically to survive this, but you are still fighting for one index).

### Resume after an escalation

When the eval loop exhausts its attempt budget or plateaus, the orchestrator writes a
dated snapshot to `KB_ROOT/escalations/{board}/{subject}/{grade}/{chapter}/{date}/`
(`report.md`, `run.json`, and every attempt artifact) and prints the folder path. Read
`report.md`, then re-run with your instruction:

```bash
python orchestrator.py \
  --board EXAMPLE_BOARD --subject EXAMPLE_SUBJECT \
  --grade "Grade 8" --chapter Chapter04_Exploring_Forces \
  --human-feedback "Add pressure as a concept, max 3 skills per concept" \
  --no-sync
```

The feedback is injected into the Revision Agent as extra context for one more cycle. It
is not persisted as a rule.

### Reject a passed CSV and encode a permanent rule

Use this when the output passed both checks but is wrong. The reason is appended to
`rulesets/{board}/{subject}/{grade}/rules.md` and the pipeline re-runs. Eval enforces it
on every future run for that grade.

```bash
python orchestrator.py --reject \
  --board EXAMPLE_BOARD --subject EXAMPLE_SUBJECT \
  --grade "Grade 8" --chapter Chapter04_Exploring_Forces \
  --reason "Max 3 skills per concept" \
  --no-sync
```

`--reject` requires `--reason`.

### Re-extract the concept-skill-map with guidance

Use this when the *map* is wrong, not the CSV. Saves the guidance to the chapter's
`extraction_guidance.md`, re-runs Map Extraction, then re-runs the full pipeline.

```bash
python orchestrator.py --re-extract \
  --board EXAMPLE_BOARD --subject EXAMPLE_SUBJECT \
  --grade "Grade 8" --chapter Chapter04_Exploring_Forces \
  --map-guidance "Split 'Motion' and 'Force' into separate concepts" \
  --no-sync
```

`--re-extract` requires `--map-guidance`.

### Prerequisite mapping only, from a CSV file

Skips generation entirely and runs only the prerequisite phase. Board/subject/grade/
chapter are derived from the CSV's own rows, so the four identifier flags are not needed.
This path exits before any git pull or push, so `--no-sync` is irrelevant to it.

```bash
python orchestrator.py --prereq-csv /path/to/confirmed_curriculum.csv
```

### L2 (cross-chapter) and L3 (cross-grade)

**Neither has a CLI flag.** They are reachable only through the FastAPI backend — in
practice, through the dashboard's L2 and L3 run forms.

| Stage | Scope | Endpoint | Eligibility check |
|---|---|---|---|
| L1 | Within one chapter | part of every full pipeline run (CLI or `POST /run`) | — |
| L2 | Across chapters in one grade+subject | `POST /run-l2-prerequisite` | `GET /kb/l2-eligible-chapters?board=…&subject=…&grade=…` |
| L3 | Across earlier grades of the subject | `POST /run-l3-prerequisite` | `GET /kb/l3-eligible-chapters?board=…&subject=…&grade=…` |

Both are gated, and the gate is enforced server-side — the POST returns HTTP 400 if it is
not met:

- **L2** requires **every** chapter in that grade+subject to already have L1 prerequisites
  (`kb_access.grade_subject_l1_complete`). L2 uses the full sibling set as its candidate
  pool, so a single unmapped sibling blocks the whole grade.
- **L3** requires that *and* every chapter in **every earlier grade** of the same subject
  to have L1 prerequisites (`kb_access.subject_prior_grades_l1_complete`). Grades are
  ordered by trailing digits, and a subject may pull in alias subjects — `Science` also
  scans `Environmental Science` for its earliest grades
  (`kb_access._PREREQ_SUBJECT_ALIASES`). If there are no earlier grades at all, L3 is not
  available.

The eligibility endpoints return `blocking_chapters`, which is what to fix first:

```bash
curl "http://localhost:8000/kb/l2-eligible-chapters?board=EXAMPLE_BOARD&subject=EXAMPLE_SUBJECT&grade=Grade%208"
```

```json
{"eligible": false, "blocking_chapters": ["Chapter07_Sound"], "chapters": []}
```

Starting an L2 run directly (the dashboard does this for you):

```bash
curl -X POST http://localhost:8000/run-l2-prerequisite \
  -H "Content-Type: application/json" \
  -d '{"board":"EXAMPLE_BOARD","subject":"EXAMPLE_SUBJECT","grade":"Grade 8","chapter":"Chapter04_Exploring_Forces"}'
```

The response is `{"run_id": "..."}`; events stream from `GET /stream/{run_id}`. Swap
`run-l2-prerequisite` for `run-l3-prerequisite` for L3.

Note that all run-starting endpoints default to `no_sync: true`, and the dashboard always
sends `no_sync: true`. **Dashboard and API runs never push to the KB.** Only the CLI
pushes, and only without `--no-sync`.

---

## 9. Running the dashboard

Two terminals.

```bash
# Terminal 1 — FastAPI backend
source .venv/bin/activate
uvicorn api:app --reload --port 8000
```

```bash
# Terminal 2 — Next.js dashboard
cd dashboard
cp .env.local.example .env.local     # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev
```

Open **http://localhost:3000**.

| Route | What it does |
|---|---|
| `/` | Pipeline console: run form with per-agent model picker, KB browser (board → subject → grade → chapter), chapter queue for batch runs, live agent timeline over SSE, CSV compare/diff, escalation panel, and L2 / L3 prerequisite run forms with their eligibility state. |
| `/analytics` | Run history, model-performance rollup (pass rate, avg tokens and cost per agent+model), and per-chapter drill-down into individual run records and artifacts. |

`http://localhost:8000/` is not the dashboard — it is a stub page that links to :3000.
The dashboard calls the backend cross-origin directly rather than through a Next.js
rewrite, because proxying buffers the SSE stream.

### Security: localhost only

**The FastAPI backend has no authentication on any endpoint** — including the six that
start runs or write to your KB (`/run`, `/reject`, `/re-extract`,
`/run-prerequisite-only`, `/run-l2-prerequisite`, `/run-l3-prerequisite`). CORS is
allowlisted to `http://localhost:3000`, but CORS is a browser policy, not access control;
any direct HTTP client bypasses it entirely.

Anyone who can reach port 8000 can spend your Gateway credit and write to your KB. Bind
it to localhost only, never to `0.0.0.0`, never behind a public tunnel, and do not deploy
it.

---

## 10. Cost

Running the pipeline spends real money. There is no free or dry-run mode.

Figures below are measured medians from **685 recorded runs** in the maintainer's own KB
(`total_cost_usd` in each `run.json`, priced by the Gateway per call):

| Stage | Runs | Median | Mean | p90 | Max |
|---|---|---|---|---|---|
| Full pipeline (through L1) | 239 | **$0.32** | $0.45 | $0.96 | $1.64 |
| L2 only (cross-chapter) | 232 | **$0.11** | $0.13 | $0.26 | $0.34 |
| L3 only (cross-grade) | 212 | **$0.39** | $0.38 | $0.56 | $0.74 |

Taking one chapter all the way through all three stages costs about **$0.82** at the
median. Total across all 685 recorded runs: **$216.77**.

What moves these numbers:

- **Model choice.** Everything above used the defaults, `anthropic/claude-sonnet-5`
  unless overridden. A cheaper model per agent lowers cost; the dashboard's per-agent
  picker is where you set that.
- **Chapter length.** The whole chapter PDF and all curriculum docs go into the prompts.
- **Revision attempts.** A chapter that passes on attempt 1 is far cheaper than one that
  cycles through Doctor, Rules Doctor, Revision, and re-generation.
- **A failed or escalated chapter still costs money.** Every attempt before the
  escalation was billed. Escalations sit in the expensive tail of that full-pipeline
  distribution, not the cheap end.

Budget accordingly before queuing a whole grade: 20 chapters through all three stages is
roughly $16 at the median, and more if several escalate.
