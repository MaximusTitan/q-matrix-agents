"""
skills/llm.py

Thin wrapper around the Vercel AI Gateway (via OpenAI-compatible SDK).
All agents call LLMs through this single function.
Model, token limits, and retry logic are configured here — not in agent code.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize the client pointing to Vercel AI Gateway
_client = OpenAI(
    api_key=os.getenv("AI_GATEWAY_API_KEY"),
    base_url="https://ai-gateway.vercel.sh/v1"
)

# Default model, can be overridden by passing model to call_llm
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
MAX_TOKENS    = 8096

PRICE_PER_MILLION_TOKENS = {
    "openai/gpt-4o": {
        "input":  2.50,
        "output": 10.00,
    },
    "anthropic/claude-3-5-sonnet-20241022": {
        "input":  3.00,
        "output": 15.00,
    },
}

BILLING_MODEL_ALIASES = {
    "gpt-4o": "openai/gpt-4o",
    "anthropic/claude-sonnet-4.5": "anthropic/claude-3-5-sonnet-20241022",
    "claude-sonnet-4.5": "anthropic/claude-3-5-sonnet-20241022",
}


def _extract_usage(response, model_name: str) -> dict:
    usage_obj = None
    if hasattr(response, "usage"):
        usage_obj = response.usage
    elif isinstance(response, dict):
        usage_obj = response.get("usage")

    def _get_token(field: str) -> int:
        if usage_obj is None:
            return 0
        value = getattr(usage_obj, field, None)
        if value is None and isinstance(usage_obj, dict):
            value = usage_obj.get(field)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    prompt_tokens = _get_token("prompt_tokens")
    completion_tokens = _get_token("completion_tokens")
    total_tokens = _get_token("total_tokens") or prompt_tokens + completion_tokens

    cost = 0.0
    billing_model = BILLING_MODEL_ALIASES.get(model_name, model_name)
    rates = PRICE_PER_MILLION_TOKENS.get(billing_model)
    if rates is not None:
        cost = (
            prompt_tokens * rates["input"] + completion_tokens * rates["output"]
        ) / 1_000_000.0

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost": cost,
    }


def call_llm(system_prompt: str, user_content: str, model: str = None) -> tuple[str, dict]:
    """
    Call the AI Gateway with a system prompt and user content.

    Args:
        system_prompt: The agent's system-level instructions.
        user_content:  The content the agent should act on.
        model:         The specific model to use (e.g., 'anthropic/claude-sonnet-4.5').

    Returns:
        Tuple containing the model's response as a plain string and usage metadata.
    """
    target_model = model or DEFAULT_MODEL
    
    # Map frontend display strings to the gateway model IDs that exist today.
    model_mapping = {
        "openai/gpt-4o": "openai/gpt-4o",
        "gpt-4o": "openai/gpt-4o",
        "anthropic/claude-3-5-sonnet-20241022": "anthropic/claude-sonnet-4.5",
        "anthropic/claude-sonnet-4.5": "anthropic/claude-sonnet-4.5",
        "claude-sonnet-4.5": "anthropic/claude-sonnet-4.5",
    }
    
    gateway_model = model_mapping.get(target_model, target_model)
    
    response = _client.chat.completions.create(
        model=gateway_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        max_tokens=MAX_TOKENS
    )
    
    usage = _extract_usage(response, target_model)
    return response.choices[0].message.content, usage