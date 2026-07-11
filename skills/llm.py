"""
skills/llm.py

Thin wrapper around the Vercel AI Gateway's OpenAI Chat Completions-compatible
endpoint. This shape (rather than the Anthropic Messages-compatible endpoint) is what
lets a single client talk to any provider the Gateway exposes — Anthropic, OpenAI,
Google, Meta, Mistral, DeepSeek, etc. — with forced tool-choice working identically
across all of them, confirmed against the live endpoint.

All agents call LLMs through this single function. Retry logic is configured here —
not in agent code. Model choice is per-call (see `model=`) so each agent can be
pointed at a different model/provider; DEFAULT_MODEL is only the fallback.
"""

import json
import os
import time
import openai
from dotenv import load_dotenv

load_dotenv()

_client = openai.OpenAI(
    api_key=os.getenv("AI_GATEWAY_API_KEY"),
    base_url="https://ai-gateway.vercel.sh/v1",
)

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
MAX_TOKENS    = 8096
MAX_RETRIES   = 3
RETRY_DELAY   = 5  # seconds

_USAGE_FIELDS = (
    "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
)


def _usage_from_response(response) -> tuple[dict, float]:
    """Extract (usage, cost_usd) from a ChatCompletion response.

    The Gateway augments the standard OpenAI `usage` object with its own
    Anthropic-style cache fields and a pre-computed `cost` — already priced for
    whichever provider actually served the request, so no local price table is
    needed for any model.
    """
    usage = response.usage
    cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
    return (
        {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": cached,
        },
        float(getattr(usage, "cost", 0) or 0),
    )


def add_usage(a: dict, b: dict) -> dict:
    """Sum two usage dicts field-by-field. Missing/None fields are treated as 0."""
    return {field: (a.get(field) or 0) + (b.get(field) or 0) for field in _USAGE_FIELDS}


def _with_retries(make_request):
    """Run make_request(), retrying transient API errors up to MAX_RETRIES times."""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return make_request()

        except openai.RateLimitError as e:
            last_error = e
            print(f"[llm] Rate limit hit (attempt {attempt}/{MAX_RETRIES}). "
                  f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

        except openai.InternalServerError as e:
            last_error = e
            print(f"[llm] Server error (attempt {attempt}/{MAX_RETRIES}). "
                  f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

        except openai.APIError:
            # Non-retryable — surface immediately
            raise

    raise RuntimeError(
        f"LLM call failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )


def call_llm(system_prompt: str, user_content: str, model: str = DEFAULT_MODEL) -> tuple[str, dict, float]:
    """
    Call an LLM through the Gateway with a system prompt and user content.
    Retries up to MAX_RETRIES times on transient errors.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.
        model:         Gateway model id, e.g. "anthropic/claude-sonnet-4-6",
                       "openai/gpt-5-mini", "google/gemini-2.5-flash".

    Returns:
        (text, usage, cost_usd) — the model's response as a plain string, a dict with
        input_tokens/output_tokens/cache_creation_input_tokens/cache_read_input_tokens,
        and the Gateway-computed USD cost of this call.

    Raises:
        RuntimeError: If all retries are exhausted.
        openai.APIError: On non-retryable API errors.
    """
    def make_request():
        response = _client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        usage, cost_usd = _usage_from_response(response)
        return response.choices[0].message.content, usage, cost_usd

    return _with_retries(make_request)


def call_llm_structured(
    system_prompt: str, user_content: str, tool: dict, model: str = DEFAULT_MODEL
) -> tuple[dict, dict, float]:
    """
    Call an LLM through the Gateway with a single tool and force the model to call it,
    so the response is schema-shaped JSON instead of hand-formatted text the model has
    to escape/delimit itself (e.g. raw CSV, where a stray unescaped comma silently
    corrupts the row). Retries up to MAX_RETRIES times on transient errors.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.
        tool:          A single tool definition (name, description, input_schema).
                       The model is forced to call exactly this tool.
        model:         Gateway model id. Must support tool use (the Gateway's model
                       catalog tags these "tool-use").

    Returns:
        (result, usage, cost_usd) — the tool call's input as a dict (shape matches
        tool["input_schema"]), the token-usage dict, and the Gateway-computed USD cost.

    Raises:
        RuntimeError: If all retries are exhausted, or the response has no tool call
                      (forcing tool_choice makes this exceedingly unlikely).
        openai.APIError: On non-retryable API errors.
    """
    def make_request():
        response = _client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            }],
            tool_choice={"type": "function", "function": {"name": tool["name"]}},
        )
        usage, cost_usd = _usage_from_response(response)
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            raise RuntimeError(
                f"Model response had no tool call (finish_reason={response.choices[0].finish_reason})."
            )
        return json.loads(tool_calls[0].function.arguments), usage, cost_usd

    return _with_retries(make_request)
