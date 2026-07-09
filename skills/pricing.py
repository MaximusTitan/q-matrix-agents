"""
skills/pricing.py

Computes USD cost from LLM token usage. The Vercel AI Gateway's Anthropic-compatible
endpoint passes through token counts (input/output/cache) but never a dollar figure,
so cost has to be derived here from a per-model price table.

Update MODEL_PRICING whenever skills/llm.py::MODEL changes.
"""

from skills import llm

# Per-model price in USD per million tokens: (input_price, output_price).
# Keyed by the bare model id — any "provider/" gateway prefix is stripped before lookup.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
}


def _bare_model_id(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def cost_usd(usage: dict, model: str = None) -> float:
    """
    Compute the USD cost of a usage dict for the given model (defaults to llm.MODEL).

    Cache tokens are billed at the same rate as regular input tokens here — an
    intentional simplification, since this codebase does not currently use
    cache_control and those fields are always 0.
    """
    model = model or llm.MODEL
    bare_model = _bare_model_id(model)

    prices = MODEL_PRICING.get(bare_model)
    if prices is None:
        print(f"[pricing] No price entry for model '{bare_model}' — reporting $0 cost. "
              f"Add it to skills/pricing.py::MODEL_PRICING.")
        return 0.0
    price_in, price_out = prices

    input_tokens = (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
    )
    output_tokens = usage.get("output_tokens") or 0

    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out
