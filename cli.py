"""
CodeCopilot CLI entry point.

Supports running against any project directory, not just CodeCopilot itself:

    codecopilot                            # operate on current directory
    codecopilot --workdir D:/my-project    # operate on a different project
    codecopilot -C ../other-repo           # short form

The --workdir flag MUST be parsed before importing the agent stack, because
utils/secure_fs.py snapshots PROJECT_ROOT from os.getcwd() at import time.
"""
import os
import sys
import json
import asyncio
import argparse
from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────
#  EARLY: parse --workdir and chdir BEFORE
#  any project module is imported.
# ─────────────────────────────────────────────

def _early_parse_workdir() -> tuple:
    """
    Pull --workdir / -C out of sys.argv before argparse does its real run.
    Returns (target_dir, remaining_argv) and DOES NOT consume any other flags.
    """
    target = None
    cleaned = [sys.argv[0]]
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a in ("--workdir", "-C"):
            if i + 1 >= len(sys.argv):
                print(f"Error: {a} requires a path argument.", file=sys.stderr)
                sys.exit(2)
            target = sys.argv[i + 1]
            i += 2
        elif a.startswith("--workdir="):
            target = a.split("=", 1)[1]
            i += 1
        else:
            cleaned.append(a)
            i += 1
    sys.argv = cleaned
    return target


_workdir = _early_parse_workdir()

# Resolve CodeCopilot's own install dir so we can find its .env later,
# regardless of where the user launches from.
_CODECOPILOT_DIR = os.path.dirname(os.path.abspath(__file__))

if _workdir:
    target_abs = os.path.abspath(os.path.expanduser(_workdir))
    if not os.path.isdir(target_abs):
        print(f"Error: workdir does not exist or is not a directory: {target_abs}",
              file=sys.stderr)
        sys.exit(2)
    os.chdir(target_abs)
    print(f"[CodeCopilot] Working in: {target_abs}")

# Load .env from CodeCopilot's install dir FIRST so HF_TOKEN is found
# even if the user's project folder doesn't have its own .env.
# Then load the project's .env (if any) to allow per-project overrides.
try:
    from dotenv import load_dotenv
    _project_env = os.path.join(os.getcwd(), ".env")
    _install_env = os.path.join(_CODECOPILOT_DIR, ".env")
    if os.path.exists(_install_env):
        load_dotenv(_install_env, override=False)
    if os.path.exists(_project_env) and os.path.abspath(_project_env) != os.path.abspath(_install_env):
        # project-level .env wins over install-level (override=True)
        load_dotenv(_project_env, override=True)
except Exception:
    pass

# Make sure CodeCopilot's own modules are importable even when cwd is elsewhere.
if _CODECOPILOT_DIR not in sys.path:
    sys.path.insert(0, _CODECOPILOT_DIR)

# ─────────────────────────────────────────────
#  Now safe to import the rest
# ─────────────────────────────────────────────

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich import box

from main import Agent, AgentEvent, Config
from agents.router import route_persona
from tool_registry import get_all_tool_schemas

# ─────────────────────────────────────────────
#  Console & Style
# ─────────────────────────────────────────────
console = Console()

prompt_style = Style.from_dict({
    "prompt": "#00d7ff bold",
})

# ─────────────────────────────────────────────
#  Visual Helpers
# ─────────────────────────────────────────────

BANNER = r"""
  ____          _        ____            _ _       _
 / ___|___   __| | ___  / ___|___  _ __ (_) | ___ | |_
| |   / _ \ / _` |/ _ \| |   / _ \| '_ \| | |/ _ \| __|
| |__| (_) | (_| |  __/| |__| (_) | |_) | | | (_) | |_
 \____\___/ \__,_|\___| \____\___/| .__/|_|_|\___/ \__|
                                  |_|
"""

TOOL_ICONS = {
    "bash_tool":        "⚡",
    "read_file":        "📖",
    "write_file":       "✍️ ",
    "edit_file":        "🔧",
    "list_files":       "📂",
    "glob_tool":        "🔍",
    "grep_tool":        "🔎",
    "web_search":       "🌐",
    "fetch_url":        "🌍",
    "memory":           "🧠",
    "todo":             "📋",
    "notebook":         "📓",
    "question_tool":    "❓",
    "plan":             "🗺️ ",
    "code_exec":        "🐍",
    "spawn_agent":      "🤖",
}

