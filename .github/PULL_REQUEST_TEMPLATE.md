# What changed and why

<!-- The problem, then the change. Not a restatement of the diff. -->

**Closes:** #

---

## Type of change

<!-- Check all that apply. -->

- [ ] Agent (`agents/`)
- [ ] Skill module (`skills/`)
- [ ] Prompt (`prompts/`)
- [ ] Orchestrator (`orchestrator.py`)
- [ ] API (`api.py`)
- [ ] Dashboard (`dashboard/`)
- [ ] Docs (README / ARCHITECTURE / CONTRIBUTING / SECURITY)
- [ ] Tests only
- [ ] Other:

---

## How this was tested

**Tests run** — paste the actual output, trimmed. Note that most files in `tests/` are
executable scripts, not `pytest` test functions; say which you ran and how.

```
$ python tests/test_prerequisite_l3.py
...
```

**Chapters run end-to-end** — list the real `board / subject / grade / chapter` targets
you ran through the pipeline, and the outcome (passed / escalated) for each. "Ran the
tests" is not sufficient for a change to an agent, a prompt, or the orchestrator.

| Board | Subject | Grade | Chapter | Outcome |
|---|---|---|---|---|
|  |  |  |  |  |

**Not tested / known gaps:**

---

## Cost and quality impact

<!-- Required if this PR changes the pipeline (agent, prompt, orchestrator, model routing).
     Delete this section for docs-only or dashboard-only changes.
     Numbers come from run.json: total_cost_usd and total_usage. -->

| Metric | Before | After | n runs |
|---|---|---|---|
| Escalation rate |  |  |  |
| Cost per chapter (median) |  |  |  |
| Total tokens per chapter |  |  |  |
| Check-1 pass rate |  |  |  |
| Check-2 pass rate |  |  |  |

Baseline for reference (685 run records): full pipeline median **$0.32** (mean $0.45,
p90 $0.96, max $1.64); L2 median **$0.11**; L3 median **$0.39**; all three stages
≈ **$0.82** median per chapter.

Which chapters the before/after numbers came from:

---

## Checklist

- [ ] Tests pass, and new agents / skills modules ship with a test
- [ ] No secrets in the diff — no API keys, tokens, or credentials, including in pasted logs
- [ ] No `.env` or other ignored file committed
- [ ] No copyrighted curriculum or textbook content added to code, tests, prompts, or this description
- [ ] Any new KB path lives only in `skills/kb_access.py`
- [ ] This is a PR from a `feat/` `fix/` `docs/` branch — **not** a direct commit to `main`
- [ ] Commits are meaningful units of work, not one-file-per-commit churn
- [ ] README and/or ARCHITECTURE updated if behavior, the agent roster, the API surface, or the KB layout changed
