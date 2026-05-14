"""Web search connector for enrichment – lightweight search + cached results."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

import httpx

from ..core.db import DatabaseManager, _now

log = logging.getLogger(__name__)


class WebSearchConnector:
    """Search the web using DuckDuckGo HTML or a configurable search API."""

    def __init__(self, db: DatabaseManager, search_api: str = "duckduckgo"):
        self._db = db
        self._search_api = search_api

    def search(self, query: str, lead_id: str = "", max_results: int = 5) -> list[dict]:
        """Search and cache results. Returns list of {title, url, snippet}."""
        # Check cache first
        cached = self._db.get_enrichment_cache(lead_id)
        for c in cached:
            if c.query == query:
                try:
                    return json.loads(c.result_json)
                except json.JSONDecodeError:
                    pass

        results = self._duckduckgo_search(query, max_results)

        # Cache results
        if lead_id and results:
            self._db.add_enrichment_cache(
                lead_id=lead_id,
                query=query,
                result_json=json.dumps(results),
                source_url=f"duckduckgo:{query}",
            )

        return results

    def _duckduckgo_search(self, query: str, max_results: int) -> list[dict]:
        """Search DuckDuckGo HTML and extract results."""
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadsScraper/2.0",
                })
                resp.raise_for_status()
                html = resp.text

            results = []
            # Extract result blocks using regex (lightweight, no BS4 dependency)
            blocks = re.findall(
                r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                html, re.DOTALL,
            )
            for href, title, snippet in blocks[:max_results]:
                title_clean = re.sub(r'<[^>]+>', '', title).strip()
                snippet_clean = re.sub(r'<[^>]+>', '', snippet).strip()
                results.append({
                    "title": title_clean,
                    "url": href,
                    "snippet": snippet_clean,
                })

            return results

        except Exception as e:
            log.error("DuckDuckGo search failed for '%s': %s", query, e)
            return []

    def fetch_page_text(self, url: str, max_chars: int = 5000) -> str:
        """Fetch a page and extract text content."""
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadsScraper/2.0",
                })
                resp.raise_for_status()
                html = resp.text

            # Strip HTML tags for plain text
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]

        except Exception as e:
            log.error("Failed to fetch %s: %s", url, e)
            return ""