PERSONA_COLORS = {
    "coder":    "#a78bfa",   # purple
    "debugger": "#f97316",   # orange
    "default":  "#22d3ee",   # cyan
}

def _persona_color(persona: str) -> str:
    return PERSONA_COLORS.get(persona, "#22d3ee")


def print_banner(persona: str, tool_count: int = 0, auto_routed: bool = False):
    color = _persona_color(persona)
    console.print(f"[bold {color}]{BANNER}[/bold {color}]")
    route_note = "  [dim](auto-routed)[/dim]" if auto_routed else ""
    console.print(
        Panel.fit(
            f"[bold white]Model:[/bold white] [dim]{Config.MODEL_ID}[/dim]   "
            f"[bold white]Persona:[/bold white] [{color}]{persona.upper()}[/{color}]{route_note}   "
            f"[bold white]Tools:[/bold white] [dim]{tool_count or '?'} loaded[/dim]\n"
            f"[bold white]Workdir:[/bold white] [dim]{os.getcwd()}[/dim]\n"
            f"[dim]Type [bold white]/help[/bold white] for commands  •  "
            f"[bold white]/tools[/bold white] to list tools  •  "
            f"[bold white]exit[/bold white] to quit[/dim]",
            border_style=color,
            title=f"[bold {color}]✦ CodeCopilot ✦[/bold {color}]",
        )
    )


def print_tool_call(tool_name: str, args: dict):
    icon = TOOL_ICONS.get(tool_name, "🔩")
    args_preview = ", ".join(
        f"[dim]{k}[/dim]=[cyan]{str(v)[:40]}[/cyan]"
        for k, v in args.items()
        if v is not None
    )
    console.print(
        f"  {icon} [bold yellow]{tool_name}[/bold yellow]  {args_preview}",
        highlight=False,
    )


def print_tool_result_summary(tool_name: str, raw_result: str):
    """Shows a one-line status badge after a tool completes."""
    try:
        res = json.loads(raw_result)
        status = res.get("status", "")
        error  = res.get("error")
        if error:
            badge = f"[bold red]✗ failed[/bold red]  [dim]{str(error)[:60]}[/dim]"
        elif status == "success":
            badge = "[bold green]✓ done[/bold green]"
        else:
            badge = "[dim]↩ returned[/dim]"
    except Exception:
        badge = "[dim]↩ returned[/dim]"

    console.print(f"    └─ {badge}", highlight=False)


def format_diff(diff_text: str) -> Syntax:
    return Syntax(diff_text, "diff", theme="monokai", line_numbers=True)


