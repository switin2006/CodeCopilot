"""
Code chunker for RAG indexing.

Strategy:
  - .py files  → AST-aware: splits by top-level function/class definitions
                 so each chunk is a coherent unit of code
  - All others → Sliding window of RAG_CHUNK_SIZE lines with RAG_OVERLAP overlap

Each chunk dict has:
  {
    "content":    str,       # the actual code/text
    "file_path":  str,       # relative to project root
    "start_line": int,       # 1-indexed
    "end_line":   int,       # 1-indexed (inclusive)
    "language":   str,       # e.g. "python", "javascript", "markdown"
    "symbol":     str,       # function/class name if AST-extracted, else ""
  }
"""

import os
import ast
from typing import Iterator

# ------------------------------------------------------------------
# CONFIGURATION (mirrors utils/config.py — kept here to avoid circular)
# ------------------------------------------------------------------
_CHUNK_SIZE = 60    # lines per window chunk
_OVERLAP    = 15    # overlap lines between consecutive window chunks

# Extensions to index (text-based files only)
_INDEXED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rs", ".cpp", ".c", ".h",
    ".cs", ".rb", ".php", ".swift", ".kt",
    ".md", ".txt", ".yaml", ".yml", ".toml",
    ".json", ".html", ".css", ".sh", ".env.example",
}

# Directories to always skip
_SKIP_DIRS = {
    ".git", ".chroma", "__pycache__", "node_modules",
    "venv", "env", ".venv", ".tox", "dist", "build",
    ".eggs", "*.egg-info",
}

# Max file size to index (bytes)
_MAX_FILE_BYTES = 500_000   # 500 KB


# ------------------------------------------------------------------
# LANGUAGE DETECTION
# ------------------------------------------------------------------

_EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rs": "rust", ".cpp": "cpp", ".c": "c",
    ".h": "c", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".swift": "swift", ".kt": "kotlin", ".md": "markdown",
    ".txt": "text", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".json": "json", ".html": "html",
    ".css": "css", ".sh": "shell",
}

def _detect_language(file_path: str) -> str:
    _, ext = os.path.splitext(file_path)
    return _EXT_TO_LANG.get(ext.lower(), "text")


# ------------------------------------------------------------------
# PYTHON AST CHUNKER
# ------------------------------------------------------------------

def _chunk_python(file_path: str, lines: list[str]) -> list[dict]:
    """
    Splits a Python file into chunks at top-level function/class boundaries.
    Falls back to window chunker if AST parsing fails.
    """
    try:
        source = "".join(lines)
        tree = ast.parse(source)
    except SyntaxError:
        return _chunk_window(file_path, lines, "python")

    chunks = []
    top_nodes = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not isinstance(getattr(n, 'parent', None), (ast.FunctionDef, ast.ClassDef))
    ]

    # Mark parent relationships (simple approach)
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node   # type: ignore[attr-defined]

    # Filter: only top-level (parent is Module)
    top_level = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    if not top_level:
        return _chunk_window(file_path, lines, "python")

    for node in top_level:
        start = node.lineno - 1          # 0-indexed
        end   = node.end_lineno or start + 1  # type: ignore[attr-defined]
        end   = min(end, len(lines))

        # Grab a small preamble (decorators already included in lineno for Python ≥3.8)
        chunk_lines = lines[start:end]
        content = "".join(chunk_lines).strip()

        if not content:
            continue

        chunks.append({
            "content":    content,
            "file_path":  file_path,
            "start_line": start + 1,
            "end_line":   end,
            "language":   "python",
            "symbol":     node.name,
        })

    # Also add a module-level chunk (imports, constants at top of file)
    first_node_line = top_level[0].lineno - 1 if top_level else len(lines)
    preamble = "".join(lines[:first_node_line]).strip()
    if preamble:
        chunks.insert(0, {
            "content":    preamble,
            "file_path":  file_path,
            "start_line": 1,
            "end_line":   first_node_line,
            "language":   "python",
            "symbol":     "__module_preamble__",
        })

    return chunks


# ------------------------------------------------------------------
# SLIDING WINDOW CHUNKER (generic)
# ------------------------------------------------------------------

def _chunk_window(file_path: str, lines: list[str], language: str) -> list[dict]:
    """Overlapping sliding-window chunker — works for any text file."""
    chunks = []
    total  = len(lines)
    step   = max(1, _CHUNK_SIZE - _OVERLAP)
    start  = 0

    while start < total:
        end     = min(start + _CHUNK_SIZE, total)
        content = "".join(lines[start:end]).strip()
        if content:
            chunks.append({
                "content":    content,
                "file_path":  file_path,
                "start_line": start + 1,
                "end_line":   end,
                "language":   language,
                "symbol":     "",
            })
        if end >= total:
            break
        start += step

    return chunks


# ------------------------------------------------------------------
# PUBLIC API
# ------------------------------------------------------------------

def chunk_file(file_path: str, root: str = ".") -> list[dict]:
    """
    Chunk a single file into indexable pieces.

    Args:
        file_path: Absolute or relative path to the file.
        root:      Project root for computing relative paths stored in chunks.

    Returns:
        List of chunk dicts, or empty list if file is skipped/unreadable.
    """
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in _INDEXED_EXTENSIONS:
        return []

    try:
        if os.path.getsize(file_path) > _MAX_FILE_BYTES:
            return []
    except OSError:
        return []

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    if not lines:
        return []

    language    = _detect_language(file_path)
    rel_path    = os.path.relpath(file_path, root)

    if ext.lower() == ".py":
        chunks = _chunk_python(rel_path, lines)
    else:
        chunks = _chunk_window(rel_path, lines, language)

    return chunks


def chunk_directory(directory: str = ".") -> Iterator[dict]:
    """
    Walk a directory and yield chunks from all indexable files.

    Skips hidden directories, virtualenvs, build artifacts, and binary files.
    """
    abs_root = os.path.abspath(directory)

    for dirpath, dirnames, filenames in os.walk(abs_root):
        # Prune skip dirs in-place (prevents os.walk from descending)
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]

        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            for chunk in chunk_file(full_path, root=abs_root):
                yield chunk
