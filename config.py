"""Central configuration. All tunables live here; secrets come from .env only."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:  # dotenv optional for tests
    pass

ROOT = Path(__file__).parent
TRANSCRIPTS_DIR = Path(os.getenv("TRANSCRIPTS_DIR", ROOT / "data" / "transcripts"))
QUESTIONS_PATH = Path(os.getenv("QUESTIONS_PATH", ROOT / "data" / "questions.json"))
STORE_DIR = Path(os.getenv("STORE_DIR", ROOT / "store"))
SQLITE_PATH = STORE_DIR / "memory.sqlite"
CHROMA_DIR = STORE_DIR / "chroma"
LLM_CACHE_PATH = STORE_DIR / "llm_cache.sqlite"
OUTPUTS_DIR = ROOT / "outputs"
LOG_DIR = ROOT / "logs"

# ---- Chunking (speaker-turn aware) ----
CHUNK_TARGET_WORDS = 220      # soft target; chunks only break at turn boundaries
CHUNK_MAX_WORDS = 400         # a single very long turn may exceed target, never split mid-turn
CHUNK_OVERLAP_TURNS = 3       # trailing turns repeated at the start of the next chunk

# ---- Embeddings (local, free) ----
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_BATCH_SIZE = 64

# ---- LLMs ----
# Ordered fallback chains. Every call logs which (provider, model) actually answered.
# Measured on 2026-11-19 (see README "Where the tools broke"): gemini-3.6-flash, 3.7 and 3.8 returned
# 503 UNAVAILABLE / timeouts most of the day; gemini-3-flash-preview answered in ~3 s; flash-lite models
# returned intermittent 503s. Groq free tier caps gpt-oss-20b at 8k tokens/minute, i.e. ~1 big prompt/min,
# so it is the last resort, not a parallel worker.
# Free-tier quotas are PER MODEL (measured from 429 bodies / response headers):
#   gemini-3-flash-preview: 20 requests/day;  Groq models: 1,000 req/day but 8,000 tokens/minute
#   (so prompts > ~8k tokens are rejected with 413 - answer prompts cannot run on Groq).
# Extraction therefore never touches the scarce reasoning models.
REASONING_CHAIN = [
    ("gemini", os.getenv("REASONING_MODEL", "gemini-3.6-flash")),
    ("gemini", "gemini-3-flash-preview"),
    ("gemini", "gemini-3.5-flash-lite"),
    ("gemini", "gemini-3.1-flash-lite"),
    ("groq", "openai/gpt-oss-120b"),
]
# qwen3.8-27b was removed: its free tier allows only 1,000 OUTPUT tokens/minute, so every extraction
# request was rejected as "too large".
EXTRACTION_CHAIN = [
    ("gemini", os.getenv("EXTRACTION_MODEL", "gemini-3.1-flash-lite")),
    ("gemini", "gemini-3.5-flash-lite"),
    ("groq", os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")),
    ("groq", "openai/gpt-oss-120b"),
]
LLM_TIMEOUT_S = 75
LLM_MAX_RETRIES = 2
CIRCUIT_FAILURES = 3        # consecutive overload/timeout failures before a model is skipped
CIRCUIT_COOLDOWN_S = 120   # after a 503 burst
TIMEOUT_COOLDOWN_S = 900   # a model that times out repeatedly is usually down for a long time
GROQ_TPM = 7800            # Groq free tier: 8,000 tokens/min per model, counting prompt + max_tokens

# Public list prices (USD per 1M tokens), used ONLY for cost estimates. Free tier = $0 actual.
# Values are assumptions recorded in outputs/cost_estimate.md; check provider pricing pages.
# Sources checked 2026-11-19: gemini-3.1-flash-lite $0.25/$1.50 (multiple trackers agree);
# gemini-3.6-flash $0.75/$3.75 introductory until 2026-12-31, $1.50/$7.50 afterwards (sources conflict);
# gpt-oss-20b on Groq $0.075/$0.30. gemini-3-flash-preview and 3.5-flash-lite: ASSUMED equal to their tier.
PRICING = {
    "gemini-3.1-flash-lite": {"in": 0.25, "out": 1.50},
    "gemini-3.6-flash": {"in": 0.75, "out": 3.75},
    "gemini-3-flash-preview": {"in": 0.75, "out": 3.75},
    "gemini-3.5-flash-lite": {"in": 0.25, "out": 1.50},
    "openai/gpt-oss-20b": {"in": 0.075, "out": 0.30},
    "openai/gpt-oss-120b": {"in": 0.15, "out": 0.60},
}

# ---- Agent ----
MAX_RETRIEVAL_ITERATIONS = 3
RETRIEVAL_TOP_K = 8               # chunks per query
EVIDENCE_TOKEN_BUDGET = 9000      # approx tokens of transcript evidence sent to the answerer
MIN_QUOTE_WORDS = 6
