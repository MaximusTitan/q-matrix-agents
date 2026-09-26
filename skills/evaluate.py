"""
skills/evaluate.py

Thin wrapper around the Vercel AI Gateway's evaluation endpoint (`POST /v1/evaluate`),
used by agents whose job is a decision rather than a piece of writing.

Evaluation models (e.g. TypeSafe's Jev) do not generate text. They answer typed
questions about a shared `state`:

    boolean — a probability in [0, 1] that the answer is "yes"
    choice  — one option out of a named set (≤255), plus a probability per option
    score   — a position on an ordered rubric, plus a probability per rung

The Gateway does NOT serve these models on its OpenAI-compatible endpoint, which is why
this lives beside skills/llm.py rather than inside it. Agents keep their chat-LLM path
and branch on `is_evaluation_model(model)`, so a per-agent `models` override can still
point any of them back at a chat model.

Retry behaviour mirrors skills/llm.py: transient errors (429, 5xx, 529) are retried up
to MAX_RETRIES times; everything else surfaces immediately.
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from dotenv import load_dotenv

from skills.llm import MAX_RETRIES, RETRY_DELAY, add_usage

load_dotenv()

JEV_MODEL    = "typesafe-ai/jev"
EVALUATE_URL = "https://ai-gateway.vercel.sh/v1/evaluate"
TIMEOUT_S    = 60

# Jev's limits: 32k tokens for `state` plus the longest question, 64k for the whole
# request. Token counts are estimated as chars/3 (deliberately pessimistic for
# English/JSON), with headroom kept under both hard limits.
STATE_TOKEN_BUDGET   = 30_000
REQUEST_TOKEN_BUDGET = 56_000
MAX_CHOICE_OPTIONS = 255
# Questions sharing one state are batched into a single request up to this many (and
# up to REQUEST_TOKEN_BUDGET). 512 was accepted in a live probe on 2026-09-27.
MAX_QUESTIONS_PER_REQUEST = 256
MAX_PARALLEL_REQUESTS = 8

_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


class EvaluationError(RuntimeError):
    """An evaluation request failed (non-retryable status, or retries exhausted)."""


def is_evaluation_model(model: str | None) -> bool:
    """True for Gateway model ids served by the evaluation endpoint."""
    return (model or "").startswith("typesafe-ai/")


def estimate_tokens(value) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return len(text) // 3 + 1


# ── Question builders ─────────────────────────────────────────────────────────

def boolean(instructions: str, true: str | None = None, false: str | None = None) -> dict:
    q = {"type": "boolean", "instructions": instructions}
    if true or false:
        q["criteria"] = {"true": true or "", "false": false or ""}
    return q


def choice(instructions: str, options: dict[str, str]) -> dict:
    if not 2 <= len(options) <= MAX_CHOICE_OPTIONS:
        raise ValueError(f"choice needs 2..{MAX_CHOICE_OPTIONS} options, got {len(options)}")
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score(instructions: str, levels: list[str]) -> dict:
    if len(levels) < 2:
        raise ValueError("score needs at least 2 levels")
    return {"type": "score", "instructions": instructions, "criteria": levels}


# ── Answer readers ────────────────────────────────────────────────────────────

def probability(answer: dict) -> float:
    """Probability of "yes" from a boolean answer (TypeSafe's native shape calls it `noul`)."""
    value = answer.get("probability", answer.get("noul"))
    if value is None:
        raise EvaluationError(f"boolean answer has no probability: {answer!r}")
    return float(value)


# ── Transport ─────────────────────────────────────────────────────────────────

def _usage_from_body(body: dict) -> tuple[dict, float]:
    usage = body.get("usage") or {}
    gateway = (body.get("providerMetadata") or {}).get("gateway") or {}
    return (
        {
            "input_tokens": usage.get("inputTokens", usage.get("input_tokens", 0)) or 0,
            "output_tokens": usage.get("outputTokens", usage.get("output_tokens", 0)) or 0,
        },
        float(gateway.get("cost") or 0),
    )


def _error_message(response: httpx.Response) -> str:
    try:
        return (response.json().get("error") or {}).get("message") or response.text[:300]
    except ValueError:
        return response.text[:300]


def call_evaluate(state, questions: dict[str, dict], model: str = JEV_MODEL) -> tuple[dict, dict, float]:
    """
    Evaluate `questions` against `state` in one request.

    Args:
        state:     str, dict or list — the content every question is asked about.
        questions: {question_id: question} built with boolean()/choice()/score().
        model:     Gateway evaluation model id.

    Returns:
        (answers, usage, cost_usd) — answers keyed by question id, the token-usage dict,
        and the Gateway-computed USD cost.

    Raises:
        ValueError:      state + longest question exceeds STATE_TOKEN_BUDGET.
        EvaluationError: non-retryable HTTP status, or retries exhausted.
    """
    if not questions:
        return {}, {}, 0.0
    longest = max(estimate_tokens(q) for q in questions.values())
    if estimate_tokens(state) + longest > STATE_TOKEN_BUDGET:
        raise ValueError(
            f"evaluation state too large (~{estimate_tokens(state) + longest} tokens, "
            f"budget {STATE_TOKEN_BUDGET}); split the state before calling"
        )

    api_key = os.getenv("AI_GATEWAY_API_KEY")
    if not api_key:
        raise EvaluationError("AI_GATEWAY_API_KEY is not set")

    body = {"model": model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {api_key}"}
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = httpx.post(EVALUATE_URL, headers=headers, json=body, timeout=TIMEOUT_S)
        except httpx.TransportError as e:
            last_error = f"{type(e).__name__}: {e}"
        else:
            if response.status_code == 200:
                data = response.json()
                answers = data.get("answers") or {}
                missing = set(questions) - set(answers)
                if missing:
                    raise EvaluationError(f"evaluation response missing answers for {sorted(missing)[:5]}")
                usage, cost_usd = _usage_from_body(data)
                return answers, usage, cost_usd
            last_error = f"HTTP {response.status_code}: {_error_message(response)}"
            if response.status_code not in _RETRYABLE_STATUS:
                raise EvaluationError(last_error)

        print(f"[evaluate] {last_error} (attempt {attempt}/{MAX_RETRIES}). "
              f"Retrying in {RETRY_DELAY}s...")
        time.sleep(RETRY_DELAY)

    raise EvaluationError(f"Evaluation failed after {MAX_RETRIES} attempts. Last error: {last_error}")


def evaluate_many(
    requests: list[tuple[object, dict[str, dict]]], model: str = JEV_MODEL,
) -> tuple[dict, dict, float]:
    """
    Run several (state, questions) requests in parallel and merge their answers.

    Question maps larger than MAX_QUESTIONS_PER_REQUEST, or whose estimated size would
    exceed REQUEST_TOKEN_BUDGET, are split into several requests against the same state.
    Question ids must be unique across all requests.

    Returns:
        (answers, usage, cost_usd) summed over every request.

    Raises:
        ValueError / EvaluationError from call_evaluate — one failed request fails the batch.
    """
    jobs = []
    seen_ids: set[str] = set()
    for state, questions in requests:
        dupes = seen_ids & questions.keys()
        if dupes:
            raise ValueError(f"duplicate question ids across requests: {sorted(dupes)[:5]}")
        seen_ids |= questions.keys()
        state_tokens = estimate_tokens(state)
        chunk, chunk_tokens = {}, state_tokens
        for qid, question in questions.items():
            q_tokens = estimate_tokens(question)
            if chunk and (len(chunk) >= MAX_QUESTIONS_PER_REQUEST
                          or chunk_tokens + q_tokens > REQUEST_TOKEN_BUDGET):
                jobs.append((state, chunk))
                chunk, chunk_tokens = {}, state_tokens
            chunk[qid] = question
            chunk_tokens += q_tokens
        if chunk:
            jobs.append((state, chunk))

    answers: dict = {}
    usage_total: dict = {}
    cost_total = 0.0
    if not jobs:
        return answers, usage_total, cost_total

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_REQUESTS, len(jobs))) as pool:
        for got, usage, cost in pool.map(lambda job: call_evaluate(job[0], job[1], model), jobs):
            answers.update(got)
            usage_total = add_usage(usage_total, usage)
            cost_total += cost
    return answers, usage_total, cost_total
