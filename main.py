import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Generator, Optional

from openai import OpenAI

# Import core modules
from tool_registry import get_all_tool_schemas, execute_tool_call
from utils.prompts import get_system_prompt
from utils.context import ContextManager

# Config and AgentEvent live in utils/config.py so agents/worker.py
# can import them without creating circular imports through main.py
from utils.config import Config, AgentEvent

# Re-export so cli.py can still do: from main import Agent, AgentEvent, Config
__all__ = ["Agent", "AgentEvent", "Config"]


class Agent:
    """
    Main orchestrator agent (Hugging Face Inference Edition).

    Uses Qwen3-Coder-480B (or any OpenAI-compatible model) for native
    function calling and code reasoning. Tools execute in parallel when
    the model returns multiple tool calls in one turn.
    """

    def __init__(
        self,
        hf_token: Optional[str] = None,
        persona: Optional[str] = None,
    ):
        """
        Args:
            hf_token: Optional override for the Hugging Face token.
            persona:  'coder' | 'debugger' | 'default'. Overrides Config.PERSONA.
        """
        self.persona = persona or Config.PERSONA

        api_key = hf_token or Config.OPENAI_API_KEY
        if not api_key:
            raise ValueError(
                "No API key found. Set HF_TOKEN (or OPENAI_API_KEY) in your .env file. "
                "Get a free token at https://huggingface.co/settings/tokens"
            )

        # Connect to the OpenAI-compatible endpoint (HF Router by default).
        self.client = OpenAI(
            base_url=Config.OPENAI_BASE_URL,
            api_key=api_key,
        )

        self.system_prompt = get_system_prompt(self.persona)

        self.memory = ContextManager(
            system_prompt=self.system_prompt,
            model_limit=Config.MODEL_CONTEXT_LIMIT,
            max_output=Config.MAX_OUTPUT_TOKENS,
        )

        # Refresh=True so newly added tool files are always picked up
        self.tools = get_all_tool_schemas(refresh=True)

    # ──────────────────────────────────────────────────────────────
    #  LLM Call
    # ──────────────────────────────────────────────────────────────

    def _call_llm_with_retry(self) -> Any:
        """LLM call with exponential backoff."""
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
                # 401/403 won't get better with retries — fail fast with a clear hint
                if "401" in msg or "403" in msg or "Wrong API Key" in msg or "Invalid username" in msg:
                    backend = Config.OPENAI_BASE_URL
                    raise RuntimeError(
                        f"Auth rejected by backend at {backend} (401/403). "
                        "Check that the right API key is set in .env for this backend, "
                        "and that no stale system env var is overriding it. "
                        "Restart the CLI after editing .env. "
                        f"Raw error: {msg}"
                    )
                retries += 1
                if retries > Config.MAX_RETRIES:
                    break
                time.sleep(Config.RETRY_DELAY * retries)
        msg = str(last_err) if last_err else "unknown error"
        raise RuntimeError(f"LLM call failed after {Config.MAX_RETRIES} retries: {msg}")

    # ──────────────────────────────────────────────────────────────
    #  Parallel Tool Execution
    # ──────────────────────────────────────────────────────────────

    def _execute_parallel(
        self,
        tool_calls_data: list,
    ) -> dict:
        """
        Execute multiple tool calls concurrently using a thread pool.

        Args:
            tool_calls_data: List of {call_id, name, args} dicts.

        Returns:
            Dict mapping call_id → result string (in original call order).
        """
        if len(tool_calls_data) == 1:
            # Skip overhead for single tool calls
            tc = tool_calls_data[0]
            return {tc["call_id"]: execute_tool_call(tc["name"], tc["args"])}

        max_workers = min(len(tool_calls_data), Config.MAX_PARALLEL_TOOLS)
        results: dict = {}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_id = {
                pool.submit(execute_tool_call, tc["name"], tc["args"]): tc["call_id"]
                for tc in tool_calls_data
            }
            for future in as_completed(future_to_id):
                call_id = future_to_id[future]
                try:
                    results[call_id] = future.result()
                except Exception as e:
                    results[call_id] = json.dumps({
                        "status": "failed",
                        "error":  str(e),
                        "output": f"Tool execution error: {str(e)}",
                    })

        return results

    # ──────────────────────────────────────────────────────────────
    #  Main Agentic Loop
    # ──────────────────────────────────────────────────────────────

    def chat(self, user_input: str) -> Generator[AgentEvent, None, None]:
        """
        Process a user message through the agentic loop.

        Yields AgentEvent objects:
            tool_call   — emitted before each tool executes
            tool_result — emitted after each tool returns
            answer      — final prose answer (loop ends)
            error       — unrecoverable failure (loop ends)
            info        — informational messages (e.g. max_turns warning)
        """
        self.memory.add_message("user", user_input)

        turn_count = 0

        while turn_count < Config.MAX_AGENTIC_TURNS:
            turn_count += 1

            # ── LLM Call ─────────────────────────────────────────
            try:
                response = self._call_llm_with_retry()
            except Exception as e:
                yield AgentEvent(
                    type="error",
                    content=f"Critical LLM Failure: {str(e)}",
                )
                return

            message = response.choices[0].message

            # ── Case 1: Tool Calls ────────────────────────────────
            if message.tool_calls:
                self.memory.add_tool_calls(message)

                # Parse all tool calls first
                tool_calls_data = []
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls_data.append({
                        "call_id": tc.id,
                        "name":    tc.function.name,
                        "args":    args,
                    })

                # Emit tool_call events (all upfront so CLI can show them)
                for tc in tool_calls_data:
                    event = AgentEvent(
                        type="tool_call",
                        content="Executing tool...",
                        tool_name=tc["name"],
                        tool_id=tc["call_id"],
                        tool_args=tc["args"],
                    )
                    yield event
                    if event.content == "REJECTED":
                        tc["rejected"] = True

                # Execute allowed tools (in parallel if multiple, sequential if one)
                results = {}
                active_tcs = [tc for tc in tool_calls_data if not tc.get("rejected")]
                if active_tcs:
                    results.update(self._execute_parallel(active_tcs))

                # Inject failure results for rejected tools
                for tc in tool_calls_data:
                    if tc.get("rejected"):
                        results[tc["call_id"]] = json.dumps({
                            "status": "failed",
                            "error": "User rejected this tool call."
                        })

                # Emit results and add to memory IN ORIGINAL ORDER
                # (API requires tool results to match the order of tool_calls)
                for tc in tool_calls_data:
                    result = results[tc["call_id"]]

                    yield AgentEvent(
                        type="tool_result",
                        content=result,
                        tool_name=tc["name"],
                        tool_id=tc["call_id"],
                        tool_args=tc["args"],
                    )

                    self.memory.add_message(
                        "tool",
                        result,
                        tool_call_id=tc["call_id"],
                    )

            # ── Case 2: Final Answer ──────────────────────────────
            else:
                answer = message.content or ""
                self.memory.add_message("assistant", answer)
                yield AgentEvent(type="answer", content=answer)
                return

        # ── Max Turns Guard ───────────────────────────────────────
        yield AgentEvent(
            type="error",
            content=(
                f"Max agentic turns ({Config.MAX_AGENTIC_TURNS}) reached. "
                "The task may be too complex for a single session. "
                "Try breaking it into smaller requests, or use spawn_agent."
            ),
        )

    # ──────────────────────────────────────────────────────────────
    #  Utilities
    # ──────────────────────────────────────────────────────────────

    def clear_memory(self) -> None:
        """Reset conversation history and re-scan tools from disk."""
        self.memory.clear()
        self.tools = get_all_tool_schemas(refresh=True)
