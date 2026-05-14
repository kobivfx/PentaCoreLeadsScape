"""Mapping: raw Apify items → canonical LeadCandidate, URL handling, dedup."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from ..core.models import LeadCandidate

log = logging.getLogger(__name__)


def canonicalize_url(raw_url: str) -> str:
    """Normalize a URL for deduplication."""
    if not raw_url:
        return ""
    try:
        p = urlparse(raw_url.strip())
        # Lowercase scheme and host
        scheme = p.scheme.lower() or "https"
        host = p.netloc.lower()
        path = p.path.rstrip("/") or "/"
        # Remove tracking params
        remove_params = {"utm_source", "utm_medium", "utm_campaign", "utm_content",
                         "utm_term", "fbclid", "gclid", "ref", "source"}
        qs = parse_qs(p.query, keep_blank_values=False)
        filtered = {k: v for k, v in qs.items() if k.lower() not in remove_params}
        query = urlencode(filtered, doseq=True) if filtered else ""
        return urlunparse((scheme, host, path, "", query, ""))
    except Exception:
        return raw_url.strip()


def compute_lead_id(url: str) -> str:
    """Deterministic ID from canonical URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def extract_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        # Remove www.
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def map_raw_item(raw: dict, mapping: dict, actor_name: str, source: str,
                 query_used: str) -> LeadCandidate | None:
    """Apply output_mapping_json to extract canonical fields from a raw item."""
    try:
        url_raw = _extract_field(raw, mapping.get("url", "url"))
        if not url_raw:
            return None

        url = canonicalize_url(url_raw)
        title = _extract_field(raw, mapping.get("title", "title")) or ""
        text = _extract_field(raw, mapping.get("text", "description")) or ""
        author = _extract_field(raw, mapping.get("author", "author_name")) or ""

        return LeadCandidate(
            url=url,
            title=title[:500],
            text=text[:5000],
            author=author[:200],
            source=source,
            actor_name=actor_name,
            query_used=query_used,
            domain=extract_domain(url),
            extra={k: v for k, v in raw.items()
                   if k not in ("url", "title", "description", "text") and isinstance(v, (str, int, float, bool))},
        )
    except Exception as e:
        log.debug("map_raw_item error: %s", e)
        return None


def _extract_field(raw: dict, expr: str) -> str | None:
    """Extract a field from raw dict using a mapping expression.

    Supports:
      - Simple key: "url"
      - Nested: "data.url"
      - Slice: "full_text[:120]"
    """
    if not expr:
        return None

    # Handle slice notation e.g. full_text[:120]
    slice_match = re.match(r"^(\w[\w.]*)(\[.*\])$", expr)
    if slice_match:
        key_part = slice_match.group(1)
        slice_part = slice_match.group(2)
        val = _resolve_key(raw, key_part)
        if val is None:
            return None
        val = str(val)
        try:
            # Parse slice safely
            m = re.match(r"\[(\d*):(\d*)\]", slice_part)
            if m:
                start = int(m.group(1)) if m.group(1) else None
                end = int(m.group(2)) if m.group(2) else None
                return val[start:end]
        except Exception:
            pass
        return val

    return _resolve_key(raw, expr)


def _resolve_key(raw: dict, key: str):
    """Resolve a possibly nested key like 'data.url'."""
    parts = key.split(".")
    obj = raw
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None
    return str(obj) if obj is not None else None
