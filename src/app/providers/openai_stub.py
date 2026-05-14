"""OpenAI scoring provider stub."""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..core.models import AgentResult, LeadCandidate
from .base import BaseProvider

log = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):
    """Score leads using OpenAI API. Functional stub – ready when API key is provided."""

    def score_candidate(self, candidate: LeadCandidate, context: dict) -> AgentResult:
        if self.mock:
            return self._mock_score(candidate)

        model = self.config.get("model", "gpt-4o-mini")
        temperature = self.config.get("temperature", 0.2)
        max_tokens = self.config.get("max_tokens", 2048)
        rate_limit = self.config.get("rate_limit_rpm", 20)

        prompt = self.build_prompt(candidate, context)

        if rate_limit > 0:
            time.sleep(60.0 / rate_limit)

        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a lead qualification agent. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            text = data["choices"][0]["message"]["content"]
            return self.parse_response(text)

        except Exception as e:
            log.error("OpenAI scoring failed: %s", e)
            raise
