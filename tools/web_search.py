import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Literal
from utils.schema_helper import tool

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
_DDGO_URL = "https://api.duckduckgo.com/"
_DEFAULT_TIMEOUT = 10       # seconds
_MAX_RESULTS = 10

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------

def _ddg_query(query: str, num_results: int, region: str) -> list[dict]:
    """
    Calls DuckDuckGo Instant Answer API (no API key required).
    Returns a list of result dicts with title, url, snippet.
    """
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_redirect": "1",
        "no_html": "1",
        "kl": region,
    })
    url = f"{_DDGO_URL}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "CodeCopilot/1.0"})
    with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []

    # Abstract (best direct answer)
    if data.get("AbstractText"):
        results.append({
            "type": "abstract",
            "title": data.get("Heading", ""),
            "url": data.get("AbstractURL", ""),
            "snippet": data["AbstractText"],
        })

    # Related Topics
    for topic in data.get("RelatedTopics", []):
        if len(results) >= num_results:
            break
        # topics can be nested (Topics with sub-list)
        if "Topics" in topic:
            for sub in topic["Topics"]:
                if len(results) >= num_results:
                    break
                results.append({
                    "type": "related",
                    "title": sub.get("Text", "")[:80],
                    "url": sub.get("FirstURL", ""),
                    "snippet": sub.get("Text", ""),
                })
        else:
            results.append({
                "type": "related",
                "title": topic.get("Text", "")[:80],
                "url": topic.get("FirstURL", ""),
                "snippet": topic.get("Text", ""),
            })

    return results[:num_results]


# ------------------------------------------------------------------
# TOOL
# ------------------------------------------------------------------

@tool
def web_search(
    query: str,
    num_results: int = 5,
    region: str = "wt-wt",
) -> str:
    """
    Searches the web using DuckDuckGo and returns structured results.
    Use this tool to get up-to-date information, documentation, or answers
    that are not in your training data.

    USAGE RULES:
    1. Use for factual look-ups, library docs, error messages, or current events.
    2. Prefer specific queries (e.g., 'Python asyncio gather docs' not just 'asyncio').
    3. Always cite the source URL in your answer.

    :param query: The search query string.
    :param num_results: Number of results to return (1-10, default 5).
    :param region: DuckDuckGo region code for localized results (default 'wt-wt' = global).
    """
    result = {
        "status": "failed",
        "query": query,
        "results": [],
        "output": "",
        "error": None,
    }

    # 1. Validation
    if not query or not query.strip():
        result["error"] = "Query cannot be empty."
        result["output"] = result["error"]
        return json.dumps(result)

    num_results = max(1, min(num_results, _MAX_RESULTS))

    # 2. Search
    try:
        hits = _ddg_query(query.strip(), num_results, region)

        if not hits:
            result["status"] = "success"
            result["output"] = f"No results found for query: '{query}'. Try rephrasing."
            return json.dumps(result)

        # 3. Format output for LLM consumption
        lines = [f"Search results for: '{query}'\n"]
        for i, hit in enumerate(hits, 1):
            lines.append(f"[{i}] {hit['title']}")
            lines.append(f"    URL: {hit['url']}")
            lines.append(f"    {hit['snippet']}\n")

        result["status"] = "success"
        result["results"] = hits
        result["output"] = "\n".join(lines)

    except urllib.error.URLError as e:
        result["error"] = f"Network error: {str(e)}"
        result["output"] = result["error"]
    except Exception as e:
        result["error"] = f"Search failed: {str(e)}"
        result["output"] = result["error"]

    return json.dumps(result)
