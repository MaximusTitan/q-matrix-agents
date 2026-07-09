"""
skills/llm.py

Thin wrapper around Claude via the Vercel AI Gateway.
All agents call LLMs through this single function.
Model, token limits, and retry logic are configured here — not in agent code.
"""

import os
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = anthropic.Anthropic(
    api_key=os.getenv("AI_GATEWAY_API_KEY"),
    base_url="https://ai-gateway.vercel.sh",
)

MODEL         = "anthropic/claude-sonnet-4-6"
MAX_TOKENS    = 8096
MAX_RETRIES   = 3
RETRY_DELAY   = 5  # seconds

_USAGE_FIELDS = (
    "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
)


def _usage_from_response(response) -> dict:
    """Extract token usage from a Message response as a plain dict."""
    usage = response.usage
    return {field: getattr(usage, field, 0) or 0 for field in _USAGE_FIELDS}


def add_usage(a: dict, b: dict) -> dict:
    """Sum two usage dicts field-by-field. Missing/None fields are treated as 0."""
    return {field: (a.get(field) or 0) + (b.get(field) or 0) for field in _USAGE_FIELDS}


def _with_retries(make_request):
    """Run make_request(), retrying transient API errors up to MAX_RETRIES times."""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return make_request()

        except anthropic.RateLimitError as e:
            last_error = e
            print(f"[llm] Rate limit hit (attempt {attempt}/{MAX_RETRIES}). "
                  f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

        except anthropic.InternalServerError as e:
            last_error = e
            print(f"[llm] Server error (attempt {attempt}/{MAX_RETRIES}). "
                  f"Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

        except anthropic.APIError:
            # Non-retryable — surface immediately
            raise

    raise RuntimeError(
        f"LLM call failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )


def call_llm(system_prompt: str, user_content: str) -> tuple[str, dict]:
    """
    Call the Anthropic API with a system prompt and user content.
    Retries up to MAX_RETRIES times on transient errors.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.

    Returns:
        (text, usage) — the model's response as a plain string, and a dict with
        input_tokens/output_tokens/cache_creation_input_tokens/cache_read_input_tokens.

    Raises:
        RuntimeError: If all retries are exhausted.
        anthropic.APIError: On non-retryable API errors.
    """
    def make_request():
        response = _client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ]
        )
        return response.content[0].text, _usage_from_response(response)

    return _with_retries(make_request)


def call_llm_structured(system_prompt: str, user_content: str, tool: dict) -> tuple[dict, dict]:
    """
    Call the Anthropic API with a single tool and force the model to call it, so the
    response is schema-shaped JSON instead of hand-formatted text the model has to
    escape/delimit itself (e.g. raw CSV, where a stray unescaped comma silently
    corrupts the row). Retries up to MAX_RETRIES times on transient errors.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.
        tool:          A single tool definition (name, description, input_schema).
                       The model is forced to call exactly this tool.

    Returns:
        (result, usage) — the tool call's input as a dict (shape matches
        tool["input_schema"]), and a dict with input_tokens/output_tokens/
        cache_creation_input_tokens/cache_read_input_tokens.

    Raises:
        RuntimeError: If all retries are exhausted, or the response has no tool_use
                      block (forcing tool_choice makes this exceedingly unlikely).
        anthropic.APIError: On non-retryable API errors.
    """
    def make_request():
        response = _client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[
                {"role": "user", "content": user_content}
            ]
        )
        usage = _usage_from_response(response)
        for block in response.content:
            if block.type == "tool_use":
                return block.input, usage
        raise RuntimeError(
            f"Model response had no tool_use block (stop_reason={response.stop_reason})."
        )

    return _with_retries(make_request)
