import json
import urllib.request
import urllib.parse
import urllib.error
import html
import re
from typing import Optional
from utils.schema_helper import tool

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
_DEFAULT_TIMEOUT  = 15    # seconds
_MAX_CONTENT_LEN  = 8000  # chars to return to LLM


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------

def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode HTML entities."""
    # Remove <script> and <style> blocks entirely
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining tags
    raw = re.sub(r"<[^>]+>", " ", raw)
    # Decode HTML entities (&amp; etc.)
    raw = html.unescape(raw)
    # Collapse whitespace
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _extract_title(raw: str) -> str:
    """Extract <title> text from HTML."""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    return _strip_html(m.group(1)) if m else ""


# ------------------------------------------------------------------
# TOOL
# ------------------------------------------------------------------

@tool
def fetch_url(
    url: str,
    extract_text: bool = True,
    timeout: int = 15,
) -> str:
    """
    Fetches the content of a URL and returns the page text.
    Use this tool to read documentation, articles, API references, or web pages
    found via web_search.

    USAGE RULES:
    1. Only fetch URLs that are public and do not require authentication.
    2. Prefer 'extract_text=True' (default) — returns clean readable text.
    3. Set 'extract_text=False' only if you need raw HTML for analysis.
    4. Content is truncated to 8,000 characters; use offset queries if you need more.

    :param url: The full URL to fetch (must start with http:// or https://).
    :param extract_text: If True (default), strips HTML and returns plain text.
    :param timeout: Request timeout in seconds (default 15).
    """
    result = {
        "status": "failed",
        "url": url,
        "title": "",
        "content": "",
        "content_length": 0,
        "is_truncated": False,
        "output": "",
        "error": None,
    }

    # 1. Validation
    if not url or not url.strip():
        result["error"] = "'url' cannot be empty."
        result["output"] = result["error"]
        return json.dumps(result)

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        result["error"] = f"Invalid URL: must start with http:// or https://. Got: '{url}'"
        result["output"] = result["error"]
        return json.dumps(result)

    # 2. Fetch
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; CodeCopilot/1.0; "
                    "+https://github.com/CodeCopilot)"
                ),
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        with urllib.request.urlopen(req, timeout=min(timeout, 30)) as resp:
            # Check content-type
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()

            raw_bytes = resp.read(512 * 1024)  # max 512 KB download
            raw_str = raw_bytes.decode(charset, errors="replace")

    except urllib.error.HTTPError as e:
        result["error"] = f"HTTP {e.code}: {e.reason} — {url}"
        result["output"] = result["error"]
        return json.dumps(result)
    except urllib.error.URLError as e:
        result["error"] = f"Network error fetching '{url}': {str(e.reason)}"
        result["output"] = result["error"]
        return json.dumps(result)
    except Exception as e:
        result["error"] = f"Unexpected fetch error: {str(e)}"
        result["output"] = result["error"]
        return json.dumps(result)

    # 3. Process Content
    title = _extract_title(raw_str)
    content = _strip_html(raw_str) if extract_text else raw_str

    result["title"] = title
    result["content_length"] = len(content)

    if len(content) > _MAX_CONTENT_LEN:
        content = content[:_MAX_CONTENT_LEN]
        result["is_truncated"] = True

    result["content"] = content
    result["status"] = "success"

    # 4. LLM-friendly output
    truncation_note = (
        f"\n\n[Content truncated at {_MAX_CONTENT_LEN} chars. "
        f"Full page has {result['content_length']} chars.]"
        if result["is_truncated"] else ""
    )
    result["output"] = (
        f"URL: {url}\n"
        f"Title: {title or 'N/A'}\n"
        f"---\n"
        f"{content}"
        f"{truncation_note}"
    )

    return json.dumps(result)
