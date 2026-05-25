"""
Central configuration and shared dataclasses for CodeCopilot.

Kept separate from main.py so that agents/worker.py and tools/spawn_agent.py
can import Config and AgentEvent without creating circular imports.
"""
import os
from dataclasses import dataclass
from typing import Any, Optional, Dict, List
from dotenv import load_dotenv

# Load .env file explicitly from the CodeCopilot root directory
_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root_dir, ".env"))


@dataclass(frozen=True)
class Config:
    # ── Inference Backend ──────────────────────────────────────────
    # Default: Cerebras (free tier, fast OpenAI-compatible inference, native
    # tool calling). Override OPENAI_BASE_URL / OPENAI_API_KEY in .env to
    # point at any other provider (HF Router, Groq, Together, Ollama, etc.).
    HF_TOKEN: str          = os.getenv("HF_TOKEN", "")
    OPENAI_BASE_URL: str   = os.getenv("OPENAI_BASE_URL", "https://api.cerebras.ai/v1")
    # Pick the key that matches the active backend. We check provider-specific
    # vars FIRST so a stray system-wide OPENAI_API_KEY (left over from another
    # tool) doesn't get sent to the wrong provider.
    OPENAI_API_KEY: str    = (
        (os.getenv("CEREBRAS_API_KEY", "") if "cerebras" in os.getenv("OPENAI_BASE_URL", "https://api.cerebras.ai/v1") else "")
        or (os.getenv("GROQ_API_KEY", "")  if "groq"     in os.getenv("OPENAI_BASE_URL", "") else "")
        or (os.getenv("HF_TOKEN", "")      if "huggingface" in os.getenv("OPENAI_BASE_URL", "") else "")
        or os.getenv("OPENAI_API_KEY", "")
        or os.getenv("CEREBRAS_API_KEY", "")
        or os.getenv("HF_TOKEN", "")
    )

    # Main model — zai-glm-4.6 on Cerebras (~1000 tokens/sec, strong native
    # tool-calling). Override via env var MODEL_ID to swap in any model your
    # Cerebras dashboard says you have access to, e.g.:
    #   "llama3.1-8b"
    #   "llama-3.3-70b"
    #   "qwen-3-32b"
    #   "qwen-3-coder-480b"
    MODEL_ID: str          = os.getenv("MODEL_ID", "zai-glm-4.6")

    PERSONA: str           = "coder"
    MODEL_CONTEXT_LIMIT: int = 32_000   # Qwen3-Coder supports 256k natively; capped to keep cost down
    MAX_OUTPUT_TOKENS: int   = 4_096
    MAX_RETRIES: int         = 3
    RETRY_DELAY: int         = 2

    # ── Agentic Loop ───────────────────────────────────────────────
    MAX_AGENTIC_TURNS: int  = 20   # max LLM→tool loops per user message
    MAX_PARALLEL_TOOLS: int = 4    # max concurrent tool executions

    # ── RAG ────────────────────────────────────────────────────────
    CHROMA_DIR: str         = ".chroma"
    RAG_CHUNK_SIZE: int     = 60   # lines per chunk
    RAG_OVERLAP: int        = 15   # overlap between chunks
    EMBED_MODEL: str        = "all-MiniLM-L6-v2"


@dataclass
class AgentEvent:
    """
    Structured event payload yielded by Agent.chat() and consumed by the CLI.

    Types:
        tool_call   — agent is about to call a tool
        tool_result — tool has returned a result
        answer      — agent's final prose response (loop ends)
        error       — unrecoverable failure (loop ends)
        info        — informational message (progress, routing, etc.)
        question    — agent needs user input (via question_tool)
    """
    type: str
    content: Any
    tool_name: Optional[str] = None
    tool_id: Optional[str]   = None
    tool_args: Optional[Dict] = None
    answers: Optional[List]  = None   # populated by CLI after question events
