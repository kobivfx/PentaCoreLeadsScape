"""Apify actor runner – start actors, poll, fetch results."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

APIFY_BASE = "https://api.apify.com/v2"


class ApifyRunner:
    """Run Apify actors and fetch dataset items.
    
    Supports multiple API tokens with automatic rotation and fallback.
    If a request fails, the next token in the list is used.
    """

    def __init__(self, tokens: str | list[str], timeout: int = 300, mock: bool = False):
        """Initialize with single token (str) or list of tokens.
        
        Args:
            tokens: Single API token string or list of tokens
            timeout: Request timeout in seconds
            mock: If True, return mock results
        """
        # Normalize to list
        if isinstance(tokens, str):
            self._tokens = [tokens] if tokens else []
        else:
            self._tokens = list(tokens) if tokens else []
        
        if not self._tokens:
            raise ValueError("At least one Apify token must be provided")
        
        self._current_token_idx = 0
        self._timeout = timeout
        self._mock = mock
        self._client = httpx.Client(timeout=60)
        self._token_failures = {}  # Track failures per token for logging

    @property
    def _current_token(self) -> str:
        """Get current token."""
        return self._tokens[self._current_token_idx]

    def _next_token(self) -> bool:
        """Move to next token. Return True if a next token exists, False if exhausted."""
        if len(self._tokens) <= 1:
            return False
        next_idx = (self._current_token_idx + 1) % len(self._tokens)
        if next_idx == self._current_token_idx:  # Wrapped around
            return False
        self._current_token_idx = next_idx
        return True

    def close(self):
        self._client.close()

    def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with automatic token rotation on failure."""
        last_error = None
        attempts = 0
        
        while attempts < len(self._tokens):
            attempts += 1
            try:
                # Add current token to params
                params = kwargs.get("params", {})
                params["token"] = self._current_token
                kwargs["params"] = params
                
                if method.upper() == "GET":
                    resp = self._client.get(url, **kwargs)
                elif method.upper() == "POST":
                    resp = self._client.post(url, **kwargs)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                resp.raise_for_status()
                
                # Success - log if this is not the first token
                if self._current_token_idx != 0 and last_error:
                    log.info(
                        "Request succeeded after token fallback. "
                        f"Previous error: {last_error}"
                    )
                
                return resp
            
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = str(e)
                token_preview = f"{self._current_token[:10]}...{self._current_token[-4:]}"
                
                # Check if it's a rate limit or auth error (should rotate)
                is_rate_limit = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429
                is_auth_error = isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403)
                
                if is_rate_limit or is_auth_error or attempts < len(self._tokens):
                    if self._next_token():
                        new_token_preview = f"{self._current_token[:10]}...{self._current_token[-4:]}"
                        log.warning(
                            f"Token {token_preview} failed ({type(e).__name__}). "
                            f"Rotating to {new_token_preview}"
                        )
                        continue
                
                # No more tokens to try
                log.error(f"All {len(self._tokens)} tokens exhausted. Last error: {last_error}")
                raise
        
        raise last_error or Exception("Request failed after exhausting all tokens")

    # ------------------------------------------------------------------
    def run_actor(self, actor_id: str, input_data: dict) -> list[dict]:
        if self._mock:
            return self._mock_results(actor_id, input_data)

        log.info("Starting Apify actor %s", actor_id)
        url = f"{APIFY_BASE}/acts/{actor_id}/runs"
        resp = self._make_request(
            "POST",
            url,
            json=input_data,
            headers={"Content-Type": "application/json"},
        )
        run_data = resp.json()["data"]
        run_id = run_data["id"]
        log.info("Actor run started: %s (run %s)", actor_id, run_id)

        # Poll for completion
        status = run_data.get("status", "RUNNING")
        elapsed = 0
        poll_interval = 5
        while status in ("RUNNING", "READY"):
            if elapsed >= self._timeout:
                log.warning("Actor %s timed out after %ds", actor_id, self._timeout)
                self._abort_run(run_id)
                return []
            time.sleep(poll_interval)
            elapsed += poll_interval
            status = self._check_run_status(run_id)

        if status != "SUCCEEDED":
            log.error("Actor %s finished with status: %s", actor_id, status)
            return []

        # Fetch dataset
        dataset_id = run_data.get("defaultDatasetId")
        if not dataset_id:
            dataset_id = self._get_dataset_id(run_id)
        return self._fetch_dataset(dataset_id) if dataset_id else []

    def _check_run_status(self, run_id: str) -> str:
        url = f"{APIFY_BASE}/actor-runs/{run_id}"
        resp = self._make_request("GET", url)
        return resp.json()["data"]["status"]

    def _get_dataset_id(self, run_id: str) -> str | None:
        url = f"{APIFY_BASE}/actor-runs/{run_id}"
        resp = self._make_request("GET", url)
        return resp.json()["data"].get("defaultDatasetId")

    def _fetch_dataset(self, dataset_id: str) -> list[dict]:
        url = f"{APIFY_BASE}/datasets/{dataset_id}/items"
        items = []
        offset = 0
        limit = 100
        while True:
            resp = self._make_request(
                "GET",
                url,
                params={"offset": offset, "limit": limit, "format": "json"},
            )
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        log.info("Fetched %d items from dataset %s", len(items), dataset_id)
        return items

    def _abort_run(self, run_id: str):
        try:
            url = f"{APIFY_BASE}/actor-runs/{run_id}/abort"
            self._make_request("POST", url)
        except Exception as e:
            log.warning("Failed to abort run %s: %s", run_id, e)

    # ------------------------------------------------------------------
    @staticmethod
    def _mock_results(actor_id: str, input_data: dict) -> list[dict]:
        """Return mock results for testing."""
        log.info("MOCK: actor=%s", actor_id)
        return [
            {
                "url": "https://example.com/mock-lead-1",
                "title": "[MOCK] Studio announces 3D cinematic outsourcing partnership",
                "description": "A major game studio is looking for animation vendors for next-gen game cinematics.",
            },
            {
                "url": "https://example.com/mock-lead-2",
                "title": "[MOCK] Brand launches animated commercial campaign",
                "description": "Consumer brand seeks 3D animation studio for mascot-driven ad campaign.",
            },
            {
                "url": "https://example.com/mock-lead-3",
                "title": "[MOCK] Indie developer needs cutscene animation outsourcing",
                "description": "Small indie studio crowdfunding an RPG needs cinematic cutscenes produced externally.",
            },
        ]
