"""
skills/model_stats.py

Aggregates persisted run records (skills/kb_access.py::list_all_run_records) into
per-(agent, model) performance stats for the analytics dashboard's Model Performance
section — pass/fail rates and cost/token/row averages per agent-model configuration,
answering "which model actually performs best for this agent, across every run we've
done so far."

Pure aggregation — no filesystem access, no knowledge of KB layout. That belongs to
skills/kb_access.py; this module only knows the run_record.py schema shape.
"""

from skills.llm import add_usage

_ZERO_USAGE = {
    "input_tokens": 0, "output_tokens": 0,
    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
}


class _Bucket:
    """Accumulates one (agent, model) pair's stats across every run it appears in."""

    def __init__(self):
        self.runs = 0
        self.passed = 0
        self.escalated = 0
        self.total_cost_usd = 0.0
        self.total_usage = dict(_ZERO_USAGE)
        self.rows_sum = 0
        self.rows_count = 0  # only Generator populates this
        self.last_used = None  # ISO date string, max() over runs

    def add_run(self, *, passed: bool, cost_usd: float, usage: dict, date: str, rows: int | None):
        self.runs += 1
        if passed:
            self.passed += 1
        else:
            self.escalated += 1
        self.total_cost_usd += cost_usd
        self.total_usage = add_usage(self.total_usage, usage)
        if rows is not None:
            self.rows_sum += rows
            self.rows_count += 1
        if date and (self.last_used is None or date > self.last_used):
            self.last_used = date

    def to_entry(self, agent: str, model: str) -> dict:
        avg_usage = {
            field: (self.total_usage.get(field, 0) / self.runs if self.runs else 0)
            for field in _ZERO_USAGE
        }
        return {
            "agent": agent,
            "model": model,
            "runs": self.runs,
            "passed": self.passed,
            "escalated": self.escalated,
            "pass_rate": (self.passed / self.runs) if self.runs else 0.0,
            "total_cost_usd": self.total_cost_usd,
            "avg_cost_usd": (self.total_cost_usd / self.runs) if self.runs else 0.0,
            "avg_usage": avg_usage,
            "avg_rows": (self.rows_sum / self.rows_count) if self.rows_count else None,
            "last_used": self.last_used,
        }


def _sum_attempt_usage_cost(entries: list[dict]) -> tuple[dict, float]:
    """Sum usage/cost_usd across a list of dicts that each carry those two keys
    (e.g. every doctor entry of one kind across a run's attempts)."""
    usage = dict(_ZERO_USAGE)
    cost = 0.0
    for e in entries:
        usage = add_usage(usage, e.get("usage") or {})
        cost += e.get("cost_usd", 0.0) or 0.0
    return usage, cost


def _first_model(entries: list[dict]) -> str | None:
    """The model is constant for a given agent across every attempt in one run
    (chosen once via the `models` dict passed into run_pipeline) — take the first
    non-null one seen."""
    for e in entries:
        if e.get("model"):
            return e["model"]
    return None


def record_models(rec: dict) -> set[str]:
    """
    Every distinct model identifier touched by one run record, across every agent
    that participated (generator, eval checks, doctor/rules-doctor, revision,
    judge, map extraction, prerequisite).

    Used to answer "was this model involved in producing this chapter" for the
    KB analytics model filter — unlike compute_model_performance, this doesn't
    need pass/cost/usage per agent, just the flat set of models involved.
    """
    models: set[str] = set()
    attempts = rec.get("attempts") or []

    for a in attempts:
        gen = a.get("generator")
        if gen:
            if gen.get("model"):
                models.add(gen["model"])
            for check_key in ("check1", "check2"):
                check = gen.get(check_key)
                if check and check.get("model"):
                    models.add(check["model"])
        rev = a.get("revision")
        if rev and rev.get("model"):
            models.add(rev["model"])
        for d in a.get("doctors") or []:
            if d.get("model"):
                models.add(d["model"])

    judge = rec.get("judge")
    if judge and judge.get("model"):
        models.add(judge["model"])

    pipeline_agents = rec.get("pipeline_agents") or {}
    for entry in pipeline_agents.values():
        if entry and entry.get("model"):
            models.add(entry["model"])

    return models


