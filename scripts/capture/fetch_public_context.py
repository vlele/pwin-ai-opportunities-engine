from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from typing import Any


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def fetch_url_excerpt(url: str, timeout: int = 20, max_chars: int = 4000) -> dict[str, Any]:
    if not url:
        return {"status": "skipped", "reason": "no URL provided"}
    request = urllib.request.Request(url, headers={"User-Agent": "pwin-ai-opportunities-v15"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read().decode("utf-8", errors="replace")
            text = SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(raw))).strip()
            return {
                "status": "ok",
                "url": url,
                "content_type": content_type,
                "text_excerpt": text[:max_chars],
            }
    except urllib.error.HTTPError as exc:
        return {"status": "http_error", "url": url, "code": exc.code}
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"status": "error", "url": url, "detail": str(exc)}
