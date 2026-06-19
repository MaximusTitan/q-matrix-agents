"""
skills/llm.py

Thin wrapper around Anthropic models served via Vercel's AI Gateway.
All agents call LLMs through this single function.
Model, token limits, and retry logic are configured here — not in agent code.

The gateway exposes an OpenAI-compatible API, so we use the OpenAI SDK pointed
at the gateway base URL and authenticate with the Vercel AI Gateway key
(AI_GATEWAY_API_KEY) instead of a per-provider BYOK key.
"""

import os
import time
import openai
from dotenv import load_dotenv

load_dotenv()

_client = openai.OpenAI(
    api_key=os.getenv("AI_GATEWAY_API_KEY"),
    base_url="https://ai-gateway.vercel.sh/v1",
)

# Provider-namespaced model id for the gateway.
MODEL         = "anthropic/claude-sonnet-4-6"
MAX_TOKENS    = 8096
MAX_RETRIES   = 3
RETRY_DELAY   = 5  # seconds


def call_llm(system_prompt: str, user_content: str) -> str:
    """
    Call the model (Anthropic, via the Vercel AI Gateway) with a system prompt
    and user content. Retries up to MAX_RETRIES times on transient errors.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.

    Returns:
        The model's response as a plain string.

    Raises:
        RuntimeError: If all retries are exhausted.
        openai.APIError: On non-retryable API errors.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            return response.choices[0].message.content

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
