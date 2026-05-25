"""
LLM-based persona router using a small, fast model on the HF Inference Router.

Strategy:
  PRIMARY  → A small fast model (Llama-3.1-8B-Instruct by default)
               • Tiny vs. the main 480B model
               • Classifies in <1 s
               • Doesn't compete for the main model's rate-limit bucket

  FALLBACK → Lightweight keyword scorer
               • Used ONLY if the API is unavailable or returns junk
               • Instant, fully offline

Cache:
  • Results cached per session (MD5 of input → persona)
  • Identical messages skip the LLM entirely
"""

from __future__ import annotations

import os
import hashlib
from typing import Optional

from utils.config import Config

# ── Configuration ──────────────────────────────────────────────────
# A small fast model for cheap classification. Defaults to whatever the
# main agent uses, so we don't depend on a second model alias being
# available on the user's account. Override via ROUTER_MODEL if you want
# a smaller / cheaper one (e.g. "llama3.1-8b" on Cerebras).
_ROUTER_MODEL   = os.getenv("ROUTER_MODEL", Config.MODEL_ID)
_MAX_TOKENS     = 8        # only need one word back
_TEMPERATURE    = 0.0      # fully deterministic

_VALID_PERSONAS = {"coder", "debugger", "default"}

# Session-level cache: MD5(input) → persona
_ROUTE_CACHE: dict = {}

# ── Router System Prompt ───────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a task classifier for an AI coding assistant.
Classify the user's request into exactly ONE of these three categories.

Reply with ONLY the single category word. No punctuation. No explanation.

Categories:
  coder    — writing new code, implementing features, building things, refactoring,
             creating files, adding functions/classes, designing architecture
  debugger — fixing bugs, diagnosing errors, understanding why something crashes
             or behaves incorrectly, reading stack traces, tracing failures
  default  — research, explanations, documentation, comparisons, answering
             conceptual questions, web searches, summarising content

Examples:
  "add a login endpoint to my FastAPI app"          -> coder
  "my script crashes with AttributeError on line 5" -> debugger
  "what is the difference between async and await"  -> default
  "why is my function returning None instead of []" -> debugger
  "refactor this to use dataclasses"                -> coder
  "find the best way to do rate limiting in Python" -> default
"""


# ──────────────────────────────────────────────────────────────────
#  Fallback: lightweight keyword scorer (offline, instant)
# ──────────────────────────────────────────────────────────────────

_DEBUG_KW = {
    "bug", "error", "crash", "exception", "traceback", "fail", "failed",
    "failure", "broken", "not working", "issue", "problem", "debug",
    "why does", "why is", "why isn't", "doesn't work", "wrong output",
    "incorrect", "unexpected", "stack trace", "import error", "attributeerror",
    "typeerror", "valueerror", "keyerror", "nameerror", "runtimeerror",
    "syntaxerror", "indexerror", "segfault", "module not found",
    "fix", "resolve",
}

_CODER_KW = {
    "implement", "create", "build", "write", "generate", "refactor",
    "develop", "add", "make", "design", "architect", "integrate",
    "upgrade", "extend", "optimise", "optimize",
}

_DEFAULT_KW = {
    "explain", "what is", "how does", "research", "find", "search",
    "summarize", "compare", "difference", "document", "describe",
    "help me understand", "tell me", "analyse", "analyze",
}


def _keyword_fallback(text: str) -> str:
    """Instant keyword scorer used when LLM is unavailable."""
    lower = text.lower()
    d = sum(1 for k in _DEBUG_KW   if k in lower)
    c = sum(1 for k in _CODER_KW   if k in lower)
    e = sum(1 for k in _DEFAULT_KW if k in lower)

    best_score = max(d, c, e)
    if best_score == 0:
        return "coder"          # safe default
    if d == best_score:
        return "debugger"
    if c == best_score:
        return "coder"
    return "default"


# ──────────────────────────────────────────────────────────────────
#  Primary: LLM classifier
# ──────────────────────────────────────────────────────────────────

def _llm_classify(user_input: str) -> str:
    """
    Call the configured chat endpoint with a tight prompt and parse
    the one-word response. Raises on failure so the caller can fall
    back gracefully.
    """
    from openai import OpenAI

    api_key = Config.OPENAI_API_KEY
    if not api_key:
        raise ValueError("No API key configured for routing.")

    client = OpenAI(
        base_url=Config.OPENAI_BASE_URL,
        api_key=api_key,
    )
    response = client.chat.completions.create(
        model=_ROUTER_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_input[:500]},   # cap at 500 chars
        ],
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
    )

    raw = (response.choices[0].message.content or "").strip().lower()

    # Parse: take the first token that matches a valid persona
    for token_word in raw.split():
        cleaned = token_word.strip(".,!?:;\"'()-_>")
        if cleaned in _VALID_PERSONAS:
            return cleaned

    raise ValueError(f"Unexpected LLM response: {raw!r}")


# ──────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────

def route_persona(
    user_input: str,
    hf_token: Optional[str] = None,
) -> tuple:
    """
    Classify a user message into the most appropriate agent persona.

    Returns:
        (persona, method) where:
          persona — 'coder' | 'debugger' | 'default'
          method  — 'llm' | 'keyword_fallback' | 'cache'
    """
    if not user_input or not user_input.strip():
        return "coder", "keyword_fallback"

    cache_key = hashlib.md5(user_input.encode()).hexdigest()
    if cache_key in _ROUTE_CACHE:
        return _ROUTE_CACHE[cache_key], "cache"

    try:
        persona = _llm_classify(user_input)
        _ROUTE_CACHE[cache_key] = persona
        return persona, "llm"
    except Exception:
        pass

    persona = _keyword_fallback(user_input)
    _ROUTE_CACHE[cache_key] = persona
    return persona, "keyword_fallback"


def clear_cache() -> None:
    """Clear the session routing cache (useful in tests)."""
    _ROUTE_CACHE.clear()
