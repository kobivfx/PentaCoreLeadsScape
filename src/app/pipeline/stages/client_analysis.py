"""ClientAnalysisStage – evaluate clients using LLM to enrich with score, reason, revenue scale, introduction."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ...core.db import DatabaseManager
from ...core.models import Client
from . import PipelineStage

log = logging.getLogger(__name__)

DEFAULT_CLIENT_ANALYSIS_PROMPT = (
    "You are an expert lead-qualification agent for a 3D animation studio. "
    "Your studio provides: game cinematics, brand mascot animation, animated commercials, "
    "product animation, animation film and CGI content.\n\n"
    "Please score the client below (based on revenue, activity level, etc.):\n\n"
    "Client: {name}\n"
    "Domain (for more information): {domain}\n\n"
    "Return answer in this JSON format:\n"
    '{{\n'
    '  "score": <0-100>,\n'
    '  "reason": "<why>",\n'
    '  "revenue_scale": "<estimated revenue or company scale if available>",\n'
    '  "introduction": "<brief introduction about the client>",\n'
    '  "contact": "<email if you find>"\n'
    '}}'
)


class ClientAnalysisStage(PipelineStage):
    name = "client_analysis"

    def __init__(self, db: DatabaseManager, mock: bool = False, dry_run: bool = False):
        self._db = db
        self._mock = mock
        self._dry_run = dry_run

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]

        if self._dry_run:
            emit("Skipping client analysis (dry run)", 98)
            return ctx

        # Get clients that haven't been analyzed yet
        clients = self._db.get_clients_for_analysis(limit=50)
        if not clients:
            emit("No clients to analyze", 98)
            return ctx

        emit(f"Analyzing {len(clients)} clients…", 95)

        provider, provider_name = self._get_analysis_provider()
        prompt_template = self._get_client_analysis_prompt()

        analyzed = 0
        for client in clients:
            if cancel and cancel.is_set():
                break
            try:
                self._analyze_client(client, provider, provider_name, prompt_template)
                analyzed += 1
            except Exception as e:
                log.error("Client analysis failed for %s: %s", client.client_id, e)
                stats["errors"].append(f"client_analysis {client.name}: {e}")

        stats["clients_analyzed"] = analyzed
        emit(f"Analyzed {analyzed} clients", 98)
        return ctx

    def analyze_clients(self, clients: list[Client],
                        progress_callback=None) -> tuple[int, list[str]]:
        """Analyze a list of clients (for manual re-analysis). Returns (count, errors)."""
        provider, provider_name = self._get_analysis_provider()
        prompt_template = self._get_client_analysis_prompt()

        analyzed = 0
        errors = []
        for i, client in enumerate(clients):
            if progress_callback:
                progress_callback(f"Analyzing {client.name}… ({i+1}/{len(clients)})", 
                                  int(100 * i / len(clients)))
            try:
                self._analyze_client(client, provider, provider_name, prompt_template)
                analyzed += 1
            except Exception as e:
                log.error("Client analysis failed for %s: %s", client.client_id, e)
                errors.append(f"{client.name}: {e}")
        return analyzed, errors

    def _analyze_client(self, client: Client, provider, provider_name: str,
                        prompt_template: str):
        """Analyze a single client using LLM."""
        if provider is None:
            log.warning("No provider available for client analysis")
            return

        prompt = prompt_template.replace("{name}", client.name or "")
        prompt = prompt.replace("{domain}", client.domain or "")

        if hasattr(provider, "analyze"):
            raw = provider.analyze(prompt)
        elif hasattr(provider, "generate"):
            raw = provider.generate(prompt)
        elif hasattr(provider, "enrich"):
            raw = provider.enrich(prompt)
        else:
            log.error("Provider %s has no analyze/generate/enrich method", provider_name)
            return

        try:
            cleaned = self._extract_json(raw)
            parsed = json.loads(cleaned)

            score = int(parsed.get("score", 0))
            score = max(0, min(100, score))
            reason = str(parsed.get("reason", ""))
            revenue_scale = str(parsed.get("revenue_scale", ""))
            introduction = str(parsed.get("introduction", ""))
            contact = str(parsed.get("contact", "")).strip()
            tag = str(parsed.get("type", "")).strip()

            self._db.update_client_analysis(
                client.client_id,
                score=score,
                reason=reason,
                revenue_scale=revenue_scale,
                introduction=introduction,
                contact=contact,
                tag=tag,
            )
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Client analysis parse error for %s: %s", client.name, e)

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Extract JSON from an LLM response that may contain markdown fences."""
        m = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", raw, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if m:
            return m.group(0)
        return raw.strip()

    def _get_analysis_provider(self) -> tuple:
        """Get provider for client analysis (reuses analysis stage provider)."""
        from ..provider_manager import ProviderManager

        pm = ProviderManager(self._db, mock=self._mock)
        provider, provider_name = pm.get_provider_for_stage("analysis")

        if not provider:
            from ...core.secrets_manager import SecretsManager
            from ...providers import get_provider_instance

            active_id = self._db.get_active_provider_id()
            provider_data = self._db.get_provider(active_id)
            if not provider_data or not provider_data.enabled:
                return None, "none"
            secrets = SecretsManager(self._db.db_path)
            api_key = secrets.get_secret(provider_data.secret_key_name) or ""
            if not api_key and not self._mock:
                return None, "none"
            p = get_provider_instance(
                active_id, api_key, provider_data.config, mock=self._mock
            )
            return p, active_id

        return provider, provider_name

    def _get_client_analysis_prompt(self) -> str:
        """Get client analysis prompt from settings, or use default."""
        prompt = self._db.get_setting("client_analysis_prompt", "")
        if prompt:
            return prompt
        return DEFAULT_CLIENT_ANALYSIS_PROMPT
