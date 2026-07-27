# Contributing to q-matrix-agents

This repository is the **code layer** of Q-Matrix: a thin orchestrator, eleven
single-responsibility LLM agents, the skills modules they call, a FastAPI backend, and a
Next.js dashboard. Curriculum data lives in a separate repository reached through
`KB_ROOT`.

Read **[ARCHITECTURE.md](ARCHITECTURE.md)** before proposing anything structural. It is
the source of truth for control flow, the KB layout, and model routing.

---

## 1. Branches and pull requests

**No direct commits to `main`, ever.** Every change — code, prompt, doc, one-line fix —
lands through a pull request from a branch.

| Prefix | Use for |
|---|---|
| `feat/` | new agents, new skills, new endpoints, new dashboard views |
| `fix/` | bug fixes, prompt corrections, eval-gate repairs |
| `docs/` | README, ARCHITECTURE, this file, issue templates |

Example: `feat/l4-cross-subject-prereq`, `fix/check1-eval-gate`, `docs/oss-scaffolding`.

**Commit granularity.** Prefer a few meaningful, self-contained commits over
one-file-per-commit churn. A commit should be a coherent unit of work that reviewers can
read and, if necessary, revert on its own — not a checkpoint of your editor state. A PR
that touches an agent, its prompt, and its test is normally one commit, not three.

Keep the PR description filled in — see
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md). If the pipeline's
behavior changed, before/after numbers are part of the description, not an optional extra.

---

## 2. Development setup

