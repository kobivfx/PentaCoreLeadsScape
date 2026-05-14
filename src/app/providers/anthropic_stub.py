"""Anthropic Claude scoring provider stub."""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..core.models import AgentResult, LeadCandidate
from .base import BaseProvider

log = logging.getLogger(__name__)


class AnthropicProvider(BaseProvider):
    """Score leads using Anthropic Claude API. Functional stub."""

    def score_candidate(self, candidate: LeadCandidate, context: dict) -> AgentResult:
        if self.mock:
            return self._mock_score(candidate)

        model = self.config.get("model", "claude-sonnet-4-20250514")
        temperature = self.config.get("temperature", 0.2)
        max_tokens = self.config.get("max_tokens", 2048)
        rate_limit = self.config.get("rate_limit_rpm", 20)

        prompt = self.build_prompt(candidate, context)

        if rate_limit > 0:
            time.sleep(60.0 / rate_limit)

        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            text = data["content"][0]["text"]
            return self.parse_response(text)

        except Exception as e:
            log.error("Anthropic scoring failed: %s", e)
            raise
