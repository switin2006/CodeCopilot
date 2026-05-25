import json
import os
import time
from typing import Optional, Literal, List
from utils.schema_helper import tool

# ------------------------------------------------------------------
# WHAT IS THIS TOOL?
#
# `todo` = flat shopping list  → "do A, do B, do C"
# `plan` = structured blueprint → "Phase 1 (goal: X) has steps A→B→C,
#                                   Phase 2 (goal: Y) has steps D→E"
#
# The agent MUST call plan(action='create') before any multi-step task.
# This forces it to commit to a structured approach first, like a
# senior engineer writing a design doc before writing code.
#
# Key differences from todo:
#  1. Has a top-level GOAL (the "why")
#  2. Steps have PHASES (group related work)
#  3. Steps have DEPENDS_ON (enforce ordering, prevent skipping)
#  4. Steps have ASSIGNED_PERSONA (which agent type should do this)
#  5. Steps have RATIONALE (the "why" for each step)
#  6. The plan has an overall STATUS (draft → active → done → failed)
#  7. Only ONE active plan at a time (forces focus)
# ------------------------------------------------------------------

_PLAN_FILE = "active_plan.json"


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------

def _load_plan() -> dict:
    if not os.path.exists(_PLAN_FILE):
        return {}
    try:
        with open(_PLAN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_plan(plan: dict) -> None:
    with open(_PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _step_icon(status: str) -> str:
    return {"pending": "○", "in_progress": "◉", "done": "●", "blocked": "✗", "skipped": "⊘"}.get(status, "○")


def _render_plan(plan: dict) -> str:
    """Renders the plan as a concise human-readable string for LLM consumption."""
    if not plan:
        return "No active plan. Call plan(action='create') to start one."

    lines = [
        f"═══ PLAN: {plan['title']} ═══",
        f"Goal    : {plan['goal']}",
        f"Status  : {plan['status'].upper()}",
        f"Progress: {plan['completed_steps']}/{plan['total_steps']} steps done",
        f"Created : {plan.get('created_at', '?')}",
        "",
    ]

    current_phase = None
    for step in plan.get("steps", []):
        phase = step.get("phase", "General")
        if phase != current_phase:
            lines.append(f"  ── Phase: {phase} ──")
            current_phase = phase

        icon = _step_icon(step["status"])
        dep_str = f" [needs: #{','.join(str(d) for d in step['depends_on'])}]" if step.get("depends_on") else ""
        persona_str = f" [{step['persona']}]" if step.get("persona") else ""
        lines.append(f"  {icon} Step #{step['id']:02d}{persona_str}: {step['description']}{dep_str}")

        if step.get("rationale"):
            lines.append(f"       why: {step['rationale']}")
        if step.get("result_summary"):
            lines.append(f"       result: {step['result_summary']}")

    # Next actionable step
    next_step = _get_next_step(plan)
    if next_step:
        lines.append(f"\n→ NEXT: Step #{next_step['id']}: {next_step['description']}")
    elif plan["status"] != "done":
        lines.append("\n→ All steps complete. Call plan(action='finish') to close the plan.")

    return "\n".join(lines)


def _get_next_step(plan: dict) -> Optional[dict]:
    """Returns the first pending step whose dependencies are all done."""
    done_ids = {s["id"] for s in plan.get("steps", []) if s["status"] == "done"}
    for step in plan.get("steps", []):
        if step["status"] != "pending":
            continue
        deps = set(step.get("depends_on", []))
        if deps.issubset(done_ids):
            return step
    return None


# ------------------------------------------------------------------
# TOOL
# ------------------------------------------------------------------

@tool
def plan(
    action: Literal["create", "start_step", "finish_step", "skip_step", "update_goal", "view", "finish", "abort"],
    title: Optional[str] = None,
    goal: Optional[str] = None,
    steps: Optional[List[str]] = None,
    step_id: Optional[int] = None,
    result_summary: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """
    Structured execution planner. Use this BEFORE starting any multi-step task.
    Unlike 'todo' (a flat list), 'plan' enforces: phases, step ordering,
    dependencies between steps, and persona assignment per step.

    MANDATORY USAGE RULES:
    1. For ANY task with 3+ steps: call plan(action='create') FIRST.
    2. Before executing a step: call plan(action='start_step', step_id=N).
    3. After completing a step: call plan(action='finish_step', step_id=N, result_summary='...').
    4. ALWAYS call plan(action='view') at the start of a resumed session.
    5. Call plan(action='finish') when all steps are done.

    ACTIONS:
    - create      : Create a new plan (title + goal + steps required).
    - start_step  : Mark a step as in-progress before executing it.
    - finish_step : Mark a step done + record what was accomplished.
    - skip_step   : Skip a step with a reason.
    - update_goal : Revise the overall goal mid-task.
    - view        : Show the current plan status (do this when resuming).
    - finish      : Mark the entire plan as done.
    - abort       : Mark plan as failed with a reason.

    :param action: The operation to perform (see ACTIONS above).
    :param title: Short name for the plan (required for 'create').
    :param goal: What the plan achieves at the end (required for 'create').
    :param steps: A simple list of strings, where each string describes one step (required for 'create').
                  Example: ["Read file X", "Write function Y", "Test code"]
    :param step_id: Integer ID of the step (required for start/finish/skip_step).
    :param result_summary: Brief summary of what was done (required for 'finish_step').
    :param reason: Reason for skipping or aborting (required for skip_step/abort).
    """
    result = {"status": "failed", "output": "", "error": None}

    try:
        plan_data = _load_plan()

        # ── CREATE ──────────────────────────────────────────────────
        if action == "create":
            # Validate required fields
            if not title or not title.strip():
                result["error"] = "'title' is required for action='create'."
                result["output"] = result["error"]
                return json.dumps(result)
            if not goal or not goal.strip():
                result["error"] = "'goal' is required for action='create'. Describe what success looks like."
                result["output"] = result["error"]
                return json.dumps(result)
            if not steps or not isinstance(steps, list):
                result["error"] = (
                    "'steps' is required for action='create'. Provide a simple list of strings. "
                    "Example: [\"Read the file\", \"Write the code\"]"
                )
                result["output"] = result["error"]
                return json.dumps(result)

            # Build normalized step objects from the simple strings
            built_steps = []
            for i, s in enumerate(steps, start=1):
                if not isinstance(s, str) or not s.strip():
                    result["error"] = f"Step {i} must be a non-empty string."
                    result["output"] = result["error"]
                    return json.dumps(result)
                built_steps.append({
                    "id":             i,
                    "description":    s.strip(),
                    "phase":          "Execution",
                    "persona":        "",
                    "rationale":      "",
                    "depends_on":     [],
                    "status":         "pending",
                    "result_summary": "",
                    "started_at":     "",
                    "finished_at":    "",
                })

            plan_data = {
                "title":           title.strip(),
                "goal":            goal.strip(),
                "status":          "active",
                "steps":           built_steps,
                "total_steps":     len(built_steps),
                "completed_steps": 0,
                "created_at":      _now(),
                "updated_at":      _now(),
            }
            _save_plan(plan_data)

            result["status"] = "success"
            result["output"] = (
                f"Plan created: '{title}' with {len(built_steps)} steps.\n\n"
                + _render_plan(plan_data)
            )

        # ── VIEW ─────────────────────────────────────────────────────
        elif action == "view":
            if not plan_data:
                result["status"] = "success"
                result["output"] = "No active plan. Call plan(action='create') to begin."
                return json.dumps(result)
            result["status"] = "success"
            result["output"] = _render_plan(plan_data)

        # ── START_STEP ───────────────────────────────────────────────
        elif action == "start_step":
            if not plan_data:
                result["error"] = "No active plan. Create one first."
                result["output"] = result["error"]
                return json.dumps(result)
            if step_id is None:
                result["error"] = "'step_id' is required for action='start_step'."
                result["output"] = result["error"]
                return json.dumps(result)

            step = next((s for s in plan_data["steps"] if s["id"] == step_id), None)
            if step is None:
                result["error"] = f"Step #{step_id} not found in the plan."
                result["output"] = result["error"]
                return json.dumps(result)

            # Dependency check
            done_ids = {s["id"] for s in plan_data["steps"] if s["status"] == "done"}
            blocking = set(step.get("depends_on", [])) - done_ids
            if blocking:
                result["error"] = (
                    f"Step #{step_id} is blocked. Complete these steps first: "
                    + ", ".join(f"#{b}" for b in sorted(blocking))
                )
                result["output"] = result["error"]
                return json.dumps(result)

            step["status"] = "in_progress"
            step["started_at"] = _now()
            plan_data["updated_at"] = _now()
            _save_plan(plan_data)

            result["status"] = "success"
            result["output"] = (
                f"◉ Started Step #{step_id}: {step['description']}\n"
                f"  Rationale: {step['rationale'] or 'N/A'}\n"
                f"  Persona:   {step['persona'] or 'any'}\n"
                f"  Phase:     {step['phase']}"
            )

        # ── FINISH_STEP ──────────────────────────────────────────────
        elif action == "finish_step":
            if not plan_data:
                result["error"] = "No active plan."
                result["output"] = result["error"]
                return json.dumps(result)
            if step_id is None:
                result["error"] = "'step_id' is required for action='finish_step'."
                result["output"] = result["error"]
                return json.dumps(result)
            if not result_summary:
                result["error"] = "'result_summary' is required for action='finish_step'. Briefly describe what was accomplished."
                result["output"] = result["error"]
                return json.dumps(result)

            step = next((s for s in plan_data["steps"] if s["id"] == step_id), None)
            if step is None:
                result["error"] = f"Step #{step_id} not found."
                result["output"] = result["error"]
                return json.dumps(result)

            step["status"] = "done"
            step["result_summary"] = result_summary.strip()
            step["finished_at"] = _now()
            plan_data["completed_steps"] = sum(1 for s in plan_data["steps"] if s["status"] == "done")
            plan_data["updated_at"] = _now()
            _save_plan(plan_data)

            next_step = _get_next_step(plan_data)
            next_hint = f"\n→ NEXT: Step #{next_step['id']}: {next_step['description']}" if next_step else "\n→ All steps complete. Call plan(action='finish')."

            result["status"] = "success"
            result["output"] = (
                f"● Done Step #{step_id}: {step['description']}\n"
                f"  Result: {result_summary}\n"
                f"  Progress: {plan_data['completed_steps']}/{plan_data['total_steps']} steps done."
                + next_hint
            )

        # ── SKIP_STEP ────────────────────────────────────────────────
        elif action == "skip_step":
            if not plan_data:
                result["error"] = "No active plan."
                result["output"] = result["error"]
                return json.dumps(result)
            if step_id is None:
                result["error"] = "'step_id' is required."
                result["output"] = result["error"]
                return json.dumps(result)

            step = next((s for s in plan_data["steps"] if s["id"] == step_id), None)
            if step is None:
                result["error"] = f"Step #{step_id} not found."
                result["output"] = result["error"]
                return json.dumps(result)

            step["status"] = "skipped"
            step["result_summary"] = f"Skipped: {reason or 'No reason given'}"
            step["finished_at"] = _now()
            plan_data["updated_at"] = _now()
            _save_plan(plan_data)

            result["status"] = "success"
            result["output"] = f"⊘ Skipped Step #{step_id}: {step['description']}. Reason: {reason or 'N/A'}"

        # ── UPDATE_GOAL ──────────────────────────────────────────────
        elif action == "update_goal":
            if not plan_data:
                result["error"] = "No active plan."
                result["output"] = result["error"]
                return json.dumps(result)
            if not goal:
                result["error"] = "'goal' is required for action='update_goal'."
                result["output"] = result["error"]
                return json.dumps(result)

            old_goal = plan_data["goal"]
            plan_data["goal"] = goal.strip()
            plan_data["updated_at"] = _now()
            _save_plan(plan_data)

            result["status"] = "success"
            result["output"] = f"Goal updated.\nOld: {old_goal}\nNew: {goal}"

        # ── FINISH ───────────────────────────────────────────────────
        elif action == "finish":
            if not plan_data:
                result["error"] = "No active plan."
                result["output"] = result["error"]
                return json.dumps(result)

            plan_data["status"] = "done"
            plan_data["updated_at"] = _now()
            _save_plan(plan_data)

            done = plan_data["completed_steps"]
            total = plan_data["total_steps"]
            result["status"] = "success"
            result["output"] = (
                f"✦ Plan COMPLETE: '{plan_data['title']}'\n"
                f"  Goal achieved: {plan_data['goal']}\n"
                f"  {done}/{total} steps completed."
            )

        # ── ABORT ────────────────────────────────────────────────────
        elif action == "abort":
            if not plan_data:
                result["error"] = "No active plan."
                result["output"] = result["error"]
                return json.dumps(result)

            plan_data["status"] = "failed"
            plan_data["abort_reason"] = reason or "No reason given"
            plan_data["updated_at"] = _now()
            _save_plan(plan_data)

            result["status"] = "success"
            result["output"] = f"✗ Plan aborted: '{plan_data['title']}'. Reason: {reason or 'N/A'}"

        else:
            result["error"] = (
                f"Unknown action '{action}'. "
                "Use: create | start_step | finish_step | skip_step | update_goal | view | finish | abort"
            )
            result["output"] = result["error"]

    except Exception as e:
        result["error"] = f"Plan operation failed: {str(e)}"
        result["output"] = result["error"]

    return json.dumps(result)