Follow **[README.md → Setup](README.md#setup)**. Do not duplicate those steps here; if
they are wrong or incomplete, fix the README in a `docs/` PR.

Two things worth restating because they cause most first-run failures:

- `KB_ROOT` must point at a local clone of a Q-Matrix knowledge base. Nothing in this
  repo runs without it — `skills/kb_access.py` raises `EnvironmentError` at import time
  if it is unset.
- `AI_GATEWAY_API_KEY` is a billable credential for the Vercel AI Gateway. Never commit
  `.env`.

### Environment variables actually read by the code

| Variable | Read by | Required |
|---|---|---|
| `KB_ROOT` | `skills/kb_access.py`, `skills/git_sync.py`, tests | Yes |
| `AI_GATEWAY_API_KEY` | `skills/llm.py` | Yes |
| `ANTHROPIC_API_KEY` | `tests/test_skills.py` only | No (test path) |
| `NEXT_PUBLIC_API_URL` | `dashboard/` only | Dashboard only |

Anything else you find in a `.env` is dead weight — say so in a PR rather than adding to it.

---

## 3. Testing

Tests live in `tests/` and are run **from the repository root**:

```bash
python tests/test_prerequisite_l3.py     # pure-logic, no KB and no LLM call
python tests/test_generator_eval.py      # live: needs KB_ROOT + AI_GATEWAY_API_KEY
pytest tests/                            # collects the files; see the caveat below
```

Be aware of what the current suite actually is, so you do not misread a green run:

- Most files are **executable scripts with module-level `assert`s and prints**, not
  `pytest` test functions. There are currently **zero `def test_*` functions** in
  `tests/`. `pytest tests/` therefore executes each module at collection time and
  reports "no tests ran" even though the assertions did run. `pytest` is not in
  `requirements.txt`.
- `tests/test_prerequisite_l3.py` is the only file that needs neither `KB_ROOT` nor a
  live LLM call — it exercises pure logic (edge-key construction/validation, the
  empty-candidate-pool short-circuit, grade ordering).
- `tests/test_skills.py`, `tests/test_validation.py`, and `tests/test_map_extraction.py`
  read the KB directly and will **fail (not skip)** without a populated `KB_ROOT`. They
  assume real content, e.g. `textbooks/CBSE/Science/Grade 8/Chapter*/chapter.pdf`.
- `tests/test_generator.py`, `test_eval.py`, `test_generator_eval.py`, and
  `test_revision_loop.py` make **real, billable LLM calls** against real chapters.
- Grade folders are named `Grade` + space + number, e.g. `Grade 8`. Fixtures and paths
  that get this wrong silently find nothing.

**Expectations for contributions:**

- Every new agent and every new skills module ships with a test.
- Prefer pure-logic tests that need neither `KB_ROOT` nor a network call —
  `tests/test_prerequisite_l3.py` is the model to copy. Factor the deterministic parts of
  an agent (parsing, validation, filtering, short-circuits) out of the LLM call so they
  can be tested without spending money.
- If a test genuinely needs a populated KB or a live model, say so in its module
  docstring, exactly as the existing files do.
- Migrating the suite to real `pytest` test functions with `pytest.mark.skipif` guards on
  `KB_ROOT` / `AI_GATEWAY_API_KEY` is a welcome `fix/` or `docs/` contribution.

---

## 4. Code style

Match what is already in the tree. Read `skills/kb_access.py`, `skills/llm.py`, and
`agents/chapter_relevance.py` before writing a new module — they are the reference.

- **Module-level docstring naming the file first**, then what it does and why. Agent
  modules also document `Input:`, `Output:`, and a `Skills used:` list.

  ```python
  """
  skills/git_sync.py

  Git sync operations for the KB repo.
  Called by the orchestrator at the start (pull) and end (push) of every run.
  The agents themselves never call this — only the orchestrator does.
  """
  ```

- **Google-style function docstrings** with `Args:` / `Returns:` / `Raises:` where each
  applies. Non-obvious design decisions are explained in the docstring or a comment, with
  the reason — see `skills/git_sync.py:push_kb`, which records the concrete incident that
  motivated its scoped pathspec.
- **Box-drawing section separators** inside longer modules:

  ```python
  # ─── Path Builders ────────────────────────────────────────────────────────────
  ```

- **Type hints on signatures**, modern syntax (`dict | None`, `list[str]`, `tuple[dict, float]`).
- Private helpers and module constants are `_`-prefixed (`_run`, `_PROMPT_PATH`, `_USAGE_FIELDS`).
- Aligned assignments and keyword arguments where it aids scanning (see the argparse block
  in `orchestrator.py`). Follow the local convention rather than reformatting neighbouring code.
- No emoji in code or docs headers. No marketing language.

---

## 5. Proposing a new agent

Use the **[new agent proposal](.github/ISSUE_TEMPLATE/new_agent.yml)** issue form first.
Agents are the most expensive thing in the system to get wrong — each one adds latency,
tokens, and a new failure mode to every run — so the design is agreed before the code.

### What an agent module must look like

- **One responsibility.** If you cannot state it in a single sentence, it is two agents.
- **Its system prompt lives in `prompts/<name>_prompt.md`** and is loaded at import time
  from disk. Prompts are never inlined as Python string literals.
- **Called by the orchestrator; never calls the orchestrator.** Control flow is one-way.
  Agents also do not call each other.
- **Agents do not touch the filesystem.** Only `skills/` performs IO. An agent takes
  already-loaded data as arguments and returns data; the orchestrator decides what gets
  persisted.
- **Reaches the LLM only through `skills/llm.py`** (`call_llm` / `call_llm_structured`).
  Retry logic belongs there, not in agent code. The model is per-call, with a fallback to
  the agent's entry in `AGENT_DEFAULT_MODELS`.
- **Emits usage and cost.** Every return value carries `usage` and `cost_usd` (summed with
  `skills.llm.add_usage` across multiple calls) so it lands in the run record and the
  analytics dashboard. An agent that does not report cost is invisible to every
  optimisation decision that follows.
- **Degrades rather than crashes** where the pipeline can continue without it — the
  prerequisite agents return warnings and empty edges instead of raising.
- Ships with a test (see §3) and a documentation update to README's roster table and
  ARCHITECTURE §4.

### What the proposal must contain

1. **The failure mode it fixes** — an existing, observed problem, not a hypothetical.
2. **The I/O contract** — exact input arguments and the exact returned dict shape.
3. **Where it slots into the control flow** — which agent it follows and which it precedes,
   with reference to the flowchart in ARCHITECTURE §5.
4. **Expected token/cost delta per chapter**, against the measured baselines in §7.
5. **Evidence** — run records, a prototype, or a hand-labelled sample showing the failure
   mode is real and that the agent addresses it.

Note: an **L4 (cross-subject) prerequisite agent is planned but not implemented.** Do not
document it as existing. If you want to build it, open a proposal.

---

## 6. Proposing a new skill module

`skills/` are pure, side-effect-scoped helpers. A skills module owns one capability and
keeps its side effects explicit and narrow (`file_io.py` touches the filesystem,
`git_sync.py` shells out to git, `llm.py` talks to the network, `run_record.py` and
`diff.py` do no IO at all).

Rules:

- **`skills/kb_access.py` is the SOLE owner of KB path knowledge.** Any new KB path,
  filename, or folder convention is added there and **nowhere else**. No other module —
  no agent, not the orchestrator, not `api.py`, not a test — may construct a path from
  `KB_ROOT`. This is the one seam between the code repo and the data repo and it stays
  one file wide.
- Keep computation and IO separated: prefer a pure function plus a thin persistence
  wrapper over one function that does both.
- No agent-specific business logic in `skills/`. If only one agent will ever call it, it
  belongs in that agent.
- Add the module to the table in ARCHITECTURE §8 in the same PR.

---

## 7. Pipeline-improvement track

Improving the pipeline's economics and pass rate is a first-class contribution, equal to
shipping features. Proposals are judged on **measurable movement**, not on plausibility.

### Metrics that count

| Metric | Source |
|---|---|
| Escalation rate | share of runs ending `pipeline_escalated` (run records + `escalations/`) |
| Cost per chapter | `run.json` → `total_cost_usd` |
| Check-1 pass rate | `run.json` → per-attempt `check1` |
| Check-2 pass rate | `run.json` → per-attempt `check2` |
| Token count | `run.json` → `total_usage` |

### Measured baseline

From 685 recorded run records:

| Stage | Median | Mean | p90 | Max |
|---|---|---|---|---|
| Full pipeline (Stage 1 + L1) | $0.32 | $0.45 | $0.96 | $1.64 |
| L2 (cross-chapter) | $0.11 | — | — | — |
| L3 (cross-grade) | $0.39 | — | — | — |

Mapping one chapter across all three stages costs roughly **$0.82 median**.

### What a good proposal looks like

- Before/after numbers taken from **real run records**, not estimates.
- The number of runs and which chapters were used. A single chapter proves nothing;
  chapter difficulty dominates cost variance.
- Both sides of the trade: a change that halves cost while dropping the Check-2 pass rate
  is a regression, and a change that raises the pass rate must state what it costs.
- Attach or link the `run.json` files.

### Categories

1. **New agents** — see §5.
2. **Prompt and ruleset refinements** — prompt files in this repo; `universal_rules.md`
   and grade rules content in the KB repo (see §8).
3. **Cost or token reduction** — model swaps, prompt trimming, prompt caching, batching,
   cheaper pre-filters. Use the
   [cost-reduction form](.github/ISSUE_TEMPLATE/cost_reduction.yml).
4. **New board / curriculum adapters** — support for boards or subject structures the
   current extraction and eval path handles poorly.

---

## 8. Which repository gets what

| Contribution | Repository |
|---|---|
| Orchestrator, agents, prompts, skills, `api.py`, dashboard, docs, tests | **this repo** (`q-matrix-agents`) |
| Curriculum material (PDFs, LO documents, textbooks) | **KB template repo** (`q-matrix-kb-template`) |
| Ruleset *content* (`universal_rules.md`, grade `rules.md`) | KB template repo |
| KB structure / layout changes | KB template repo — plus the matching path change in `skills/kb_access.py` here |

This repo contains **no curriculum data and no secrets**, and the pipeline never writes to
it. Do not add curriculum text to an issue, a test fixture, a prompt, or a PR description.

Curriculum-data contributions carry their own **rights-attestation requirements** —
you must be able to attest that the material may be redistributed under the KB repo's
terms. Those requirements are documented in the KB template repository; read them before
opening a data PR there.

---

## 9. Review process

- **At least one maintainer review** before merge. No self-merges.
- **CI and tests green.** If a test cannot run in CI because it needs a populated KB or a
  live model, paste the local output in the PR.
- **No secrets in the diff.** No API keys, no `.env`, no absolute paths containing
  credentials, no tokens in logs pasted into the description.
- **No copyrighted curriculum text** in code, tests, prompts, or issue bodies.
- If behavior changed, README and/or ARCHITECTURE are updated in the same PR.

Security issues do **not** go through the issue tracker — see
[SECURITY.md](SECURITY.md).
