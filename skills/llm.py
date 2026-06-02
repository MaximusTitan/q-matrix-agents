"""
skills/llm.py

Thin wrapper around the Anthropic API.
All agents call LLMs through this single function.
Model, token limits, and retry logic are configured here — not in agent code.
"""

import os
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL         = "claude-sonnet-4-20250514"
MAX_TOKENS    = 8096
MAX_RETRIES   = 3
RETRY_DELAY   = 5  # seconds


def call_llm(system_prompt: str, user_content: str) -> str:
    """
    Call the Anthropic API with a system prompt and user content.
    Retries up to MAX_RETRIES times on transient errors.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.

    Returns:
        The model's response as a plain string.

    Raises:
        RuntimeError: If all retries are exhausted.
        anthropic.APIError: On non-retryable API errors.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content}
                ]
            )
            return response.content[0].text

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

        except anthropic.APIError as e:
            # Non-retryable — surface immediately
            raise

    raise RuntimeError(
        f"LLM call failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )
