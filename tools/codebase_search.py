import json
import os
from typing import Optional
from utils.schema_helper import tool

# Singleton indexer — shared across all tool calls in a session
_indexer = None


def _get_indexer():
    global _indexer
    if _indexer is None:
        from rag import CodebaseIndexer
        _indexer = CodebaseIndexer()
    return _indexer


@tool
def codebase_search(
    query: str,
    n_results: int = 5,
    language: Optional[str] = None,
    auto_index: bool = True,
) -> str:
    """
    Semantically searches the codebase for code related to a concept or description.
    Returns ranked snippets with file paths and line numbers.

    HOW IT WORKS:
    - Your query is converted to a vector using a local AI embedding model.
    - That vector is compared against pre-indexed vectors of every function,
      class, and code block in the project.
    - The most semantically similar chunks are returned — even if they don't
      share keywords with your query.

    USAGE RULES:
    1. Use for SEMANTIC/CONCEPTUAL searches: "authentication logic", "error handling",
       "database connection setup", "JWT token validation".
    2. For EXACT searches (known function names, import strings), use grep_tool instead.
    3. After getting results, use read_file on the returned file_path to get full context.
    4. If you get 0 results, try rephrasing or call codebase_search with auto_index=True.
    5. Works best AFTER the codebase has been indexed (use /reindex in CLI, or set auto_index=True).

    :param query: Natural language description of what you are looking for.
    :param n_results: Number of top results to return (1-20, default 5).
    :param language: Optional language filter ('python', 'javascript', etc.).
    :param auto_index: If True (default), auto-indexes the project if not yet indexed.
    """
    result = {
        "status":   "failed",
        "query":    query,
        "results":  [],
        "output":   "",
        "error":    None,
    }

    if not query or not query.strip():
        result["error"] = "'query' cannot be empty."
        result["output"] = result["error"]
        return json.dumps(result)

    n_results = max(1, min(n_results, 20))

    try:
        indexer = _get_indexer()

        # Auto-index if empty
        if auto_index and not indexer.is_indexed():
            stats = indexer.index(".")
            index_note = (
                f"[Auto-indexed {stats['chunks_added']} chunks from "
                f"{stats['files_indexed']} files in {stats['duration_sec']}s]\n\n"
            )
        else:
            index_note = ""

        if not indexer.is_indexed():
            result["status"] = "success"
            result["output"] = (
                "Codebase is not indexed yet. Run /reindex in the CLI, "
                "or call this tool with auto_index=True."
            )
            return json.dumps(result)

        hits = indexer.search(query.strip(), n_results=n_results, language_filter=language)

        if not hits:
            result["status"] = "success"
            result["output"] = (
                f"{index_note}No results found for: '{query}'. "
                "Try rephrasing, or use grep_tool for exact matches."
            )
            return json.dumps(result)

        # Format output for LLM consumption
        lines = [f"{index_note}Semantic search results for: '{query}'\n"]
        for hit in hits:
            symbol_str = f" [{hit['symbol']}]" if hit.get("symbol") and hit["symbol"] != "__module_preamble__" else ""
            lines.append(
                f"[{hit['rank']}] {hit['file_path']} L{hit['start_line']}-{hit['end_line']}"
                f"{symbol_str}  (score: {hit['score']:.2f})"
            )
            lines.append(f"    {hit['snippet'][:200].replace(chr(10), ' ')}")
            lines.append("")

        lines.append(
            "→ Use read_file(file_path, offset=<start_line-1>) to read the full context."
        )

        result["status"]  = "success"
        result["results"] = hits
        result["output"]  = "\n".join(lines)

    except ImportError as e:
        result["error"]  = f"RAG dependencies not installed: {e}. Run: pip install chromadb sentence-transformers"
        result["output"] = result["error"]
    except Exception as e:
        result["error"]  = f"Search failed: {str(e)}"
        result["output"] = result["error"]

    return json.dumps(result)
