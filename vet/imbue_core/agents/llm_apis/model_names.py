import enum


class AnthropicModelName(enum.StrEnum):
    CLAUDE_3_HAIKU_2024_03_07 = "claude-3-haiku-20240307"
    CLAUDE_3_OPUS_2024_02_29 = "claude-3-opus-20240229"
    CLAUDE_3_5_SONNET_2024_06_20 = "claude-3-5-sonnet-20240620"
    CLAUDE_3_5_SONNET_2024_10_22 = "claude-3-5-sonnet-20241022"
    CLAUDE_3_5_HAIKU_2024_10_22 = "claude-3-5-haiku-20241022"
    CLAUDE_3_7_SONNET_2025_02_19 = "claude-3-7-sonnet-20250219"
    CLAUDE_4_OPUS_2025_05_14 = "claude-opus-4-20250514"
    CLAUDE_4_1_OPUS_2025_08_05 = "claude-opus-4-1-20250805"
    CLAUDE_4_SONNET_2025_05_14 = "claude-sonnet-4-20250514"
    CLAUDE_4_5_SONNET_2025_09_29 = "claude-sonnet-4-5-20250929"
    CLAUDE_4_5_HAIKU_2025_10_01 = "claude-haiku-4-5-20251001"
    CLAUDE_4_5_OPUS_2025_11_01 = "claude-opus-4-5-20251101"
    CLAUDE_4_6_OPUS = "claude-opus-4-6"
    # the same as above but with the token limit and cost per token for the 1M token limit
    # TODO: combine these and add ability for token costs to be nonlinear
    # FIXME: this is an exception where the model name is not the same as the model name in the API
    CLAUDE_4_SONNET_2025_05_14_LONG = "claude-sonnet-4-20250514-long"
    CLAUDE_4_5_SONNET_2025_09_29_LONG = "claude-sonnet-4-5-20250929-long"
    CLAUDE_4_6_OPUS_LONG = "claude-opus-4-6-long"

    # the following are 'retired' and are no longer available: https://docs.claude.com/en/docs/about-claude/model-deprecations
    # CLAUDE_2_1 = "claude-2.1"
    # CLAUDE_2 = "claude-2"
    # CLAUDE_3_SONNET_2024_02_29 = "claude-3-sonnet-20240229"


class OpenAIModelName(enum.StrEnum):
    GPT_3_5_TURBO = "gpt-3.5-turbo-0125"
    GPT_4_0613 = "gpt-4-0613"
    GPT_4_1106_PREVIEW = "gpt-4-1106-preview"
    GPT_4_0125_PREVIEW = "gpt-4-0125-preview"
    GPT_4_TURBO_2024_04_09 = "gpt-4-turbo-2024-04-09"
    GPT_4O_2024_05_13 = "gpt-4o-2024-05-13"
    GPT_4O_2024_08_06 = "gpt-4o-2024-08-06"
    GPT_4O_MINI_2024_07_18 = "gpt-4o-mini-2024-07-18"
    O1_2024_12_17 = "o1-2024-12-17"
    GPT_4_1_2025_04_14 = "gpt-4.1-2025-04-14"
    GPT_4_1_MINI_2025_04_14 = "gpt-4.1-mini-2025-04-14"
    GPT_4_1_NANO_2025_04_14 = "gpt-4.1-nano-2025-04-14"
    O3_2025_04_16 = "o3-2025-04-16"
    O3_MINI_2025_01_31 = "o3-mini-2025-01-31"
    O4_MINI_2025_04_16 = "o4-mini-2025-04-16"
    GPT_5_2025_08_07 = "gpt-5-2025-08-07"
    GPT_5_MINI_2025_08_07 = "gpt-5-mini-2025-08-07"
    GPT_5_NANO_2025_08_07 = "gpt-5-nano-2025-08-07"
    GPT_5_1_2025_11_13 = "gpt-5.1-2025-11-13"


class GeminiModelName(enum.StrEnum):
    GEMINI_1_0_PRO = "models/gemini-1.0-pro-001"
    GEMINI_1_5_FLASH = "models/gemini-1.5-flash-001"
    GEMINI_1_5_PRO = "models/gemini-1.5-pro-001"
    GEMINI_1_5_PRO_2 = "models/gemini-1.5-pro-002"
    GEMINI_1_5_FLASH_2 = "models/gemini-1.5-flash-002"
    GEMINI_2_0_FLASH = "models/gemini-2.0-flash-001"
    GEMINI_2_5_FLASH = "models/gemini-2.5-flash"
    GEMINI_2_5_FLASH_LITE_PREVIEW = "models/gemini-2.5-flash-lite-preview-06-17"


# TODO: there are likely more models to add
class GroqSupportedModelName(enum.StrEnum):
    GROQ_GEMMA2_9B_IT = "groq/gemma2-9b-it"
    GROQ_LLAMA3_70B_8192 = "groq/llama3-70b-8192"
    GROQ_LLAMA3_8B_8192 = "groq/llama3-8b-8192"
    GROQ_LLAMA_3_3_70B_SPECDEC = "groq/llama-3.3-70b-specdec"
    GROQ_MIXTRAL_8X7B_32768 = "groq/mixtral-8x7b-32768"
    GROQ_LLAMA_3_3_70B_VERSATILE = "groq/llama-3.3-70b-versatile"
    GROQ_LLAMA_3_1_8B_INSTANT = "groq/llama-3.1-8b-instant"
    GROQ_LLAMA_3_2_1B_PREVIEW = "groq/llama-3.2-1b-preview"
    GROQ_LLAMA_3_2_3B_PREVIEW = "groq/llama-3.2-3b-preview"