def compute_model_performance(records: list[dict]) -> dict:
    """
    Args:
        records: Every run.json dict, e.g. from kb_access.list_all_run_records().

    Returns:
        {
          "total_runs": int,
          "total_cost_usd": float,
          "distinct_models": int,
          "by_provider": [{"provider", "runs", "total_cost_usd"}, ...],  # cost desc
          "entries": [ModelPerformanceEntry, ...],  # grouped by agent, runs desc within
        }
    """
    buckets: dict[tuple[str, str], _Bucket] = {}

    def bucket(agent: str, model: str) -> _Bucket:
        key = (agent, model)
        if key not in buckets:
            buckets[key] = _Bucket()
        return buckets[key]

    for rec in records:
        passed = rec.get("final_status") == "passed"
        date = rec.get("date") or ""
        attempts = rec.get("attempts") or []

        # ── Generator ──────────────────────────────────────────────────────
        gens = [a["generator"] for a in attempts if a.get("generator")]
        gen_model = _first_model(gens)
        if gen_model:
            usage, cost = _sum_attempt_usage_cost(gens)
            rows = sum(g.get("rows") or 0 for g in gens)
            bucket("generator", gen_model).add_run(
                passed=passed, cost_usd=cost, usage=usage, date=date, rows=rows
            )

        # ── Eval (Check 1 + Check 2 combined) ──────────────────────────────
        checks = []
        for g in gens:
            if g.get("check1"):
                checks.append(g["check1"])
            if g.get("check2"):
                checks.append(g["check2"])
        eval_model = _first_model(checks)
        if eval_model:
            usage, cost = _sum_attempt_usage_cost(checks)
            bucket("eval", eval_model).add_run(
                passed=passed, cost_usd=cost, usage=usage, date=date, rows=None
            )

        # ── Doctor / Rules Doctor (split by kind) ──────────────────────────
        doctors = [d for a in attempts for d in (a.get("doctors") or [])]
        for kind, agent_key in (("coverage", "doctor"), ("rules", "rules_doctor")):
            kind_entries = [d for d in doctors if d.get("kind") == kind]
            model = _first_model(kind_entries)
            if model:
                usage, cost = _sum_attempt_usage_cost(kind_entries)
                bucket(agent_key, model).add_run(
                    passed=passed, cost_usd=cost, usage=usage, date=date, rows=None
                )

        # ── Revision ────────────────────────────────────────────────────────
        revisions = [a["revision"] for a in attempts if a.get("revision")]
        rev_model = _first_model(revisions)
        if rev_model:
            usage, cost = _sum_attempt_usage_cost(revisions)
            bucket("revision", rev_model).add_run(
                passed=passed, cost_usd=cost, usage=usage, date=date, rows=None
            )

        # ── Judge (only present when it actually ran) ──────────────────────
        judge = rec.get("judge")
        if judge and judge.get("model"):
            bucket("judge", judge["model"]).add_run(
                passed=passed, cost_usd=judge.get("cost_usd", 0.0),
                usage=judge.get("usage") or {}, date=date, rows=None,
            )

        # ── Map Extraction / Prerequisite L1 / Prerequisite L2 / Prerequisite L3
        #    (pipeline-level, not per-attempt) ──────────────────────────────
        pipeline_agents = rec.get("pipeline_agents") or {}
        for agent_key in ("map_extraction", "prerequisite", "prerequisite_l2", "prerequisite_l3"):
            entry = pipeline_agents.get(agent_key)
            if entry and entry.get("model"):
                bucket(agent_key, entry["model"]).add_run(
                    passed=passed, cost_usd=entry.get("cost_usd", 0.0),
                    usage=entry.get("usage") or {}, date=date, rows=None,
                )

    entries = [b.to_entry(agent, model) for (agent, model), b in buckets.items()]
    entries.sort(key=lambda e: (e["agent"], -e["runs"]))

    provider_totals: dict[str, dict] = {}
    for e in entries:
        provider = e["model"].split("/", 1)[0]
        p = provider_totals.setdefault(provider, {"provider": provider, "runs": 0, "total_cost_usd": 0.0})
        p["runs"] += e["runs"]
        p["total_cost_usd"] += e["total_cost_usd"]
    by_provider = sorted(provider_totals.values(), key=lambda p: -p["total_cost_usd"])

    return {
        "total_runs": len(records),
        "total_cost_usd": sum(r.get("total_cost_usd") or 0.0 for r in records),
        "distinct_models": len({e["model"] for e in entries}),
        "by_provider": by_provider,
        "entries": entries,
    }
