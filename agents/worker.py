"""
WorkerAgent — an isolated agent used by the spawn_agent tool.

Key differences from the main Agent in main.py:
  1. Does NOT have 'spawn_agent' in its tool list (prevents infinite recursion)
  2. Has a lower MAX_TURNS limit (15) to avoid runaway workers
  3. Accepts optional `context` from the orchestrator (injected before chat)
  4. Self-contained — imports Config and AgentEvent from utils.config to
     avoid circular imports through main.py
"""

import json
import time
from typing import Any, Generator, Optional

from openai import OpenAI

from utils.config import Config, AgentEvent
from utils.prompts import get_system_prompt
from utils.context import ContextManager
from tool_registry import get_all_tool_schemas, execute_tool_call


# Tools that workers are NOT allowed to call (prevents recursive spawning)
_WORKER_EXCLUDED_TOOLS = {"spawn_agent"}

# Workers have a tighter turn limit than the main orchestrator
_WORKER_MAX_TURNS = 15


class WorkerAgent:
    """
    An isolated agent instance created by spawn_agent to complete a subtask.

    The worker runs its own full agentic loop (LLM ↔ tools) but is bounded
    by _WORKER_MAX_TURNS and cannot spawn further workers.
    """

    def __init__(
        self,
        persona: str = "coder",
        hf_token: Optional[str] = None,
    ):
        self.persona = persona

        api_key = hf_token or Config.OPENAI_API_KEY
        if not api_key:
            raise ValueError(
                "No API key found. Set HF_TOKEN (or OPENAI_API_KEY) in your .env file."
            )

        self.client = OpenAI(
            base_url=Config.OPENAI_BASE_URL,
            api_key=api_key,
        )
        self.system_prompt = get_system_prompt(persona)

        self.memory = ContextManager(
            system_prompt=self.system_prompt,
            model_limit=Config.MODEL_CONTEXT_LIMIT,
            max_output=Config.MAX_OUTPUT_TOKENS,
        )

        # Load all tools EXCEPT spawn_agent (no recursive spawning)
        all_tools = get_all_tool_schemas(refresh=False)
        self.tools = [
            t for t in all_tools
            if t.get("function", {}).get("name") not in _WORKER_EXCLUDED_TOOLS
        ]

    def _call_llm(self) -> Any:
        """LLM call with retry + exponential backoff."""
        retries = 0
        last_err: Optional[Exception] = None
        while retries <= Config.MAX_RETRIES:
            try:
                return self.client.chat.completions.create(
                    model=Config.MODEL_ID,
                    messages=self.memory.get_messages(),
                    tools=self.tools,
                    tool_choice="auto",
                    max_tokens=Config.MAX_OUTPUT_TOKENS,
                    temperature=0.1,
                )
            except Exception as e:
                last_err = e
                msg = str(e)
                if "401" in msg or "403" in msg or "Wrong API Key" in msg or "Invalid username" in msg:
                    raise RuntimeError(
                        f"Auth rejected by backend at {Config.OPENAI_BASE_URL} (401/403). "
                        "Check the API key in .env and restart the CLI. "
                        f"Raw error: {msg}"
                    )
                retries += 1
                if retries > Config.MAX_RETRIES:
                    break
                time.sleep(Config.RETRY_DELAY * retries)
        raise RuntimeError(
            f"Worker LLM call failed after {Config.MAX_RETRIES} retries: {last_err}"
        )

    def chat(
        self,
        user_input: str,
        context: str = "",
    ) -> Generator[AgentEvent, None, None]:
        """
        Run the agentic loop for a single task.

        Args:
            user_input: The task description from the orchestrator.
            context:    Optional context string injected as a system note.

        Yields:
            AgentEvent objects (tool_call, tool_result, answer, error).
        """
        # Inject orchestrator context if provided
        if context:
            self.memory.add_message(
                "system",
                f"[CONTEXT FROM ORCHESTRATOR]\n{context}",
            )

        self.memory.add_message("user", user_input)

        turn_count = 0
        while turn_count < _WORKER_MAX_TURNS:
            turn_count += 1

            try:
                response = self._call_llm()
            except Exception as e:
                yield AgentEvent(
                    type="error",
                    content=f"Worker LLM failure: {str(e)}",
                )
                return

            message = response.choices[0].message

            # ── Tool Calls ────────────────────────────────────────
            if message.tool_calls:
                self.memory.add_tool_calls(message)

                for tc in message.tool_calls:
                    func_name = tc.function.name
                    call_id   = tc.id
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    yield AgentEvent(
                        type="tool_call",
                        content="Executing tool...",
                        tool_name=func_name,
                        tool_id=call_id,
                        tool_args=args,
                    )

                    result = execute_tool_call(func_name, args)

                    yield AgentEvent(
                        type="tool_result",
                        content=result,
                        tool_name=func_name,
                        tool_id=call_id,
                    )

                    self.memory.add_message("tool", result, tool_call_id=call_id)

            # ── Final Answer ──────────────────────────────────────
            else:
                answer = message.content or ""
                self.memory.add_message("assistant", answer)
                yield AgentEvent(type="answer", content=answer)
                return

        # Max turns exceeded
        yield AgentEvent(
            type="error",
            content=f"Worker exceeded max turns ({_WORKER_MAX_TURNS}). Task may be too complex.",
        )
