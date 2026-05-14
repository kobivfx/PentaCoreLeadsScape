"""DeepSeek API provider – uses OpenAI-compatible chat completions endpoint.

Supports tool calling so the model can fetch URL content during analysis.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from ..core.models import AgentResult, LeadCandidate
from .base import BaseProvider

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_MAX_TOOL_ROUNDS = 5  # safety limit for tool-call loops
_FETCH_MAX_CHARS = 12_000  # max chars returned from a web fetch

# ── Tool definitions sent to DeepSeek ─────────────────────────
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch the text content of a web page given its URL. "
                "Use this when you need to read and analyze a web page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to fetch, e.g. https://example.com/page",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


class DeepSeekProvider(BaseProvider):
    """DeepSeek API provider via OpenAI-compatible endpoint at api.deepseek.com."""

    def __init__(self, api_key: str, config: dict, mock: bool = False):
        super().__init__(api_key, config, mock)
        self._consecutive_failures = 0

    # -- scoring (legacy interface) ----------------------------------------

    def score_candidate(self, candidate: LeadCandidate, context: dict) -> AgentResult:
        if self.mock:
            return self._mock_score(candidate)
        prompt = self.build_prompt(candidate, context)
        text = self.generate(prompt)
        return self.parse_response(text)

    # -- analysis (new merged interface) -----------------------------------

    def analyze(self, prompt: str) -> str:
        """Run an analysis prompt with tool calling enabled.

        The model can call ``web_fetch`` to read the URL content before
        returning its JSON analysis.  If the model doesn't invoke tools it
        behaves identically to ``generate()``.
        """
        if self.mock:
            return json.dumps({
                "score": 7,
                "reason": "Mock analysis – looks like a potential client",
                "brand": "Mock Studio",
                "contact": "mock@example.com",
                "domain": "example.com",
            })

        temperature = self.config.get("temperature", 0.2)
        max_tokens = self.config.get(
            "max_output_tokens", self.config.get("max_tokens", 2048)
        )
        return self._call_api_with_tools(
            prompt, max_tokens=max_tokens, temperature=temperature,
        )

    # -- prefilter ---------------------------------------------------------

    def prefilter(self, text_content: str, prefilter_prompt: str) -> tuple[str, str]:
        """Run a Yes/No prefilter. Returns (result, raw_output)."""
        if self.mock:
            import random
            answer = random.choice(["Yes", "No"])
            return answer, f"mock: {answer}"

        prompt = f"{prefilter_prompt}\n\nContent:\n{text_content[:4000]}\n\nAnswer (Yes or No):"
        temp = self.config.get("temperature", 0.1)
        try:
            raw = self._call_api(prompt, max_tokens=32, temperature=temp)
            self._consecutive_failures = 0
            return self._parse_yes_no(raw), raw
        except Exception as e:
            self._consecutive_failures += 1
            log.error("DeepSeek prefilter failed (attempt %d): %s",
                      self._consecutive_failures, e)
            if self._consecutive_failures >= _MAX_RETRIES:
                raise RuntimeError(
                    f"DeepSeek prefilter giving up after {_MAX_RETRIES} failures: {e}"
                )
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
        log.warning("DeepSeek prefilter ambiguous (treating as No): %s", raw[:200])
        return "No"

    # -- generation --------------------------------------------------------

    def generate(self, prompt: str, max_tokens: int = 2048,
                 temperature: float | None = None) -> str:
        """Generate text using DeepSeek API."""
        if self.mock:
            return json.dumps({"text": "mock response", "status": "ok"})
        if temperature is None:
            temperature = self.config.get("temperature", 0.2)
        max_tokens = self.config.get("max_output_tokens",
                                     self.config.get("max_tokens", max_tokens))
        return self._call_api(prompt, max_tokens=max_tokens, temperature=temperature)

    def _call_api_with_tools(self, prompt: str, max_tokens: int = 2048,
                             temperature: float = 0.2) -> str:
        """Call DeepSeek with tool definitions and handle the tool-call loop.

        Flow:
         1. Send prompt + tool definitions.
         2. If the model responds with tool_calls → execute them locally,
            append results, re-send.
         3. Repeat until the model returns a final text response
            (or we hit _MAX_TOOL_ROUNDS).
        """
        base_url = self.config.get(
            "base_url", "https://api.deepseek.com"
        ).rstrip("/")
        model = self.config.get("model", "deepseek-chat")
        url = f"{base_url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages: list[dict] = [{"role": "user", "content": prompt}]

        with httpx.Client(timeout=120) as client:
            for round_idx in range(_MAX_TOOL_ROUNDS):
                body: dict = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": 0.95,
                    "tools": _TOOLS,
                }

                try:
                    resp = client.post(url, json=body, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as e:
                    raise RuntimeError(
                        f"DeepSeek API error {e.response.status_code}: "
                        f"{e.response.text[:300]}"
                    )
                except Exception as e:
                    raise RuntimeError(f"DeepSeek API request failed: {e}")

                choice = data["choices"][0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason", "")

                # ── If the model wants to call tools ──────────────
                tool_calls = message.get("tool_calls")
                if tool_calls:
                    # Append the assistant message (with tool_calls) to history
                    messages.append(message)

                    for tc in tool_calls:
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            fn_args = {}

                        log.info("DeepSeek tool call [%s]: %s(%s)",
                                 round_idx, fn_name, fn_args)

                        # Execute the tool
                        result_text = self._dispatch_tool(fn_name, fn_args)

                        # Append tool result
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_text,
                        })
                    continue  # next round with tool results

                # ── Normal text response ──────────────────────────
                content = (message.get("content") or "").strip()
                if content:
                    return content

                # Edge case: empty content with stop finish_reason
                log.warning("DeepSeek returned empty content (finish=%s)", finish_reason)
                return ""

        # Exhausted rounds – return whatever we have
        log.warning("DeepSeek tool-call loop hit %d rounds, returning last content",
                     _MAX_TOOL_ROUNDS)
        return (messages[-1].get("content") or "") if messages else ""

    # -- tool dispatch -----------------------------------------------------

    def _dispatch_tool(self, name: str, args: dict) -> str:
        """Execute a tool by name and return the result string."""
        if name == "web_fetch":
            url = args.get("url", "")
            return self._execute_web_fetch(url)
        return json.dumps({"error": f"Unknown tool: {name}"})

    @staticmethod
    def _execute_web_fetch(url: str) -> str:
        """Fetch a web page and return its text content (best-effort)."""
        if not url:
            return "Error: No URL provided."

        # Basic URL validation
        if not re.match(r'^https?://', url, re.IGNORECASE):
            return f"Error: Invalid URL scheme – only http/https allowed: {url}"

        log.info("web_fetch: fetching %s", url)
        try:
            with httpx.Client(
                timeout=30,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "text/html" in content_type or "application/xhtml" in content_type:
                    text = _extract_text_from_html(resp.text)
                elif "application/json" in content_type:
                    text = resp.text
                else:
                    # Plain text or other text types
                    text = resp.text

                if len(text) > _FETCH_MAX_CHARS:
                    text = text[:_FETCH_MAX_CHARS] + "\n\n[… content truncated …]"
                return text

        except httpx.HTTPStatusError as e:
            return f"Error fetching URL (HTTP {e.response.status_code}): {url}"
        except httpx.TimeoutException:
            return f"Error: Request timed out fetching {url}"
        except Exception as e:
            return f"Error fetching URL: {e}"

    # -- plain API call (no tools) -----------------------------------------

    def _call_api(self, prompt: str, max_tokens: int = 2048,
                  temperature: float = 0.2) -> str:
        """Call DeepSeek chat completions API."""
        base_url = self.config.get(
            "base_url", "https://api.deepseek.com"
        ).rstrip("/")
        model = self.config.get("model", "deepseek-chat")
        url = f"{base_url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
        }

        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"DeepSeek API error {e.response.status_code}: "
                f"{e.response.text[:300]}"
            )
        except Exception as e:
            raise RuntimeError(f"DeepSeek API request failed: {e}")

    # -- validation / health check -----------------------------------------

    def validate_config(self) -> str | None:
        """Return error string if config is invalid, else None."""
        if not self.api_key and not self.mock:
            return "DeepSeek API key is required."
        return None

    def health_check(self) -> dict:
        """Run a quick health check."""
        import time as _time
        result = {"ok": False, "latency_ms": 0, "error": "", "raw": "", "runtime": {}}
        if not self.api_key:
            result["error"] = "No API key configured"
            return result

        t0 = _time.perf_counter()
        try:
            raw = self._call_api("Reply with: OK", max_tokens=8, temperature=0.0)
            latency = round((_time.perf_counter() - t0) * 1000)
            result["ok"] = True
            result["latency_ms"] = latency
            result["raw"] = raw
            result["runtime"] = {
                "model": self.config.get("model", "deepseek-chat"),
                "base_url": self.config.get("base_url", "https://api.deepseek.com"),
            }
        except Exception as e:
            latency = round((_time.perf_counter() - t0) * 1000)
            result["latency_ms"] = latency
            result["error"] = str(e)
        return result

    def get_runtime_info(self) -> dict:
        return {
            "mode": "api",
            "model": self.config.get("model", "deepseek-chat"),
            "base_url": self.config.get("base_url", "https://api.deepseek.com"),
            "tool_calling": True,
        }


# ── Module-level helpers ──────────────────────────────────────

def _extract_text_from_html(html: str) -> str:
    """Best-effort HTML → plain text conversion without heavy dependencies."""
    # Remove script / style blocks
    text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html,
                  flags=re.DOTALL | re.IGNORECASE)
    # Convert common block tags to newlines
    text = re.sub(r'<(br|hr|/p|/div|/li|/tr|/h[1-6])[^>]*>', '\n', text,
                  flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode basic HTML entities
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(entity, char)
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
