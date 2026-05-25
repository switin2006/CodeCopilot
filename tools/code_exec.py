import subprocess
import sys
import json
import os
import tempfile
from typing import Optional
from utils.schema_helper import tool

# ------------------------------------------------------------------
# SAFE EXEC CONFIGURATION
# ------------------------------------------------------------------
_DEFAULT_TIMEOUT = 10      # seconds
_MAX_OUTPUT_LEN  = 8_000   # chars — truncate huge stdout

# Patterns that should never be allowed in code_exec
# (use bash_tool for system commands; this tool is for Python only)
_BLOCKED_PATTERNS = [
    "os.system", "subprocess", "__import__('os')",
    "open('/", "open(\"/", "shutil.rmtree",
]


def _is_safe(code: str) -> tuple[bool, str]:
    """
    Light static safety check. Not a sandbox — use Docker for true isolation.
    Blocks the most dangerous patterns that should use bash_tool instead.
    """
    for pat in _BLOCKED_PATTERNS:
        if pat in code:
            return False, (
                f"Blocked pattern '{pat}' detected. "
                "Use bash_tool for system commands. "
                "code_exec is for pure Python logic only."
            )
    return True, ""


# ------------------------------------------------------------------
# TOOL
# ------------------------------------------------------------------

@tool
def code_exec(
    code: str,
    timeout: int = 10,
    python_version: Optional[str] = None,
) -> str:
    """
    Executes a Python code snippet in a subprocess and returns the output.
    Use this tool to TEST your own code, verify logic, or run quick experiments.

    USAGE RULES:
    1. Use this after writing code with write_file to verify it works.
    2. For system commands (mkdir, git, pip), use bash_tool instead.
    3. Keep code snippets focused — avoid long scripts (use write_file + bash_tool for those).
    4. The code runs in an isolated subprocess with access to installed packages.
    5. Do NOT use for file system deletions or network requests; use dedicated tools.

    :param code: The Python code string to execute.
    :param timeout: Max execution time in seconds (default 10, max 60).
    :param python_version: Optional Python interpreter path (e.g., 'python3.11'). Defaults to current interpreter.
    """
    result = {
        "status":    "failed",
        "stdout":    "",
        "stderr":    "",
        "exit_code": -1,
        "output":    "",
        "error":     None,
    }

    # 1. Validate input
    if not code or not code.strip():
        result["error"] = "code cannot be empty."
        result["output"] = result["error"]
        return json.dumps(result)

    timeout = max(1, min(timeout, 60))  # clamp between 1 and 60 seconds

    # 2. Safety check
    safe, reason = _is_safe(code)
    if not safe:
        result["error"] = reason
        result["output"] = reason
        return json.dumps(result)

    # 3. Determine interpreter (ignore LLM suggestions, enforce current environment)
    interpreter = sys.executable

    # 4. Write to a temp file and execute
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        proc = subprocess.run(
            [interpreter, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        # Truncate huge outputs
        if len(stdout) > _MAX_OUTPUT_LEN:
            stdout = stdout[:_MAX_OUTPUT_LEN] + f"\n... [truncated at {_MAX_OUTPUT_LEN} chars]"
        if len(stderr) > _MAX_OUTPUT_LEN:
            stderr = stderr[:_MAX_OUTPUT_LEN] + f"\n... [truncated at {_MAX_OUTPUT_LEN} chars]"

        result["stdout"]    = stdout
        result["stderr"]    = stderr
        result["exit_code"] = proc.returncode
        result["status"]    = "success" if proc.returncode == 0 else "failed"

        # LLM-friendly formatted output
        lines = []
        if stdout:
            lines.append(f"STDOUT:\n{stdout}")
        if stderr:
            lines.append(f"STDERR:\n{stderr}")
        lines.append(f"Exit code: {proc.returncode}")
        if proc.returncode != 0:
            lines.append("⚠ Code exited with a non-zero status — there may be an error above.")

        result["output"] = "\n".join(lines) if lines else "(no output)"

    except subprocess.TimeoutExpired:
        result["error"]  = f"Code execution timed out after {timeout}s."
        result["output"] = result["error"]

    except FileNotFoundError:
        result["error"]  = f"Python interpreter not found: {interpreter}"
        result["output"] = result["error"]

    except Exception as e:
        result["error"]  = f"Unexpected execution error: {str(e)}"
        result["output"] = result["error"]

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return json.dumps(result)