def print_help():
    table = Table(
        title="[bold cyan]Available Commands[/bold cyan]",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("Command", style="bold yellow", no_wrap=True)
    table.add_column("Description")
    table.add_row("/help",              "Show this help message")
    table.add_row("/tools",             "List all loaded tools with descriptions")
    table.add_row("/clear",             "Clear conversation history")
    table.add_row("/persona <name>",    "Switch persona: coder | debugger | default")
    table.add_row("/cwd",               "Show current working directory")
    table.add_row("exit / quit",        "Exit CodeCopilot")
    console.print(table)


def print_tools_table(schemas: list):
    table = Table(
        title="[bold cyan]Loaded Tools[/bold cyan]",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold white",
    )
    table.add_column("#",    style="dim", width=3)
    table.add_column("Icon", width=4)
    table.add_column("Name",        style="bold yellow", no_wrap=True)
    table.add_column("Description", style="white")

    for i, schema in enumerate(schemas, 1):
        fn = schema.get("function", {})
        name = fn.get("name", "?")
        desc = fn.get("description", "").split("\n")[0][:65]
        icon = TOOL_ICONS.get(name, "🔩")
        table.add_row(str(i), icon, name, desc)

    console.print(table)

# ─────────────────────────────────────────────
#  Question Tool Callback
# ─────────────────────────────────────────────

async def question_callback(questions: list) -> list:
    """
    Async callback wired into question_tool so the agent can ask
    the user mid-execution without blocking the event loop.
    """
    console.print(Rule("[bold yellow]⟳ Agent needs your input[/bold yellow]", style="yellow"))
    answers = []
    session = PromptSession()
    for q in questions:
        console.print(f"  [bold cyan]?[/bold cyan] {q}")
        ans = await session.prompt_async("  ❯ ", style=prompt_style)
        answers.append(ans.strip())
    console.print(Rule(style="yellow"))
    return answers

# ─────────────────────────────────────────────
#  Main Loop
# ─────────────────────────────────────────────

async def main_loop(persona: str = "auto"):
    all_schemas   = get_all_tool_schemas(refresh=True)
    tool_count    = len(all_schemas)
    auto_mode     = (persona == "auto")
    current_persona = "coder" if auto_mode else persona

    print_banner(current_persona, tool_count=tool_count)



    agent: Optional[Agent] = None
    if not auto_mode:
        try:
            agent = Agent(persona=persona)
        except Exception as e:
            console.print(f"[bold red]Initialization Error:[/bold red] {e}")
            console.print(
                "[dim]Tip: make sure HF_TOKEN is set in your .env file. "
                "Get a free token at https://huggingface.co/settings/tokens[/dim]"
            )
            return

    session = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
    )


    while True:
        try:
            ts = datetime.now().strftime("%H:%M")
            prompt_text = [
                ("class:prompt", f"\n[{ts}] ❯ "),
            ]
            user_input = await session.prompt_async(prompt_text, style=prompt_style)
            user_input = user_input.strip()

            if not user_input:
                continue

            # ── Slash Commands ───────────────────────────────────────
            if user_input.lower() in ("exit", "quit"):
                console.print("\n[dim]Goodbye. 👋[/dim]\n")
                break

            if user_input.lower() == "/help":
                print_help()
                continue

            if user_input.lower() == "/cwd":
                console.print(f"[dim]Working dir: {os.getcwd()}[/dim]")
                continue

            if user_input.lower() == "/tools":
                print_tools_table(agent.tools if agent else all_schemas)
                continue

            if user_input.lower() == "/clear":
                if agent:
                    agent.clear_memory()
                console.print("[dim]✓ Conversation history cleared.[/dim]")
                continue



            if user_input.lower().startswith("/persona"):
                parts = user_input.split()
                if len(parts) < 2:
                    console.print("[yellow]Usage: /persona <coder|debugger|default>[/yellow]")
                    continue
                new_persona = parts[1].lower()
                if new_persona not in ("coder", "debugger", "default"):
                    console.print(f"[red]Unknown persona '{new_persona}'. Choose: coder, debugger, default[/red]")
                    continue
                try:
                    agent = Agent(persona=new_persona)
                    current_persona = new_persona
                    auto_mode = False
                    color = _persona_color(new_persona)
                    console.print(f"[{color}]✓ Switched to persona: {new_persona.upper()}[/{color}]")
                except Exception as e:
                    console.print(f"[red]Failed to switch persona: {e}[/red]")
                continue

            # ── Auto-routing (lazy agent init) ────────────────────
            if agent is None:
                if auto_mode:
                    with Live(
                        Spinner("dots2", text=" [dim]Routing...[/dim]"),
                        refresh_per_second=10,
                        transient=True,
                    ):
                        current_persona, route_method = route_persona(user_input)

                    color = _persona_color(current_persona)
                    method_badge = (
                        "[dim cyan][llm][/dim cyan]"          if route_method == "llm"
                        else "[dim yellow][cache][/dim yellow]" if route_method == "cache"
                        else "[dim red][fallback][/dim red]"
                    )
                    console.print(
                        f"[dim]→ [{color}]{current_persona.upper()}[/{color}] persona  {method_badge}[/dim]"
                    )
                try:
                    agent = Agent(persona=current_persona)
                except Exception as e:
                    console.print(f"[bold red]Initialization Error:[/bold red] {e}")
                    console.print(
                        "[dim]Tip: make sure HF_TOKEN is set in your .env file. "
                        "Get a free token at https://huggingface.co/settings/tokens[/dim]"
                    )
                    continue

            # ── Agent Chat ───────────────────────────────────────────
            console.print("")
            color = _persona_color(current_persona)

            spinner = Spinner("dots2", text=f" [{color}]Thinking...[/{color}]")
            with Live(spinner, refresh_per_second=15, transient=True) as live:

                for event in agent.chat(user_input):

                    if event.type == "tool_call":
                        live.stop()
                        print_tool_call(event.tool_name, event.tool_args or {})

                        if event.tool_name in ["write_file", "edit_file"]:
                            ans = await session.prompt_async("  [bold yellow]⚠ Allow this file modification? [Y/n] ❯ [/bold yellow]")
                            if ans.strip().lower() in ["n", "no"]:
                                event.content = "REJECTED"
                                console.print("  [red]✗ Action rejected by user.[/red]")

                        live.start()
                        live.update(
                            Spinner("dots2", text=f" [{color}]{TOOL_ICONS.get(event.tool_name,'🔩')} {event.tool_name}...[/{color}]")
                        )

                    elif event.type == "tool_result":
                        live.stop()

                        if event.tool_name == "edit_file":
                            try:
                                res_dict = json.loads(event.content)
                                if res_dict.get("diff") and res_dict["diff"] != "No changes made.":
                                    console.print(f"    [bold blue]↳ {res_dict.get('path', '')}[/bold blue]")
                                    console.print(format_diff(res_dict["diff"]))
                            except Exception:
                                pass

                        if event.tool_name == "spawn_agent":
                            try:
                                res_dict = json.loads(event.content)
                                if res_dict.get("status") == "success":
                                    worker_persona = res_dict.get("worker_persona", "?")
                                    tc_count = res_dict.get("tool_calls_made", 0)
                                    w_color = _persona_color(worker_persona)
                                    console.print(
                                        Panel(
                                            res_dict.get("answer", "")[:400] + "..."
                                            if len(res_dict.get("answer", "")) > 400
                                            else res_dict.get("answer", ""),
                                            title=f"[bold {w_color}]🤖 Worker [{worker_persona.upper()}]  {tc_count} tool calls[/bold {w_color}]",
                                            border_style=w_color,
                                            padding=(0, 1),
                                        )
                                    )
                            except Exception:
                                pass

                        print_tool_result_summary(event.tool_name, event.content)
                        live.start()
                        live.update(Spinner("dots2", text=f" [{color}]Thinking...[/{color}]"))

                    elif event.type == "question":
                        live.stop()
                        try:
                            q_args = json.loads(event.content) if isinstance(event.content, str) else event.content
                            questions = q_args if isinstance(q_args, list) else [str(q_args)]
                            answers = await question_callback(questions)
                            event.answers = answers
                        except Exception as e:
                            console.print(f"[red]Question handling error: {e}[/red]")
                        live.start()

                    elif event.type == "answer":
                        live.stop()
                        console.print(
                            Panel(
                                Markdown(event.content),
                                title=f"[bold {color}]✦ Copilot[/bold {color}]",
                                border_style=color,
                                padding=(1, 2),
                            )
                        )

                    elif event.type == "error":
                        live.stop()
                        console.print(
                            Panel(
                                f"[bold red]{event.content}[/bold red]",
                                title="[bold red]⚠ Error[/bold red]",
                                border_style="red",
                            )
                        )
                        break

        except KeyboardInterrupt:
            console.print("\n[dim](Use 'exit' to quit)[/dim]")
            continue
        except EOFError:
            console.print("\n[dim]Goodbye. 👋[/dim]\n")
            break
        except Exception as e:
            console.print(f"[bold red]Unexpected Error:[/bold red] {e}")

# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="CodeCopilot — Agentic AI Coding Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  codecopilot                              # use current directory\n"
            "  codecopilot --workdir D:\\my-project     # operate on another project\n"
            "  codecopilot -C ..\\other-repo --persona coder\n"
            "\n"
            "Personas:\n"
            "  --persona auto     # routes per message (default)\n"
            "  --persona coder    # always coder\n"
            "  --persona debugger # always debugger\n"
            "  --persona default  # always default\n"
        ),
    )
    # NOTE: --workdir / -C is intentionally re-declared here so it shows up
    # in --help, but the actual chdir happens earlier (before any imports).
    parser.add_argument(
        "--workdir", "-C",
        metavar="DIR",
        help="Run against this project directory instead of cwd.",
    )
    parser.add_argument(
        "--persona",
        choices=["auto", "coder", "debugger", "default"],
        default="auto",
        help="Agent persona (default: auto — routes per message)",
    )
    return parser.parse_args()


def main_sync():
    args = parse_args()
    asyncio.run(main_loop(persona=args.persona))

if __name__ == "__main__":
    main_sync()
