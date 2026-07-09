"""
skills/run_record.py

Assembles the structured per-chapter run record (`run.json`) from the events of a
single pipeline run. Pure module — it knows the SHAPE of the record and the sibling
filename convention, but nothing about WHERE files live on disk (that is
`kb_access.py`'s sole responsibility) and nothing about how the record is rendered to
markdown (that is `report_render.py`).

A run produces several CSVs — one per generator attempt, plus any coverage-doctor and
rules-doctor patches, plus the final confirmed/last CSV. `run.json` stores only
pointers (`*_file`) to these CSVs; the CSV text is returned separately as an artifacts
map so the writer can lay each one down as an independent, downloadable sibling file.

Usage:
    builder = RunRecordBuilder(board, subject, grade, chapter, date)
    builder.add_attempt(attempt=1, input_type="grade_prompt", prompt=..., gen_csv=...,
                        gen_rows=12, check1=c1, check2=c2)
    builder.add_doctor(attempt=1, kind="coverage", gaps_addressed=..., csv=...,
                       error=None, reeval_check1=dc1, reeval_check2=dc2,
                       passed=False, regressed=False, regressed_concepts=[],
                       regressed_skills=[])
    builder.set_judge(...)
    builder.finalize(final_status="passed", failed_check=None, final_csv=...,
                     final_csv_name="confirmed.csv", confirmed_checkpoint=True,
                     has_prereqs=True)
    record, artifacts = builder.build()
"""

import uuid
from datetime import datetime, timezone

from skills.llm import add_usage

SCHEMA_VERSION = 2

_ZERO_USAGE = {
    "input_tokens": 0, "output_tokens": 0,
    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
}


def _gen_csv_name(attempt: int) -> str:
    return f"gen_attempt_{attempt}.csv"


def _doctored_csv_name(attempt: int, kind: str) -> str:
    """Sibling filename for a doctor's patched CSV.

    Coverage and rules doctors write to distinct names, so an attempt where the
    coverage doctor is chained into the rules doctor produces two non-colliding files.
    """
    if kind == "rules":
        return f"doctored_rules_attempt_{attempt}.csv"
    return f"doctored_attempt_{attempt}.csv"


def _prompt_name(attempt: int) -> str:
    return f"attempt_{attempt}_prompt.md"


def _candidate_csv_name(source: str, cycle: int) -> str:
    """Resolve a Judge candidate back to its sibling CSV filename by source + cycle."""
    if source == "doctored":
        return _doctored_csv_name(cycle, "coverage")
    if source == "rules_doctored":
        return _doctored_csv_name(cycle, "rules")
    # "generated" and any unknown source fall back to the generator attempt file.
    return _gen_csv_name(cycle)


