import json
from typing import Optional
from utils.schema_helper import tool


@tool
def spawn_agent(
    task: str,
    persona: str,
    context: str = "",
) -> str:
    """
    Spawns an isolated worker agent to complete a specific subtask autonomously.
    The worker runs its own full agentic loop (with tools) and returns the result.

    Use this tool when you are acting as an ORCHESTRATOR delegating parallel or
    specialized subtasks to worker agents.

    USAGE RULES:
    1. Only use when the subtask is INDEPENDENT — the worker has its own memory
       and cannot share state with you or other workers.
    2. Provide specific, self-contained task descriptions. Include all needed
       context in the 'context' parameter since the worker starts fresh.
    3. Workers CANNOT spawn further workers (prevents infinite recursion).
    4. Good use cases:
       - "Search for X and summarize findings" (independent research)
       - "Read file Y and audit for security issues" (independent analysis)
       - "Write tests for module Z" (independent after code is written)
    5. Bad use cases:
       - Tasks that depend on another worker's live output (use sequential calls)
       - Simple single-tool tasks (just call the tool directly instead)

    :param task: Clear, self-contained description of the subtask.
    :param persona: Worker persona: 'coder' | 'debugger' | 'default'.
    :param context: Background information to inject at the start of the worker's
                    session (file contents, previous results, constraints, etc.).
    """
    result = {
        "status":         "failed",
        "task":           task,
        "worker_persona": persona,
        "answer":         "",
        "tool_calls_made": 0,
        "error":          None,
        "output":         "",
    }

    # Lazy import inside function body — CRITICAL to avoid circular imports.
    # tool_registry loads spawn_agent.py at startup; if we imported WorkerAgent
    # at the top level, it would trigger tool_registry again before it finishes
    # initialising → AttributeError. The lazy import runs only when this
    # function is actually called at runtime, by which time everything is ready.
    try:
        from agents.worker import WorkerAgent
    except ImportError as e:
        result["error"]  = f"Failed to import WorkerAgent: {e}"
        result["output"] = result["error"]
        return json.dumps(result)

    if not task or not task.strip():
        result["error"]  = "'task' cannot be empty."
        result["output"] = result["error"]
        return json.dumps(result)

    valid_personas = {"coder", "debugger", "default"}
    if persona not in valid_personas:
        result["error"]  = f"Invalid persona '{persona}'. Choose: {', '.join(valid_personas)}."
        result["output"] = result["error"]
        return json.dumps(result)

    try:
        worker       = WorkerAgent(persona=persona)
        tool_calls   = 0
        final_answer = ""
        error_msg    = ""

        for event in worker.chat(task.strip(), context=context):
            if event.type == "tool_call":
                tool_calls += 1
            elif event.type == "answer":
                final_answer = event.content
            elif event.type == "error":
                error_msg = event.content

        if error_msg and not final_answer:
            result["error"]  = error_msg
            result["output"] = f"Worker [{persona}] failed: {error_msg}"
        else:
            result["status"]          = "success"
            result["answer"]          = final_answer
            result["tool_calls_made"] = tool_calls
            result["output"] = (
                f"Worker [{persona}] completed task in {tool_calls} tool call(s).\n\n"
                f"RESULT:\n{final_answer}"
            )

    except Exception as e:
        result["error"]  = str(e)
        result["output"] = f"Worker [{persona}] crashed: {str(e)}"

    return json.dumps(result)
