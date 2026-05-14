"""Local LLM provider – supports .gguf via llama-cpp-python or HTTP server."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field

import httpx

from ..core.models import AgentResult, LeadCandidate
from .base import BaseProvider

log = logging.getLogger(__name__)

_MAX_RETRIES = 3

# ---------------------------------------------------------------------------
#  Module-level model cache – loads the .gguf once, reuses across calls.
# ---------------------------------------------------------------------------

@dataclass
class _ModelInfo:
    """Metadata about the currently loaded model."""
    llm: object = None
    model_path: str = ""
    n_gpu_layers: int = -1
    context_size: int = 8192
    gpu_offload_active: bool = False
    actual_gpu_layers: int = 0
    backend: str = "unknown"
    load_time_ms: int = 0


class _ModelCache:
    """Thread-safe singleton cache for llama-cpp-python model instances."""

    def __init__(self):
        self._lock = threading.Lock()
        self._info: _ModelInfo | None = None

    def _config_key(self, config: dict) -> tuple:
        return (
            config.get("model_path", ""),
            config.get("n_gpu_layers", -1),
            config.get("context_size", 8192),
        )

    def get_or_load(self, config: dict) -> _ModelInfo:
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
            log.info("Loading model (cache miss or settings changed)…")
            return self._load(config)

    def _load(self, config: dict) -> _ModelInfo:
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
            # llama-cpp-python exposes n_gpu_layers actually used
            actual_layers = int(md.get("general.gpu_layers", n_gpu_layers))
            if actual_layers != 0:
                gpu_active = True
                # Detect backend via build info
                for tag in ("cuda", "vulkan", "metal", "opencl", "sycl"):
                    desc = str(md.get("general.description", "")).lower()
                    if tag in desc:
                        backend = tag
                        break
                else:
                    backend = "gpu"
        except Exception:
            # Heuristic: if we requested GPU layers, assume it worked
            if n_gpu_layers != 0:
                gpu_active = True
                actual_layers = n_gpu_layers
                backend = "gpu (unconfirmed)"

        info = _ModelInfo(
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
            "Model loaded in %d ms  |  backend=%s  gpu_offload=%s  gpu_layers=%s",
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
    def current_info(self) -> _ModelInfo | None:
        return self._info


# Single global instance
_model_cache = _ModelCache()


class LocalLLMProvider(BaseProvider):
    """Local LLM (Gemma 4 .gguf) via llama-cpp-python or OpenAI-compatible HTTP endpoint."""

    def __init__(self, api_key: str, config: dict, mock: bool = False):
        super().__init__(api_key, config, mock)
        self._mode = config.get("mode", "http")  # "http" or "direct"
        self._consecutive_failures = 0
        self._model_info: _ModelInfo | None = None

        if self._mode == "direct" and not mock:
            self._ensure_model()

    # -- model lifecycle ---------------------------------------------------

    def _ensure_model(self):
        """Load (or reuse cached) model for direct mode."""
        model_path = self.config.get("model_path", "")
        if not model_path:
            raise RuntimeError(
                "No model_path configured for local LLM direct mode. "
                "Set the .gguf model path in Providers → Local LLM Settings."
            )
        if not os.path.isfile(model_path):
            raise RuntimeError(
                f"Model file not found: {model_path}. "
                "Verify the path in Providers → Local LLM Settings."
            )
        try:
            self._model_info = _model_cache.get_or_load(self.config)
        except ImportError:
            raise RuntimeError(
                "llama-cpp-python not installed. Install with: pip install llama-cpp-python"
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to load local LLM: {e}")

    @staticmethod
    def invalidate_cache():
        """Invalidate the cached model (call when settings change)."""
        _model_cache.invalidate()

    def get_runtime_info(self) -> dict:
        """Return runtime info about the loaded model for display in the UI."""
        if self._mode != "direct":
            return {
                "mode": "http",
                "backend": "http server",
                "gpu_offload": "n/a (server-managed)",
                "gpu_layers": "n/a",
                "model_load_ms": 0,
                "cached": False,
            }
        info = self._model_info or _model_cache.current_info
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
        """Generate using direct llama-cpp-python with completion API.

        For instruction-tuned models like Gemma, uses chat function for proper
        template handling. Strips template markers from response.
        """
        if not self._model_info or not self._model_info.llm:
            self._ensure_model()
        if stop is None:
            stop = ["```", "\n\n\n"]

        try:
            # Try chat completion first (proper for instruction-tuned models)
            response = self._model_info.llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                stop=stop,
            )
            text = response["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.warning("Chat completion failed, trying raw completion: %s", e)
            # Fallback to raw completion
            response = self._model_info.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                stop=stop,
            )
            text = response["choices"][0]["text"].strip()

        # Strip template markers that might appear (e.g. [/INST])
        text = text.replace("[/INST]", "").replace("[INST]", "").replace("<|im_end|>", "").strip()
        return text if text else ""

    def _generate_http(self, prompt: str, max_tokens: int, temperature: float,
                       stop: list[str] | None = None) -> str:
        """Generate using an OpenAI-compatible HTTP endpoint."""
        base_url = self.config.get("http_base_url", "http://localhost:8080")
        model = self.config.get("http_model", "gemma-4")

        url = f"{base_url.rstrip('/')}/v1/chat/completions"

        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = stop

        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            self._consecutive_failures = 0
            return data["choices"][0]["message"]["content"].strip()
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to local LLM server at {base_url}. "
                "Start the server or switch to a cloud provider."
            )

    def generate(self, prompt: str) -> str:
        """Generate text from the local LLM, respecting the configured mode."""
        max_tokens = self.config.get("max_tokens", 2048)
        temperature = self.config.get("temperature", 0.1)

        if self._mode == "direct":
            return self._generate_direct(prompt, max_tokens, temperature)
        else:
            return self._generate_http(prompt, max_tokens, temperature)

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

    def validate_config(self) -> str | None:
        """Return an error string if config is invalid, else None."""
        if self._mode == "direct":
            path = self.config.get("model_path", "")
            if not path:
                return "Model path (.gguf) is not set."
            if not os.path.isfile(path):
                return f"Model file not found: {path}"
        else:
            url = self.config.get("http_base_url", "").strip()
            if not url:
                return "HTTP Base URL is not set."
            if not url.startswith(("http://", "https://")):
                return f"Invalid HTTP Base URL: {url}"
        return None

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

        Uses low-temp generation with generous max_tokens to allow model to respond.
        """
        if self.mock:
            import random
            answer = random.choice(["Yes", "No"])
            return answer, f"mock: {answer}"

        prompt = f"{prefilter_prompt}\n\nContent:\n{text_content[:4000]}\n\nAnswer (Yes or No):"
        temp = self.config.get("temperature", 0.1)
        try:
            if self._mode == "direct":
                raw = self._generate_direct(
                    prompt, max_tokens=320000, temperature=temp, stop=["\n", "."],
                )
            else:
                raw = self._generate_http(
                    prompt, max_tokens=320000, temperature=temp, stop=["\n", "."],
                )
            self._consecutive_failures = 0
            return self._parse_yes_no(raw), raw
        except Exception as e:
            self._consecutive_failures += 1
            log.error("Prefilter failed (attempt %d): %s", self._consecutive_failures, e)
            if self._consecutive_failures >= _MAX_RETRIES:
                raise RuntimeError(
                    f"Prefilter giving up after {_MAX_RETRIES} consecutive failures: {e}"
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
        log.warning("Prefilter ambiguous response (treating as No): %s", raw[:200])
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
