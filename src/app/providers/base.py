"""Base interface for scoring providers."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict

from ..core.models import AgentResult, LeadCandidate

log = logging.getLogger(__name__)

SCORING_PROMPT_TEMPLATE = """You are an expert lead-qualification agent for a 3D animation outsourcing studio.
Your studio provides: game cinematics, cutscenes, character animation, rigging, mocap cleanup, facial animation, 
brand mascot animation, animated commercials, product animation, and CGI content.

Analyze the following lead and return a JSON object ONLY (no other text, no markdown, no explanation outside JSON).

Lead:
- URL: {url}
- Title: {title}
- Text: {text}
- Source: {source}
- Domain: {domain}

Context keywords: {keywords}
Purpose: {purpose}

Return EXACTLY this JSON schema:
{{
  "lead_type": "vendor_search | outsourcing | announcement | brand_campaign | irrelevant",
  "score": <integer 0-10>,
  "score_reason": "<one-sentence explanation>",
  "buyer_signals": ["<signal1>", "<signal2>"],
  "client_name": "<company name or empty string>",
  "project_type_guess": ["<from: game cinematics, marketing, in-game, character animation, rigging, mocap cleanup, facial, brand mascot, animated commercial, product animation, unknown>"],
  "recommended_action": "save | contact | ignore",
  "keyword_suggestions": ["<new keywords to track>"],
  "negative_keywords": ["<phrases to filter out>"]
}}

IMPORTANT: Return ONLY valid JSON. No markdown code blocks. No additional text."""


class BaseProvider(ABC):
    """Abstract scoring provider."""

    def __init__(self, api_key: str, config: dict, mock: bool = False):
        self.api_key = api_key
        self.config = config
        self.mock = mock

    @abstractmethod
    def score_candidate(self, candidate: LeadCandidate, context: dict) -> AgentResult:
        """Score a lead candidate and return structured result."""
        ...

    def build_prompt(self, candidate: LeadCandidate, context: dict) -> str:
        return SCORING_PROMPT_TEMPLATE.format(
            url=candidate.url,
            title=candidate.title,
            text=candidate.text[:3000],
            source=candidate.source,
            domain=candidate.domain,
            keywords=", ".join(context.get("keywords", [])),
            purpose=context.get("purpose", ""),
        )

    def parse_response(self, text: str) -> AgentResult:
        """Parse LLM response text into AgentResult."""
        # Strip markdown code block if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            data = json.loads(cleaned)
            return AgentResult.from_dict(data)
        except json.JSONDecodeError as e:
            log.error("Failed to parse agent response: %s\nText: %s", e, text[:500])
            return AgentResult(score_reason=f"Parse error: {e}")

    def _mock_score(self, candidate: LeadCandidate) -> AgentResult:
        """Return a mock score for testing."""
        import random
        score = random.randint(1, 10)
        return AgentResult(
            lead_type="announcement" if score > 5 else "irrelevant",
            score=score,
            score_reason=f"[MOCK] Random score for testing: {candidate.title[:50]}",
            buyer_signals=["mock signal"],
            client_name="Mock Studio Inc.",
            project_type_guess=["game cinematics"],
            recommended_action="save" if score > 6 else "ignore",
            keyword_suggestions=[],
            negative_keywords=[],
        )
