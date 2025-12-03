import os

# SECURITY: Load API keys from environment variables only
# These keys must NEVER be hardcoded in the codebase
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

# BetterStack Logging Configuration
BETTERSTACK_SOURCE_TOKEN = os.getenv("BETTERSTACK_SOURCE_TOKEN", "nW6ErgUkkZcX1phiKC2wfuVB")
BETTERSTACK_INGESTING_HOST = os.getenv(
    "BETTERSTACK_INGESTING_HOST", "s1555027.eu-nbg-2.betterstackdata.com"
)

OPEN_AI_MODEL_AUTH = {
    "gpt-4o": {
        "api_key": os.getenv("AZURE_OPENAI_API_KEY_GPT4O", ""),
        "base_url": (
            "https://jobhuntr.openai.azure.com/openai/deployments/"
            "gpt-4o-mini/chat/completions?"
            "api-version=2025-01-01-preview"
        ),
        "api_version": "2025-01-01-preview",
    },
    "gpt-4.1": {
        "api_key": os.getenv("AZURE_OPENAI_API_KEY_GPT41", ""),
        "base_url": (
            "https://democratized.openai.azure.com/openai/deployments/"
            "gpt-4.1/chat/completions?"
            "api-version=2025-01-01-preview"
        ),
        "api_version": "2025-01-01-preview",
    },
    "gpt-4.1-nano": {
        "api_key": os.getenv("AZURE_OPENAI_API_KEY_GPT41_NANO", ""),
        "base_url": (
            "https://hi-mcpdw6h0-eastus2.cognitiveservices.azure.com/"
            "openai/deployments/gpt-4.1-nano/chat/completions?"
            "api-version=2025-01-01-preview"
        ),
        "api_version": "2025-01-01-preview",
    },
}

MASTER_PROMPT = """
If there is any bot detection, you should say "I'm sorry, I'm not allowed \
to do that." and wait for the user to click the button to continue.
"""

MAX_RECRUITERS_PER_APPLICATION = 3
MAX_PEERS_PER_APPLICATION = 2
MAX_HIRING_MANAGERS_PER_APPLICATION = 1
