"""
config/llm_config.py

LLM provider configuration.
Change model names here — never in .env.
"""

# ---------------------------------------------------------------------------
# OpenAI model settings
# To switch providers, add a new section here and update AskLLM provider.
# ---------------------------------------------------------------------------

LLM_MODEL: str = "gpt-4o-mini"

# Temperature — keep at 0.0 for deterministic JSON output
TEMPERATURE: float = 0.0

# ---------------------------------------------------------------------------
# Token / character budgets
# ---------------------------------------------------------------------------

# Maximum characters in the JSON payload sent to LLM for entry decisions.
# Compact JSON with short keys stays well under 2500 chars.
MAX_INPUT_CHARS_ENTRY: int = 2_500

# Maximum characters in the JSON payload sent to LLM for exit decisions.
MAX_INPUT_CHARS_EXIT: int = 1_800

# Maximum tokens allowed in the LLM response for entry decisions.
MAX_OUTPUT_TOKENS_ENTRY: int = 220

# Maximum tokens allowed in the LLM response for exit decisions.
MAX_OUTPUT_TOKENS_EXIT: int = 160

# ---------------------------------------------------------------------------
# Retry / resilience
# ---------------------------------------------------------------------------

LLM_MAX_RETRIES: int = 3          # retries on transient errors
LLM_RETRY_WAIT_SECONDS: float = 2.0
LLM_TIMEOUT_SECONDS: int = 30     # hard timeout per call
