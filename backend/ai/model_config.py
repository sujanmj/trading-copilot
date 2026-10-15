"""Provider model IDs with safe migrations away from retired/inaccessible defaults."""

GEMINI_PRIMARY_MODEL = 'gemini-3.6-flash'
GEMINI_LITE_MODEL = 'gemini-3.5-flash-lite'
GEMINI_PRIMARY_COST_PER_1K_INPUT = 0.0015
GEMINI_PRIMARY_COST_PER_1K_OUTPUT = 0.0075
GEMINI_LITE_COST_PER_1K_INPUT = 0.0003
GEMINI_LITE_COST_PER_1K_OUTPUT = 0.0025
GROQ_DEFAULT_MODEL = 'openai/gpt-oss-20b'
GROQ_COST_PER_1K_INPUT = 0.000075
GROQ_COST_PER_1K_OUTPUT = 0.0003

# This model is listed as Enterprise-only by Groq and the deployed API key cannot
# access it. Keep an explicit migration for Railway/local envs still naming it.
GROQ_MODEL_MIGRATIONS = {
    'llama-3.3-70b-versatile': GROQ_DEFAULT_MODEL,
}


def resolve_groq_model(configured: str | None) -> str:
    model = str(configured or '').strip()
    if not model:
        return GROQ_DEFAULT_MODEL
    return GROQ_MODEL_MIGRATIONS.get(model, model)


def gemini_cost_per_1k(model: str) -> tuple[float, float]:
    if str(model or '').startswith(GEMINI_LITE_MODEL):
        return GEMINI_LITE_COST_PER_1K_INPUT, GEMINI_LITE_COST_PER_1K_OUTPUT
    return GEMINI_PRIMARY_COST_PER_1K_INPUT, GEMINI_PRIMARY_COST_PER_1K_OUTPUT


def estimate_gemini_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = gemini_cost_per_1k(model)
    total = (max(0, int(input_tokens or 0)) / 1000) * input_rate
    total += (max(0, int(output_tokens or 0)) / 1000) * output_rate
    return round(total, 6)