class RunRecordBuilder:
    """Accumulates the events of one pipeline run into a structured record.

    Tolerant of partial state: a run that escalates during generation (before any
    attempt is fully evaluated) still builds a valid record with zero or fewer
    attempts.
    """

    def __init__(self, board, subject, grade, chapter, date, mode="full"):
        self.board = board
        self.subject = subject
        self.grade = grade
        self.chapter = chapter
        self.date = date
        self.mode = mode
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-" + uuid.uuid4().hex[:6]
        )
        self._attempts: dict[int, dict] = {}
        self._judge: dict | None = None
        self._final: dict | None = None
        self._pipeline_agents: dict[str, dict] = {}

    # ── Accumulation ──────────────────────────────────────────────────────────

    def add_attempt(self, *, attempt, input_type, prompt, gen_csv, gen_rows,
                    check1, check2, usage=None, cost_usd=0.0) -> None:
        """Record a generator attempt and its eval checks.

        ``usage``/``cost_usd`` are the Generator's OWN call — Eval's usage already
        rides through inside ``check1``/``check2`` (see agents/eval.py), so it needs
        no separate plumbing here.
        """
        self._attempts[attempt] = {
            "attempt": attempt,
            "input_type": input_type,
            "prompt": prompt or "",
            "generator": {
                "csv": gen_csv or "",
                "rows": gen_rows,
                "check1": check1,
                "check2": check2,
                "passed": bool(check1.get("passed") and check2.get("passed")),
                "usage": usage or dict(_ZERO_USAGE),
                "cost_usd": cost_usd,
            },
            "doctors": [],
            "revision": None,
        }

    def add_doctor(self, *, attempt, kind, gaps_addressed, csv, error,
                   reeval_check1, reeval_check2, passed,
                   regressed, regressed_concepts, regressed_skills,
                   chained_from=None, usage=None, cost_usd=0.0) -> None:
        """Record one doctor pass (coverage or rules) for an attempt.

        Safe to call for a doctor that errored or produced an invalid CSV — pass
        ``csv=None`` and an ``error`` string; ``reeval_*`` may be None. ``usage``/
        ``cost_usd`` are the doctor's own corrective LLM call — the reeval's usage
        rides through inside ``reeval_check1``/``reeval_check2`` already.
        """
        # A doctor can, in principle, fire before its attempt was recorded (defensive);
        # create a stub so the entry is never dropped.
        entry = self._attempts.setdefault(attempt, {
            "attempt": attempt,
            "input_type": None,
            "prompt": "",
            "generator": None,
            "doctors": [],
            "revision": None,
        })
        entry["doctors"].append({
            "kind": kind,
            "chained_from": chained_from,
            "gaps_addressed": gaps_addressed or {},
            "csv": csv,
            "error": error,
            "reeval": None if reeval_check1 is None and reeval_check2 is None else {
                "check1": reeval_check1,
                "check2": reeval_check2,
            },
            "passed": bool(passed),
            "regressed": bool(regressed),
            "regressed_concepts": regressed_concepts or [],
            "regressed_skills": regressed_skills or [],
            "usage": usage or dict(_ZERO_USAGE),
            "cost_usd": cost_usd,
        })

    def add_revision(self, *, attempt, usage, cost_usd) -> None:
        """Record the Revision agent's LLM usage for an attempt."""
        entry = self._attempts.setdefault(attempt, {
            "attempt": attempt,
            "input_type": None,
            "prompt": "",
            "generator": None,
            "doctors": [],
            "revision": None,
        })
        entry["revision"] = {"usage": usage or dict(_ZERO_USAGE), "cost_usd": cost_usd}

    def add_pipeline_usage(self, agent: str, usage: dict, cost_usd: float) -> None:
        """Record usage for a pipeline-level agent that runs outside any attempt
        (Map Extraction, Prerequisite mapping)."""
        self._pipeline_agents[agent] = {"usage": usage or dict(_ZERO_USAGE), "cost_usd": cost_usd}

    def set_judge(self, *, selected_by, candidate_count, chosen_id, rationale,
                  candidates, usage=None, cost_usd=0.0) -> None:
        """Record how the final CSV was selected among passing candidates.

        ``candidates`` is a list of dicts each carrying at least ``id``, ``source``
        and ``cycle``; ``build()`` swaps any inline ``csv`` text for a ``csv_file``
        pointer. ``usage``/``cost_usd`` are zero when a single candidate was chosen
        without invoking the Judge agent.
        """
        self._judge = {
            "selected_by": selected_by,
            "candidate_count": candidate_count,
            "chosen_id": chosen_id,
            "rationale": rationale,
            "candidates": candidates or [],
            "usage": usage or dict(_ZERO_USAGE),
            "cost_usd": cost_usd,
        }

    def finalize(self, *, final_status, failed_check, final_csv, final_csv_name,
                 confirmed_checkpoint, has_prereqs) -> None:
        self._final = {
            "final_status": final_status,
            "failed_check": failed_check,
            "final_csv": final_csv or "",
            "final_csv_name": final_csv_name,
            "confirmed_checkpoint": bool(confirmed_checkpoint),
            "has_prereqs": bool(has_prereqs),
        }

    # ── Assembly ──────────────────────────────────────────────────────────────

    def build(self) -> tuple[dict, dict[str, str]]:
        """Return ``(record, artifacts)``.

        ``record`` is the JSON-serialisable run.json with pointer fields only.
        ``artifacts`` maps sibling filename -> file content (CSV / prompt markdown).
        """
        artifacts: dict[str, str] = {}
        attempts_out = []

        for n in sorted(self._attempts):
            a = self._attempts[n]
            prompt_file = _prompt_name(n)
            artifacts[prompt_file] = a.get("prompt", "")

            gen = a.get("generator")
            gen_out = None
            attempt_usage = dict(_ZERO_USAGE)
            attempt_cost_usd = 0.0
            if gen is not None:
                gen_file = _gen_csv_name(n)
                artifacts[gen_file] = gen.get("csv", "")
                gen_out = {
                    "csv_file": gen_file,
                    "rows": gen.get("rows"),
                    "check1": gen.get("check1"),
                    "check2": gen.get("check2"),
                    "passed": gen.get("passed", False),
                    "usage": gen.get("usage") or dict(_ZERO_USAGE),
                    "cost_usd": gen.get("cost_usd", 0.0),
                }
                attempt_usage = add_usage(attempt_usage, gen_out["usage"])
                attempt_usage = add_usage(attempt_usage, (gen.get("check1") or {}).get("usage") or {})
                attempt_usage = add_usage(attempt_usage, (gen.get("check2") or {}).get("usage") or {})
                attempt_cost_usd += (
                    gen_out["cost_usd"]
                    + (gen.get("check1") or {}).get("cost_usd", 0.0)
                    + (gen.get("check2") or {}).get("cost_usd", 0.0)
                )

            doctors_out = []
            for d in a.get("doctors", []):
                csv_text = d.get("csv")
                csv_file = None
                if csv_text:
                    csv_file = _doctored_csv_name(n, d.get("kind"))
                    artifacts[csv_file] = csv_text
                d_usage = d.get("usage") or dict(_ZERO_USAGE)
                d_cost = d.get("cost_usd", 0.0)
                reeval = d.get("reeval")
                doctors_out.append({
                    "kind": d.get("kind"),
                    "chained_from": d.get("chained_from"),
                    "gaps_addressed": d.get("gaps_addressed", {}),
                    "csv_file": csv_file,
                    "error": d.get("error"),
                    "reeval": reeval,
                    "passed": d.get("passed", False),
                    "regressed": d.get("regressed", False),
                    "regressed_concepts": d.get("regressed_concepts", []),
                    "regressed_skills": d.get("regressed_skills", []),
                    "usage": d_usage,
                    "cost_usd": d_cost,
                })
                attempt_usage = add_usage(attempt_usage, d_usage)
                attempt_cost_usd += d_cost
                if reeval:
                    attempt_usage = add_usage(attempt_usage, (reeval.get("check1") or {}).get("usage") or {})
                    attempt_usage = add_usage(attempt_usage, (reeval.get("check2") or {}).get("usage") or {})
                    attempt_cost_usd += (
                        (reeval.get("check1") or {}).get("cost_usd", 0.0)
                        + (reeval.get("check2") or {}).get("cost_usd", 0.0)
                    )

            revision = a.get("revision")
            if revision:
                attempt_usage = add_usage(attempt_usage, revision.get("usage") or {})
                attempt_cost_usd += revision.get("cost_usd", 0.0)

            attempts_out.append({
                "attempt": n,
                "input_type": a.get("input_type"),
                "prompt_file": prompt_file,
                "generator": gen_out,
                "doctors": doctors_out,
                "revision": revision,
                "produced_candidate": bool(
                    (gen_out and gen_out["passed"])
                    or any(d["passed"] for d in doctors_out)
                ),
                "attempt_usage": attempt_usage,
                "attempt_cost_usd": attempt_cost_usd,
            })

        # ── Judge (swap inline csv text for a pointer) ─────────────────────────
        judge_out = None
        if self._judge is not None:
            candidates_out = []
            for c in self._judge["candidates"]:
                candidates_out.append({
                    "id": c.get("id"),
                    "source": c.get("source"),
                    "cycle": c.get("cycle"),
                    "csv_file": _candidate_csv_name(c.get("source"), c.get("cycle")),
                    "concept_count": c.get("concept_count"),
                    "skill_count": c.get("skill_count"),
                    "verdict": c.get("verdict"),
                    "note": c.get("note", ""),
                    "strengths": c.get("strengths", []),
                    "concerns": c.get("concerns", []),
                })
            judge_out = {
                "chosen_id": self._judge["chosen_id"],
                "rationale": self._judge["rationale"],
                "candidates": candidates_out,
                "usage": self._judge.get("usage") or dict(_ZERO_USAGE),
                "cost_usd": self._judge.get("cost_usd", 0.0),
            }

        final = self._final or {
            "final_status": "escalated",
            "failed_check": None,
            "final_csv": "",
            "final_csv_name": None,
            "confirmed_checkpoint": False,
            "has_prereqs": False,
        }

        # ── Final CSV artifact ─────────────────────────────────────────────────
        final_csv_file = None
        if final.get("final_csv_name"):
            final_csv_file = final["final_csv_name"]
            artifacts[final_csv_file] = final.get("final_csv", "")

        # ── Whole-run totals — every attempt's subtotal + judge + pipeline-level
        # agents (Map Extraction, Prerequisite) that run outside any attempt ──────
        total_usage = dict(_ZERO_USAGE)
        total_cost_usd = 0.0
        for a_out in attempts_out:
            total_usage = add_usage(total_usage, a_out["attempt_usage"])
            total_cost_usd += a_out["attempt_cost_usd"]
        if judge_out is not None:
            total_usage = add_usage(total_usage, judge_out["usage"])
            total_cost_usd += judge_out["cost_usd"]
        for pipeline_entry in self._pipeline_agents.values():
            total_usage = add_usage(total_usage, pipeline_entry["usage"])
            total_cost_usd += pipeline_entry["cost_usd"]

        record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "date": self.date,
            "board": self.board,
            "subject": self.subject,
            "grade": self.grade,
            "chapter": self.chapter,
            "final_status": final["final_status"],
            "failed_check": final["failed_check"],
            "mode": self.mode,
            "selected_by": self._judge["selected_by"] if self._judge else None,
            "candidate_count": self._judge["candidate_count"] if self._judge else 0,
            "judge": judge_out,
            "final_csv_file": final_csv_file,
            "confirmed_checkpoint": final["confirmed_checkpoint"],
            "has_prereqs": final["has_prereqs"],
            "attempts": attempts_out,
            "pipeline_agents": self._pipeline_agents,
            "total_usage": total_usage,
            "total_cost_usd": total_cost_usd,
        }
        return record, artifacts
