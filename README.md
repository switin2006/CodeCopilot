<div align="center">

# ✦ CodeCopilot ✦

### A terminal-native, multi-agent AI coding assistant with semantic codebase search

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Cerebras](https://img.shields.io/badge/Inference-Cerebras-FF6B00?style=flat-square)](https://cerebras.ai)
[![ChromaDB](https://img.shields.io/badge/RAG-ChromaDB-7E22CE?style=flat-square)](https://www.trychroma.com)

CodeCopilot is an autonomous AI coding agent that lives in your terminal. It plans tasks, edits files, runs code, searches the web, and delegates work to specialized sub-agents — all driven by 14 native function-calling tools and a local semantic search index over your codebase.

</div>

---

## ✨ Highlights

| | |
|---|---|
| 🧠 **Multi-agent** | An orchestrator agent spawns isolated worker agents for parallel sub-tasks |
| 🎭 **Personas** | Auto-routes each request to a `coder`, `debugger`, or `default` persona |
| 🔬 **Semantic RAG** | AST-aware Python chunker + sentence-transformers + ChromaDB |
| ⚡ **14 Tools** | File I/O, shell, code execution, web search, glob/grep, planning, and more |
| 🛡️ **Sandboxed** | Path traversal protection, secret-file blocklist, per-tool confirmation for writes |
| 🌐 **Project-portable** | Run against any project folder via `--workdir` |
| 🔌 **OpenAI-compatible** | Works with Cerebras, Groq, HF Router, Ollama — anything that speaks the OpenAI chat API |

---

## 🎬 Quick Demo

```text
[19:24] ❯ Build a developer portfolio web app: research glassmorphism designs,
          ask me my accent color, generate mock data, write the HTML/CSS,
          and serve it on port 8000.

→ CODER persona

  🗺️  plan        action=create        ✓ done   (8-step plan)
  🌐  web_search  Modern CSS Glassmorphism tutorials   ✓ done
  ❓  question    What is your favorite accent color?  → "Orange"
  🔬  codebase_search  HTML CSS files                  ✓ done
  📂  list_files  path=.                               ✓ done
  🔍  glob_tool   pattern=**/*.html                    ✓ done
  ✍️   write_file  generate_data.py                     ✓ done
  🐍  code_exec   ran generate_data.py                 ✓ done
  🤖  spawn_agent worker writes style.css (orange)     ✓ done   (12 tool calls)
  ✍️   write_file  index.html                           ✓ done
  🔧  edit_file   add "Built by CodeCopilot" footer    ✓ done
  ⚡  bash_tool  python -m http.server 8000            ↩ serving on :8000

  ✦ Plan COMPLETE: 'Developer Portfolio Web App'
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- An API key from any OpenAI-compatible provider. CodeCopilot defaults to [Cerebras](https://cloud.cerebras.ai) (free tier, fast inference, native tool calling).

### 1. Clone & Install

```bash
git clone https://github.com/<your-username>/CodeCopilot.git
cd CodeCopilot
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

### 2. Configure your API key

Create a `.env` in the project root:

```dotenv
# Cerebras (recommended — free, fast, generous quota)
CEREBRAS_API_KEY="csk-..."

# Or any other OpenAI-compatible backend:
# OPENAI_API_KEY="..."
# OPENAI_BASE_URL="https://api.groq.com/openai/v1"
# MODEL_ID="llama-3.3-70b-versatile"
```

### 3. Run

```bash
python cli.py                                  # operate on current directory
python cli.py --workdir D:\some\other\project  # operate on another project
python cli.py --persona coder                  # skip auto-routing
```

On Windows you can use the launcher to run from anywhere:

```cmd
codecopilot.bat
codecopilot.bat --workdir D:\my-project
```

Add the install dir to PATH so `codecopilot` works globally:

```powershell
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\path\to\CodeCopilot", "User")
```

---

## 🧰 The 14 Tools

| Icon | Tool | What it does |
|---|---|---|
| 📂 | `list_files` | List files and directories |
| 🔍 | `glob_tool` | Match files by pattern (`**/*.py`) |
| 🔎 | `grep_tool` | Regex search across files |
| 📖 | `read_file` | Read a file with offset/limit |
| ✍️  | `write_file` | Create or overwrite a file *(prompts for confirmation)* |
| 🔧 | `edit_file` | Modify an existing file *(prompts for confirmation)* |
| ⚡ | `bash_tool` | Run shell commands (sandboxed cwd) |
| 🐍 | `code_exec` | Execute Python snippets in a subprocess |
| 🌐 | `web_search` | Search the web via DuckDuckGo |
| 🌍 | `fetch_url` | Fetch and extract text from a URL |
| 🔬 | `codebase_search` | Semantic search over your project (RAG) |
| 🗺️  | `plan` | Create / track a structured execution plan |
| ❓ | `question_tool` | Ask the user a clarifying question |
| 🤖 | `spawn_agent` | Delegate a sub-task to an isolated worker agent |

Tools that modify files (`write_file`, `edit_file`) always pause for `[Y/n]` confirmation.

---

## 🤖 Multi-Agent Architecture

```mermaid
flowchart TD
    User([👤 User]) -->|prompt| CLI[💻 cli.py<br/>Interactive REPL]
    CLI -->|first message| Router{🧭 Persona Router<br/>LLM classifier}
    Router -->|coder| Orch
    Router -->|debugger| Orch
    Router -->|default| Orch

    Orch[🎯 Orchestrator Agent<br/>main.py<br/>14 tools, 20-turn budget]

    Orch -->|chat completion + tools=| LLM[(☁️ Inference Backend<br/>Cerebras / Groq / HF / Ollama)]
    LLM -->|tool_calls[]| Orch

    Orch -->|parallel ThreadPool| TBox[🔧 Tool Execution Layer]

    TBox --> FS[📂 File Tools<br/>read · write · edit<br/>list · glob · grep]
    TBox --> Shell[⚡ Shell Tools<br/>bash_tool · code_exec]
    TBox --> Web[🌐 Web Tools<br/>web_search · fetch_url]
    TBox --> Plan[🗺️ plan · 📓 notebook<br/>structured tracking]
    TBox --> Q[❓ question_tool<br/>asks user mid-loop]
    TBox --> RAG[🔬 codebase_search]
    TBox --> Spawn[🤖 spawn_agent]

    RAG --> Vec[(💾 ChromaDB<br/>.chroma/)]
    Vec --> Embed[🧠 sentence-transformers<br/>all-MiniLM-L6-v2 · 384-d]

    Spawn -->|isolated context| WA[👷 Worker A<br/>coder · 13 tools<br/>15-turn cap]
    Spawn -->|isolated context| WB[👷 Worker B<br/>debugger · 13 tools]
    Spawn -->|isolated context| WC[👷 Worker C<br/>default · 13 tools]

    WA -->|own loop| LLM
    WB -->|own loop| LLM
    WC -->|own loop| LLM

    FS --> Sandbox[🛡️ secure_fs<br/>path sandbox + blocklist]
    Shell --> Sandbox

    style User fill:#1e293b,stroke:#22d3ee,color:#fff
    style Orch fill:#7c3aed,stroke:#a78bfa,color:#fff
    style LLM fill:#0f766e,stroke:#14b8a6,color:#fff
    style RAG fill:#9333ea,stroke:#c084fc,color:#fff
    style Spawn fill:#dc2626,stroke:#f87171,color:#fff
    style WA fill:#a78bfa,stroke:#c4b5fd,color:#000
    style WB fill:#f97316,stroke:#fb923c,color:#000
    style WC fill:#22d3ee,stroke:#67e8f9,color:#000
    style Sandbox fill:#dc2626,stroke:#fca5a5,color:#fff
    style Vec fill:#0891b2,stroke:#22d3ee,color:#fff
```

**Key invariants:**

- The **orchestrator** has all 14 tools. Workers get 13 (no `spawn_agent` → no recursion).
- **Tool calls execute in parallel** when the LLM returns multiple in one turn (`ThreadPoolExecutor`, max 4 concurrent).
- Workers get a **fresh memory** plus an explicit `context` argument from the orchestrator — they don't share state with the parent or with each other.
- **Hard caps:** orchestrator 20 turns, workers 15 turns. Prevents runaway loops.

---

## 🔬 How RAG Works Here

```mermaid
flowchart LR
    subgraph Indexing["🏗️ Indexing  (one-time per project)"]
        direction TB
        Files[📁 Project files<br/>.py .md .js .ts ...] --> Chunker[✂️ chunker.py]
        Chunker -->|Python| AST[🐍 AST split<br/>by class / def]
        Chunker -->|other| Window[📐 60-line window<br/>15-line overlap]
        AST --> Pieces[📦 Chunks<br/>+ file_path<br/>+ line range<br/>+ symbol]
        Window --> Pieces
        Pieces --> Embed1[🧠 MiniLM-L6-v2<br/>384-dim vectors]
        Embed1 --> Store[(💾 ChromaDB<br/>cosine HNSW)]
    end

    subgraph Retrieval["🔍 Retrieval  (every codebase_search call)"]
        direction TB
        Query[💬 Natural language<br/>'how is attention computed?'] --> Embed2[🧠 MiniLM-L6-v2]
        Embed2 --> Vec[📍 Query vector]
        Vec --> Search{🎯 Nearest-neighbor<br/>cosine similarity}
        Store -.cached.-> Search
        Search --> TopN[🏆 Top-N hits<br/>+ score<br/>+ snippet<br/>+ line numbers]
        TopN --> Agent[🤖 Agent reads<br/>relevant files]
    end

    style Files fill:#1e293b,stroke:#475569,color:#fff
    style Chunker fill:#7c3aed,stroke:#a78bfa,color:#fff
    style AST fill:#9333ea,stroke:#c084fc,color:#fff
    style Window fill:#9333ea,stroke:#c084fc,color:#fff
    style Embed1 fill:#0891b2,stroke:#22d3ee,color:#fff
    style Embed2 fill:#0891b2,stroke:#22d3ee,color:#fff
    style Store fill:#0f766e,stroke:#14b8a6,color:#fff
    style Search fill:#dc2626,stroke:#f87171,color:#fff
    style TopN fill:#16a34a,stroke:#4ade80,color:#fff
    style Agent fill:#1e293b,stroke:#22d3ee,color:#fff
```

**Why this design:**

1. **AST chunking for Python** — each chunk is a coherent function or class, not an arbitrary 500-character slice. Far better signal-to-noise than naive splitting.
2. **MiniLM-L6-v2** — 22 MB, 384-d, runs on CPU at ~14k sentences/sec. No GPU, no API keys, no per-query cost.
3. **Cosine + HNSW** — correct distance metric for sentence embeddings, and HNSW gives sub-millisecond approximate-nearest-neighbor lookup even at tens of thousands of chunks.
4. **Per-project store** — each `--workdir` gets its own `.chroma/`. No cross-contamination.
5. **Deterministic chunk IDs** — `md5(file_path + lines)` means re-indexing is incremental, not "wipe and rebuild".

**RAG shines for conceptual queries** (*"where is the noise schedule for diffusion sampling?"*). For exact-string searches, the agent uses `grep_tool` instead. The model decides which to use.

---

## 🛡️ Safety

- **Path sandbox.** All file tools resolve paths against the project root and reject anything outside it (path traversal, symlink attacks).
- **Sensitive files blocked.** `.env`, `.git/`, `id_rsa`, hidden dotfiles — read or write attempts fail at the tool layer.
- **Confirmation gate.** `write_file` and `edit_file` prompt the user for `[Y/n]` before applying changes.
- **No spawn recursion.** Workers cannot spawn further workers, preventing infinite agent trees.
- **Turn limits.** Orchestrator: 20 turns. Workers: 15 turns. Hard caps prevent runaway loops.

---

## 🎮 CLI Commands

| Command | Action |
|---|---|
| `/help` | Show all commands |
| `/tools` | List all loaded tools |
| `/clear` | Clear conversation history |
| `/persona <name>` | Switch persona: `coder` \| `debugger` \| `default` |
| `/reindex` | Rebuild the RAG index incrementally |
| `/reindex --force` | Wipe and rebuild the RAG index |
| `/cwd` | Show current working directory |
| `exit` / `quit` | Exit |

---

## 🎭 Personas

| Persona | Best for | System prompt focus |
|---|---|---|
| **coder** | Building features, refactoring, writing new code | "Senior Software Engineer", planning + safety |
| **debugger** | Fixing bugs, diagnosing errors, tracing failures | "Principal Code Debugging Specialist", evidence-first |
| **default** | Research, explanations, mixed tasks | General-purpose with web access |

By default the CLI **auto-routes** each first message via a small classifier model. Use `--persona <name>` to lock in one persona.

---

## ⚙️ Configuration

All settings live in `utils/config.py` and can be overridden via `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `CEREBRAS_API_KEY` | — | API key for Cerebras |
| `OPENAI_BASE_URL` | `https://api.cerebras.ai/v1` | Inference backend URL |
| `MODEL_ID` | `zai-glm-4.6` | Main agent model |
| `ROUTER_MODEL` | same as `MODEL_ID` | Persona-classification model |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | RAG embedding model |
| `MAX_AGENTIC_TURNS` | `20` | Max LLM↔tool loops per message |
| `MAX_PARALLEL_TOOLS` | `4` | Max concurrent tool calls per turn |

---

## 📁 Project Structure

```
CodeCopilot/
├── cli.py                    # Interactive terminal UI
├── main.py                   # Orchestrator agent + agentic loop
├── tool_registry.py          # Auto-discovers tools from tools/
├── codecopilot.bat           # Windows launcher
│
├── agents/
│   ├── router.py             # Persona classifier
│   └── worker.py             # Isolated WorkerAgent (no recursion)
│
├── tools/                    # 14 tools — drop-in autoloaded
│   ├── bash.py    code_exec.py    codebase_search.py
│   ├── edit.py    fetch_url.py    glob.py    grep.py
│   ├── list.py    plan.py    question.py    read.py
│   ├── spawn_agent.py    web_search.py    write.py
│
├── rag/
│   ├── chunker.py            # AST + sliding-window chunking
│   ├── embedder.py           # sentence-transformers wrapper
│   └── indexer.py            # ChromaDB persistence + search
│
└── utils/
    ├── config.py             # Central Config dataclass + AgentEvent
    ├── context.py            # Conversation memory + token budgeting
    ├── prompts.py            # Persona system prompts
    ├── schema_helper.py      # @tool decorator + JSON schema generation
    └── secure_fs.py          # Path sandbox + blocklist
```

---

## 🧪 Stress Test Prompt

Drop this single prompt into the CLI to exercise every tool:

```
Build a Developer Portfolio Web App. You MUST follow these steps and use the
exact tools mentioned:
1. plan(action='create') — break this into phases.
2. web_search + fetch_url — find a glassmorphism CSS tutorial.
3. question_tool — ask my favorite accent color.
4. codebase_search + glob_tool — see what HTML/CSS exists.
5. write_file + code_exec — generate_data.py with mock JSON.
6. spawn_agent — delegate writing style.css to a worker (use the color).
7. write_file — create index.html.
8. edit_file — add "Built by CodeCopilot" footer.
9. bash_tool — serve on port 8000.
```

This exercises 13 of 14 tools (everything except a second `spawn_agent`) and chains them through a structured plan.

---

## 🛠️ Troubleshooting

**`401 Unauthorized` from the LLM.** Check that the right API key for your active backend is in `.env` and that no stale system env var (`OPENAI_API_KEY`) is overriding it. Restart the CLI after editing `.env`.

**`429 queue_exceeded`.** The provider's free-tier inference queue is busy. Wait 30s and retry, or set `MODEL_ID` to a smaller model in `.env`.

**`codebase_search` returns nothing.** Run `/reindex --force` inside the CLI. Check that your project has files with extensions in the indexable list (`.py`, `.js`, `.ts`, `.md`, etc.).

**Agent ignores `codebase_search` for simple lookups.** That's correct behavior — for small projects, `list_files` + `read_file` is faster than RAG. Phrase concept-style queries to nudge it: *"find the part that handles X, even if X isn't an exact keyword."*

---

## 📜 License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
<sub>Built with ❤️ in the terminal. Powered by your favorite OpenAI-compatible LLM.</sub>
</div>
