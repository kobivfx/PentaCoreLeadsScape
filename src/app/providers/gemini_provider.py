"""Google Gemini scoring provider.

Supports google_search grounding and url_context tools for the analysis step,
enabling the model to read URLs and search the web autonomously.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..core.models import AgentResult, LeadCandidate
from .base import BaseProvider

log = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Built-in Gemini tools – attached automatically during analysis
# Note: Tool names must be camelCase per the Gemini API schema
_ANALYSIS_TOOLS = [
    {"urlContext": {}},
    {"googleSearch": {}},
]

# System instruction that guides the model to use Google Search as fallback
# when urlContext cannot fetch a URL (e.g. social media platforms that block scraping)
_ANALYSIS_SYSTEM_INSTRUCTION = (
    "You have two tools: urlContext (reads web pages) and googleSearch.\n"
    "IMPORTANT: Many URLs from social media platforms (Twitter/X, Facebook, "
    "Instagram, LinkedIn, TikTok, etc.) CANNOT be fetched by urlContext because "
    "these platforms block external access.\n"
    "When you cannot read a URL directly:\n"
    "1. Use Google Search to find information about that URL, the brand, "
    "or the company mentioned in it.\n"
    "2. Search for the company name, domain, or any identifiable info from the URL.\n"
    "3. Combine all findings to produce your analysis.\n"
    "NEVER say you cannot access the URL — always use Google Search as fallback "
    "and provide your best analysis based on available information."
)


class GeminiProvider(BaseProvider):
    """Score leads using Google Gemini API with optional Google Search + URL context."""

    # -- legacy scoring interface ------------------------------------------

    def score_candidate(self, candidate: LeadCandidate, context: dict) -> AgentResult:
        if self.mock:
            return self._mock_score(candidate)

        prompt = self.build_prompt(candidate, context)
        text = self._call_api(prompt, response_mime="application/json")
        return self.parse_response(text)

    # -- analysis (merged scoring + enrichment) ----------------------------

    def analyze(self, prompt: str) -> str:
        """Run analysis with google_search + url_context tools enabled.

        The Gemini API handles these tools server-side: the model can
        autonomously browse URLs and search Google, then returns a final
        response in a single API round-trip (no tool-call loop needed).
        """
        if self.mock:
            return json.dumps({
                "score": 7,
                "reason": "Mock analysis – looks like a potential client",
                "brand": "Mock Studio",
                "contact": "mock@example.com",
                "domain": "example.com",
            })

        return self._call_api(
            prompt,
            tools=_ANALYSIS_TOOLS,
            system_instruction="",
        )

    # -- prefilter ---------------------------------------------------------

    def prefilter(self, text_content: str, prefilter_prompt: str) -> tuple[str, str]:
        """Run a Yes/No prefilter. Returns (result, raw_output)."""
        if self.mock:
            import random
            answer = random.choice(["Yes", "No"])
            return answer, f"mock: {answer}"

        prompt = f"{prefilter_prompt}\n\nContent:\n{text_content[:4000]}\n\nAnswer (Yes or No):"
        try:
            raw = self._call_api(prompt, max_tokens=32, temperature=0.1)
            return self._parse_yes_no(raw), raw
        except Exception as e:
            log.error("Gemini prefilter failed: %s", e)
            return "No", f"error: {e}"

    @staticmethod
    def _parse_yes_no(raw: str) -> str:
        cleaned = raw.strip().lower()
        if not cleaned:
            return "No"
        first_word = cleaned.split()[0].rstrip(".,!?:;")
        if first_word in ("yes", "yep", "yeah", "y", "true"):
            return "Yes"
        if first_word in ("no", "nope", "nah", "n", "false"):
            return "No"
        if len(cleaned) < 20:
            if "yes" in cleaned:
                return "Yes"
            if "no" in cleaned:
                return "No"
        log.warning("Gemini prefilter ambiguous (treating as No): %s", raw[:200])
        return "No"

    # -- generation --------------------------------------------------------

    def generate(self, prompt: str, max_tokens: int = 2048,
                 temperature: float | None = None) -> str:
        """Generate text without tools."""
        if self.mock:
            return json.dumps({"text": "mock response", "status": "ok"})
        return self._call_api(prompt, max_tokens=max_tokens, temperature=temperature)

    # -- core API call -----------------------------------------------------

    def _call_api(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_mime: str | None = None,
        tools: list[dict] | None = None,
        system_instruction: str | None = None,
    ) -> str:
        """Call Gemini generateContent REST API with retry on rate limits."""
        model = self.config.get("model", "gemini-2.0-flash")
        if temperature is None:
            temperature = self.config.get("temperature", 0.2)
        if max_tokens is None:
            max_tokens = self.config.get(
                "max_output_tokens", self.config.get("max_tokens", 2048)
            )
        rate_limit = self.config.get("rate_limit_rpm", 15)

        # Rate limiting
        if rate_limit > 0:
            delay = 60.0 / rate_limit
            time.sleep(delay)

        url = f"{_API_BASE}/models/{model}:generateContent"

        gen_config: dict = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if response_mime:
            gen_config["responseMimeType"] = response_mime

        payload: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }

        if tools:
            payload["tools"] = tools
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        log.info("Gemini request: model=%s, tools=%s, prompt_len=%d",
                 model, [list(t.keys()) for t in tools] if tools else None, len(prompt))
        log.debug("Gemini payload: %s", json.dumps(payload, ensure_ascii=False)[:2000])

        # Retry loop for rate-limit (429) and server (503) errors
        max_retries = 5
        retryable_codes = {429, 503, 500, 502}
        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=120) as client:
                    resp = client.post(
                        url,
                        params={"key": self.api_key},
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    if resp.status_code in retryable_codes and attempt < max_retries - 1:
                        wait = min(2 ** (attempt + 1), 30)  # 2s, 4s, 8s, 16s
                        log.warning("Gemini %d error, retrying in %ds (attempt %d/%d)",
                                    resp.status_code, wait, attempt + 1, max_retries)
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = resp.json()

                # Store raw response for diagnostics (used by test UI)
                self._last_response = data
                log.debug("Gemini raw response keys: %s", list(data.keys()))
                if data.get("candidates"):
                    cand = data["candidates"][0]
                    log.debug("Gemini candidate keys: %s", list(cand.keys()))

                return self._extract_text(data)

            except httpx.HTTPStatusError as e:
                if e.response.status_code in retryable_codes and attempt < max_retries - 1:
                    wait = min(2 ** (attempt + 1), 30)
                    log.warning("Gemini %d error (exception), retrying in %ds (attempt %d/%d)",
                                e.response.status_code, wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    continue
                log.error("Gemini API error %s: %s", e.response.status_code, e.response.text[:500])
                raise RuntimeError(
                    f"Gemini API error {e.response.status_code}: {e.response.text[:300]}"
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                if attempt < max_retries - 1:
                    wait = min(2 ** (attempt + 1), 30)
                    log.warning("Gemini connection error, retrying in %ds (attempt %d/%d): %s",
                                wait, attempt + 1, max_retries, e)
                    time.sleep(wait)
                    continue
                log.error("Gemini API request failed: %s", e)
                raise RuntimeError(f"Gemini API request failed: {e}")
            except Exception as e:
                log.error("Gemini API request failed: %s", e)
                raise RuntimeError(f"Gemini API request failed: {e}")

        raise RuntimeError("Gemini API: max retries exceeded")

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Extract text from Gemini response, concatenating all text parts."""
        candidates = data.get("candidates", [])
        if not candidates:
            log.error("Gemini returned no candidates")
            return ""

        cand = candidates[0]
        parts = cand.get("content", {}).get("parts", [])
        texts = [p.get("text", "") for p in parts if "text" in p]
        text = "\n".join(texts).strip()

        # Log grounding metadata (handle both camelCase and snake_case)
        grounding = cand.get("groundingMetadata") or cand.get("grounding_metadata")
        if grounding:
            queries = grounding.get("webSearchQueries") or grounding.get("web_search_queries", [])
            chunks = grounding.get("groundingChunks") or grounding.get("grounding_chunks", [])
            log.info("Gemini grounding: %d search queries, %d chunks",
                     len(queries), len(chunks))
        else:
            log.info("Gemini response: no grounding metadata present")

        # Log URL context metadata (handle both camelCase and snake_case)
        url_ctx = cand.get("urlContextMetadata") or cand.get("url_context_metadata")
        if url_ctx:
            urls_info = (url_ctx.get("urlMetadata")
                         or url_ctx.get("url_metadata", []))
            for u in urls_info:
                r_url = u.get("retrievedUrl") or u.get("retrieved_url", "?")
                r_status = u.get("urlRetrievalStatus") or u.get("url_retrieval_status", "?")
                log.info("Gemini URL context: %s → %s", r_url, r_status)
        else:
            log.info("Gemini response: no URL context metadata present")

        return text

    # -- validation / health check -----------------------------------------

    def validate_config(self) -> str | None:
        """Return error string if config is invalid, else None."""
        if not self.api_key and not self.mock:
            return "Gemini API key is required."
        return None

    def health_check(self) -> dict:
        """Run a quick health check."""
        result = {"ok": False, "latency_ms": 0, "error": "", "raw": "", "runtime": {}}
        if not self.api_key:
            result["error"] = "No API key configured"
            return result

        t0 = time.perf_counter()
        try:
            raw = self._call_api("Reply with: OK", max_tokens=8, temperature=0.0)
            latency = round((time.perf_counter() - t0) * 1000)
            result["ok"] = True
            result["latency_ms"] = latency
            result["raw"] = raw
            result["runtime"] = {
                "model": self.config.get("model", "gemini-2.0-flash"),
                "backend": "Gemini API",
                "tool_calling": True,
            }
        except Exception as e:
            latency = round((time.perf_counter() - t0) * 1000)
            result["latency_ms"] = latency
            result["error"] = str(e)
        return result

    def get_runtime_info(self) -> dict:
        return {
            "mode": "api",
            "model": self.config.get("model", "gemini-2.0-flash"),
            "backend": "Gemini API",
            "tool_calling": True,
        }
