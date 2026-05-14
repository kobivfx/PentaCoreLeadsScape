"""Qwen local LLM provider – optimized for Qwen models via llama-cpp-python."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

from ..core.models import AgentResult, LeadCandidate
from .base import BaseProvider

log = logging.getLogger(__name__)

_MAX_RETRIES = 3


@dataclass
class _QwenModelInfo:
    """Metadata about the currently loaded Qwen model."""
    llm: object = None
    model_path: str = ""
    n_gpu_layers: int = -1
    context_size: int = 8192
    gpu_offload_active: bool = False
    actual_gpu_layers: int = 0
    backend: str = "unknown"
    load_time_ms: int = 0


class _QwenModelCache:
    """Thread-safe singleton cache for Qwen llama-cpp-python model instances."""

    def __init__(self):
        self._lock = threading.Lock()
        self._info: _QwenModelInfo | None = None

    def _config_key(self, config: dict) -> tuple:
        return (
            config.get("model_path", ""),
            config.get("n_gpu_layers", -1),
            config.get("context_size", 8192),
        )

    def get_or_load(self, config: dict) -> _QwenModelInfo:
        """Return cached model if settings match, otherwise load a new one."""
        with self._lock:
            key = self._config_key(config)
            if self._info and (
                self._info.model_path == key[0]
                and self._info.n_gpu_layers == key[1]
                and self._info.context_size == key[2]
                and self._info.llm is not None
            ):
                return self._info

            # Need to (re-)load
            log.info("Loading Qwen model (cache miss or settings changed)…")
            return self._load(config)

    def _load(self, config: dict) -> _QwenModelInfo:
        """Load model – caller must hold self._lock."""
        from llama_cpp import Llama

        model_path = config.get("model_path", "")
        n_gpu_layers = config.get("n_gpu_layers", -1)
        n_ctx = config.get("context_size", 8192)

        t0 = time.perf_counter()
        llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        load_ms = round((time.perf_counter() - t0) * 1000)

        # Detect GPU info from the model metadata
        gpu_active = False
        actual_layers = 0
        backend = "cpu"
        try:
            md = llm.metadata or {}
            actual_layers = int(md.get("general.gpu_layers", n_gpu_layers))
            if actual_layers != 0:
                gpu_active = True
                for tag in ("cuda", "vulkan", "metal", "opencl", "sycl"):
                    desc = str(md.get("general.description", "")).lower()
                    if tag in desc:
                        backend = tag
                        break
                else:
                    backend = "gpu"
        except Exception:
            if n_gpu_layers != 0:
                gpu_active = True
                actual_layers = n_gpu_layers
                backend = "gpu (unconfirmed)"

        info = _QwenModelInfo(
            llm=llm,
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            context_size=n_ctx,
            gpu_offload_active=gpu_active,
            actual_gpu_layers=actual_layers,
            backend=backend,
            load_time_ms=load_ms,
        )
        self._info = info
        log.info(
            "Qwen model loaded in %d ms  |  backend=%s  gpu_offload=%s  gpu_layers=%s",
            load_ms, backend, gpu_active, actual_layers,
        )
        return info

    def invalidate(self):
        """Force next call to reload."""
        with self._lock:
            if self._info and self._info.llm is not None:
                try:
                    del self._info.llm
                except Exception:
                    pass
            self._info = None

    @property
    def current_info(self) -> _QwenModelInfo | None:
        return self._info


# Single global instance for Qwen
_qwen_model_cache = _QwenModelCache()


class QwenProvider(BaseProvider):
    """Qwen local LLM provider via llama-cpp-python or OpenAI-compatible HTTP endpoint."""

    def __init__(self, api_key: str, config: dict, mock: bool = False):
        super().__init__(api_key, config, mock)
        self._mode = config.get("mode", "http")  # "http" or "direct"
        self._consecutive_failures = 0
        self._model_info: _QwenModelInfo | None = None

        if self._mode == "direct" and not mock:
            self._ensure_model()

    # -- model lifecycle ---------------------------------------------------

    def _ensure_model(self):
        """Load (or reuse cached) Qwen model for direct mode."""
        model_path = self.config.get("model_path", "")
        if not model_path:
            raise RuntimeError(
                "No model_path configured for Qwen direct mode. "
                "Set the .gguf model path in Providers → Qwen Settings."
            )
        if not os.path.isfile(model_path):
            raise RuntimeError(
                f"Qwen model file not found: {model_path}. "
                "Verify the path in Providers → Qwen Settings."
            )
        try:
            self._model_info = _qwen_model_cache.get_or_load(self.config)
        except ImportError:
            raise RuntimeError(
                "llama-cpp-python not installed. Install with: pip install llama-cpp-python"
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to load Qwen model: {e}")

    @staticmethod
    def invalidate_cache():
        """Invalidate the cached Qwen model (call when settings change)."""
        _qwen_model_cache.invalidate()

    def get_runtime_info(self) -> dict:
        """Return runtime info about the loaded Qwen model for display in the UI."""
        if self._mode != "direct":
            return {
                "mode": "http",
                "backend": "http server",
                "gpu_offload": "n/a (server-managed)",
                "gpu_layers": "n/a",
                "model_load_ms": 0,
                "cached": False,
            }
        info = self._model_info or _qwen_model_cache.current_info
        if not info:
            return {
                "mode": "direct",
                "backend": "not loaded",
                "gpu_offload": False,
                "gpu_layers": 0,
                "model_load_ms": 0,
                "cached": False,
            }
        return {
            "mode": "direct",
            "backend": info.backend,
            "gpu_offload": info.gpu_offload_active,
            "gpu_layers": info.actual_gpu_layers,
            "model_load_ms": info.load_time_ms,
            "cached": True,
        }

    # -- generation --------------------------------------------------------

    def _generate_direct(self, prompt: str, max_tokens: int, temperature: float,
                         stop: list[str] | None = None) -> str:
        """Generate using direct llama-cpp-python with chat completion API.
        
        Qwen models are instruction-tuned, so we use chat completion for proper
        template handling.
        """
        if not self._model_info or not self._model_info.llm:
            self._ensure_model()
        if stop is None:
            stop = ["```", "\n\n\n"]

        try:
            response = self._model_info.llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
            )
            text = response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.warning("Qwen chat completion failed, trying raw completion: %s", e)
            response = self._model_info.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
            )
            text = response["text"].strip()

        return text

    def _generate_http(self, prompt: str, max_tokens: int, temperature: float,
                       stop: list[str] | None = None) -> str:
        """Generate via OpenAI-compatible HTTP endpoint (e.g., ollama)."""
        import httpx

        if stop is None:
            stop = ["```", "\n\n\n"]

        url = self.config.get("http_base_url", "").strip()
        if not url:
            raise RuntimeError("HTTP Base URL not configured for Qwen provider")

        if not url.endswith("/"):
            url += "/"
        url += "v1/chat/completions"

        model_name = self.config.get("http_model", "qwen")

        try:
            with httpx.Client(timeout=300) as client:
                response = client.post(
                    url,
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "top_p": 0.95,
                        "stop": stop,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"HTTP request to Qwen failed: {e}")

    def generate(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        """Generate text using Qwen."""
        if self.mock:
            return json.dumps({"text": "mock response", "status": "ok"})

        try:
            if self._mode == "direct":
                return self._generate_direct(prompt, max_tokens, temperature)
            else:
                return self._generate_http(prompt, max_tokens, temperature)
        except Exception as e:
            self._consecutive_failures += 1
            log.error("Qwen generation failed (attempt %d): %s", self._consecutive_failures, e)
            if self._consecutive_failures >= _MAX_RETRIES:
                raise RuntimeError(f"Qwen generation giving up after {_MAX_RETRIES} failures: {e}")
            raise

    # -- health check / validation -----------------------------------------

    def health_check(self) -> dict:
        """Run a lightweight health check. Returns {ok, latency_ms, error, raw, runtime}."""
        t0 = time.perf_counter()
        try:
            if self._mode == "direct":
                self._ensure_model()
                raw = self._generate_direct(
                    "Reply with OK only.", max_tokens=8, temperature=0, stop=["\n"],
                )
            else:
                import httpx
                base_url = self.config.get("http_base_url", "http://localhost:8080")
                try:
                    with httpx.Client(timeout=10) as client:
                        r = client.get(f"{base_url.rstrip('/')}/health")
                        if r.status_code == 200:
                            latency = round((time.perf_counter() - t0) * 1000)
                            return {"ok": True, "latency_ms": latency,
                                    "error": "", "raw": r.text[:200],
                                    "runtime": self.get_runtime_info()}
                except Exception:
                    pass
                raw = self._generate_http(
                    "Reply with OK only.", max_tokens=8, temperature=0, stop=["\n"],
                )
            latency = round((time.perf_counter() - t0) * 1000)
            return {"ok": True, "latency_ms": latency, "error": "", "raw": raw,
                    "runtime": self.get_runtime_info()}
        except Exception as e:
            latency = round((time.perf_counter() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "error": str(e), "raw": "",
                    "runtime": self.get_runtime_info()}

    # -- scoring -----------------------------------------------------------

    def score_candidate(self, candidate: LeadCandidate, context: dict) -> AgentResult:
        if self.mock:
            return self._mock_score(candidate)
        prompt = self.build_prompt(candidate, context)
        text = self.generate(prompt)
        return self.parse_response(text)

    # -- prefilter ---------------------------------------------------------

    def prefilter(self, text_content: str, prefilter_prompt: str) -> tuple[str, str]:
        """Run a Yes/No prefilter. Returns (result, raw_output).
        
        Uses low temperature for more deterministic Yes/No responses.
        """
        if self.mock:
            import random
            answer = random.choice(["Yes", "No"])
            return answer, f"mock: {answer}"

        prompt = f"{prefilter_prompt}.\n\nContent:\n{text_content[:4000]}\n\nAnswer (Yes or No):"
        temp = self.config.get("temperature", 0.1)
        try:
            if self._mode == "direct":
                raw = self._generate_direct(
                    prompt, max_tokens=32, temperature=temp, stop=["\n", "."],
                )
            else:
                raw = self._generate_http(
                    prompt, max_tokens=32, temperature=temp, stop=["\n", "."],
                )
            self._consecutive_failures = 0
            return self._parse_yes_no(raw), raw
        except Exception as e:
            self._consecutive_failures += 1
            log.error("Qwen prefilter failed (attempt %d): %s", self._consecutive_failures, e)
            if self._consecutive_failures >= _MAX_RETRIES:
                raise RuntimeError(
                    f"Qwen prefilter giving up after {_MAX_RETRIES} consecutive failures: {e}"
                )
            return "No", f"error: {e}"

    @staticmethod
    def _parse_yes_no(raw: str) -> str:
        """Robustly parse a Yes/No answer from raw model output."""
        cleaned = raw.strip().lower()
        if not cleaned:
            return "No"
        first_word = cleaned.split()[0].rstrip(".,!?:;")
        if first_word in ("yes", "yep", "yeah", "y", "true"):
            return "Yes"
        if first_word in ("no", "nope", "nah", "n", "false"):
            return "No"
        # Check if yes/no appears anywhere in short output
        if len(cleaned) < 20:
            if "yes" in cleaned:
                return "Yes"
            if "no" in cleaned:
                return "No"
        log.warning("Qwen prefilter ambiguous response (treating as No): %s", raw[:200])
        return "No"

    def build_prefilter_prompt(self, text_content: str, prefilter_prompt: str) -> str:
        """Return the exact prompt that will be sent to the model (for UI debug display)."""
        return f"{prefilter_prompt}\n\nContent:\n{text_content[:4000]}\n\nAnswer (Yes or No):"

    # -- enrichment --------------------------------------------------------

    def enrich(self, prompt: str) -> str:
        """Run an enrichment prompt and return raw response text."""
        if self.mock:
            return json.dumps({
                "company_name": "Mock Studio",
                "contact_email": "mock@example.com",
                "contact_name": "",
                "publisher": "",
                "project_details": "Mock enrichment data",
                "budget_indicator": "",
                "sources": [],
            })
        return self.generate(prompt)

    # -- analysis (merged scoring+enrichment) ------------------------------

    def analyze(self, prompt: str) -> str:
        """Run an analysis prompt and return raw response text."""
        if self.mock:
            return json.dumps({
                "score": 7,
                "reason": "Mock analysis – looks like a potential client",
                "brand": "Mock Studio",
                "contact": "mock@example.com",
                "domain": "example.com",
            })
        return self.generate(prompt)

    # -- validation --------------------------------------------------------

    def validate_config(self) -> str | None:
        """Validate configuration. Returns error message if invalid, None if valid."""
        if self._mode == "direct":
            model_path = self.config.get("model_path", "").strip()
            if not model_path:
                return "model_path is required for Qwen direct mode"
            if not os.path.isfile(model_path):
                return f"Model file not found: {model_path}"
        elif self._mode == "http":
            url = self.config.get("http_base_url", "").strip()
            if not url:
                return "http_base_url is required for Qwen HTTP mode"
            if not url.startswith(("http://", "https://")):
                return f"Invalid HTTP Base URL: {url}"
        return None
