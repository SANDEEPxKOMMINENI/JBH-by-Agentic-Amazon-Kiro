"""Cost calculation utilities for autonomous search bot."""

import logging
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# LiteLLM pricing JSON URL
LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

# Cache for pricing data
_pricing_cache: Optional[Dict[str, Any]] = None


def load_pricing_data() -> Dict[str, Any]:
    """Load pricing data from LiteLLM pricing JSON with caching"""
    global _pricing_cache
    if _pricing_cache is not None:
        return _pricing_cache

    try:
        response = httpx.get(LITELLM_PRICING_URL, timeout=10.0)
        response.raise_for_status()
        _pricing_cache = response.json()
        return _pricing_cache
    except Exception as e:
        logger.warning(f"Failed to load pricing data: {e}. Using fallback pricing.")
        _pricing_cache = {}
        return _pricing_cache


def get_model_pricing_key(provider: str, model: str) -> str:
    """Convert provider and model to LiteLLM pricing JSON key format"""
    provider_lower = (provider or "").lower().strip()

    # Map provider names to LiteLLM prefixes
    if provider_lower == "azure":
        return f"azure/{model}"
    elif provider_lower == "openai":
        return model  # OpenAI models are keyed directly
    elif provider_lower in ("anthropic", "claude"):
        # Anthropic models are prefixed with "anthropic/"
        return f"anthropic/{model}"
    elif provider_lower in ("google", "gemini"):
        # Google models are prefixed with "google/" or "gemini/"
        if model.startswith("gemini-"):
            return model  # Some gemini models are keyed directly
        return f"google/{model}"
    elif provider_lower in ("browseruse", "browser_use"):
        # Browser-use models might not be in pricing JSON
        return model
    else:
        # Try provider/model format
        return f"{provider_lower}/{model}"


def get_pricing_for_model(provider: str, model: str) -> Tuple[float, float]:
    """
    Get pricing for a model from LiteLLM pricing JSON.
    Returns (input_cost_per_1k_tokens, output_cost_per_1k_tokens)
    Falls back to default GPT-4 pricing if not found.
    """
    pricing_data = load_pricing_data()
    if not pricing_data:
        # Fallback to GPT-4 pricing
        return (0.03, 0.06)

    # Try multiple key formats
    possible_keys = [
        get_model_pricing_key(provider, model),
        model,  # Try direct model name
        f"{provider}/{model}" if provider else model,
    ]

    # Also try with common variations
    if provider and provider.lower() == "azure":
        possible_keys.extend(
            [
                f"azure/{model}",
                model.replace("gpt-4", "gpt-4"),  # Keep as-is
            ]
        )

    for key in possible_keys:
        if key in pricing_data:
            model_info = pricing_data[key]
            input_cost_per_token = model_info.get("input_cost_per_token", 0.0)
            output_cost_per_token = model_info.get("output_cost_per_token", 0.0)

            # Convert from per-token to per-1k-tokens
            input_cost_per_1k = (
                input_cost_per_token * 1000 if input_cost_per_token else 0.0
            )
            output_cost_per_1k = (
                output_cost_per_token * 1000 if output_cost_per_token else 0.0
            )

            if input_cost_per_1k > 0 or output_cost_per_1k > 0:
                logger.debug(
                    f"Found pricing for {key}: "
                    f"input=${input_cost_per_1k:.6f}/1k, "
                    f"output=${output_cost_per_1k:.6f}/1k"
                )
                return (input_cost_per_1k, output_cost_per_1k)

    # Fallback pricing based on model name patterns
    model_lower = model.lower()
    if "gpt-3.5" in model_lower or "gpt-35" in model_lower:
        return (0.0015, 0.002)
    elif "gpt-4" in model_lower:
        return (0.03, 0.06)
    elif "claude" in model_lower:
        # Claude pricing varies, use a reasonable default
        return (0.015, 0.075)
    elif "gemini" in model_lower:
        # Gemini pricing varies, use a reasonable default
        return (0.000125, 0.0005)

    # Ultimate fallback: GPT-4 pricing
    logger.debug(f"No pricing found for {provider}/{model}, using GPT-4 fallback")
    return (0.03, 0.06)


def calculate_cost_from_tokens(
    input_tokens: int,
    output_tokens: int,
    provider: str,
    model: str,
) -> float:
    """
    Calculate cost from token counts using model-specific pricing.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        provider: LLM provider name (e.g., 'openai', 'azure')
        model: Model name (e.g., 'gpt-4', 'gpt-3.5-turbo')

    Returns:
        Total cost in USD
    """
    input_cost_per_1k, output_cost_per_1k = get_pricing_for_model(provider, model)

    input_cost = (input_tokens / 1000) * input_cost_per_1k
    output_cost = (output_tokens / 1000) * output_cost_per_1k

    return input_cost + output_cost
