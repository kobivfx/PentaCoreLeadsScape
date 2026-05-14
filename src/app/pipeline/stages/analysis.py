"""AnalysisStage – merged scoring + enrichment using a single LLM call per lead.

Passes lead URL, content, and author into a user-editable prompt and expects
structured JSON output with: score, reason, client_name, brand, contact, domain.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from ...core.db import DatabaseManager
from ...core.models import Client, Lead
from . import PipelineStage

log = logging.getLogger(__name__)

DEFAULT_ANALYSIS_PROMPT = (
    "You are an expert lead-qualification agent for a 3D animation outsourcing studio. "
    "Your studio provides: game cinematics, brand mascot animation, animated commercials, "
    "product animation, and CGI content."
    "Please score bellow infomation (can this become my client?):\n"
    "Content: {content}\n"
    "Author: {author}\n"
    "URL (for more infomation): {url}\n"
    "Return answer in this JSON format:\n"
    '{{"score": <0-100>, "reason": "<why>", "client_name": "<potential client company>", '
    '"contact": "<email if you find>", "domain": "<client domain if you find>"}}'
)


class AnalysisStage(PipelineStage):
    name = "analysis"

    def __init__(self, db: DatabaseManager, mock: bool = False, dry_run: bool = False):
        self._db = db
        self._mock = mock
        self._dry_run = dry_run

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]

        if self._dry_run:
            emit("Skipping analysis (dry run)", 92)
            return ctx

        # Get leads that passed prefilter but have not been analyzed yet
        to_analyze = self._db.get_leads_for_analysis()
        if not to_analyze:
            emit("No leads to analyze", 92)
            return ctx

        emit(f"Analyzing {len(to_analyze)} leads…", 80)

        provider, provider_name = self._get_analysis_provider()
        default_prompt = self._get_analysis_prompt()

        # Load groups for per-group analysis prompts
        groups = {g.group_id: g for g in self._db.get_keyword_groups()}

        analyzed = 0
        consecutive_errors = 0
        max_consecutive_errors = 5
        total = len(to_analyze)
        for i, lead in enumerate(to_analyze):
            if cancel and cancel.is_set():
                break

            # Emit progress every lead
            done = i + 1
            pct = 75 + int(17 * done / total)  # 75-92% range
            emit(f"Analysis: {done}/{total} (✓{analyzed} err:{consecutive_errors})", pct)

            # Resolve per-group analysis prompt, fallback to default
            group = groups.get(lead.keyword_group_id)
            prompt_template = (
                group.analysis_prompt
                if group and group.analysis_prompt
                else default_prompt
            )
            try:
                self._analyze_lead(lead, provider, provider_name, prompt_template, stats)
                analyzed += 1
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                log.error("Analysis failed for %s: %s", lead.lead_id, e)
                stats["errors"].append(f"analysis {lead.lead_id}: {e}")
                if consecutive_errors >= max_consecutive_errors:
                    log.error("Too many consecutive analysis errors (%d), stopping",
                              consecutive_errors)
                    emit(f"Analysis stopped: {consecutive_errors} consecutive errors", 85)
                    break

        stats["analyzed"] = analyzed
        emit(f"Analyzed {analyzed} leads", 92)
        return ctx

    def _analyze_lead(self, lead: Lead, provider, provider_name: str,
                      prompt_template: str, stats: dict):
        """Analyze a single lead – send URL+content+author to LLM, parse JSON response."""
        if provider is None:
            self._db.update_lead_analysis(
                lead.lead_id,
                auto_score=lead.rule_score,
                score_reason="rule-based (no LLM provider)",
                agent_json="{}",
                lead_type="unknown",
                author=lead.author,
                enrichment_json=lead.enrichment_json,
                enrichment_provider="",
                scoring_provider=provider_name,
            )
            return

        prompt = prompt_template.replace("{url}", lead.url or "")
        prompt = prompt.replace("{content}", (lead.text or "")[:2000])
        prompt = prompt.replace("{author}", lead.author or "")

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

            score = float(parsed.get("score", 5))
            reason = str(parsed.get("reason", ""))
            client_name = str(parsed.get("client_name", ""))
            brand = str(parsed.get("brand", ""))
            contact = str(parsed.get("contact", ""))
            domain = str(parsed.get("domain", ""))

            enrichment = {
                "client_name": client_name,
                "brand": brand,
                "contact": contact,
                "domain": domain,
                "reason": reason,
            }

            self._db.update_lead_analysis(
                lead.lead_id,
                auto_score=score,
                score_reason=reason,
                agent_json=cleaned,
                lead_type="analyzed",
                author=brand or lead.author,
                enrichment_json=json.dumps(enrichment),
                enrichment_provider=provider_name,
                scoring_provider=provider_name,
                client_name=client_name,
            )

            # Extract and upsert client if identified and score meets threshold
            client_threshold = self._db.get_setting("client_creation_threshold", 50)
            try:
                client_threshold = int(client_threshold)
            except (TypeError, ValueError):
                client_threshold = 50
            if client_name and score >= client_threshold:
                self._upsert_client_from_analysis(
                    client_name=client_name,
                    domain=domain,
                    contact=contact,
                    lead_id=lead.lead_id,
                )
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Analysis parse error for %s: %s", lead.lead_id, e)
            self._db.update_lead_analysis(
                lead.lead_id,
                auto_score=lead.rule_score,
                score_reason=f"parse_error: {raw[:200] if raw else ''}",
                agent_json="{}",
                lead_type="unknown",
                author=lead.author,
                enrichment_json=lead.enrichment_json,
                enrichment_provider="",
                scoring_provider=provider_name,
            )

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Extract JSON from an LLM response that may contain markdown fences or surrounding text."""
        # Try to find a ```json ... ``` block first
        m = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", raw, re.DOTALL)
        if m:
            return m.group(1).strip()
        # Fallback: find the first { ... } block
        m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if m:
            return m.group(0)
        # Last resort: return stripped raw
        return raw.strip()

    def _upsert_client_from_analysis(self, client_name: str, domain: str,
                                      contact: str, lead_id: str):
        """Create or update a client record from analysis results."""
        client_id = hashlib.sha256(client_name.lower().strip().encode()).hexdigest()[:16]
        client = Client(
            client_id=client_id,
            name=client_name.strip(),
            domain=domain,
            contact=contact,
            lead_count=1,
            lead_ids_json=json.dumps([lead_id]),
        )
        self._db.upsert_client(client)

    def _get_analysis_provider(self) -> tuple:
        """Get provider for the analysis stage."""
        from ..provider_manager import ProviderManager

        pm = ProviderManager(self._db, mock=self._mock)
        provider, provider_name = pm.get_provider_for_stage("analysis")

        if not provider:
            # Fallback to active cloud provider
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

    def _get_analysis_prompt(self) -> str:
        """Get the analysis prompt template from DB, or use default."""
        pt = self._db.get_prompt_template("analysis_prompt")
        if pt and pt.template_text:
            return pt.template_text
        return DEFAULT_ANALYSIS_PROMPT
