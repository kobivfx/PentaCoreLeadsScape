"""ScoringStage – local-LLM-first with cloud fallback and DB context."""
from __future__ import annotations

import json
import logging
from typing import Any

from ...core.db import DatabaseManager
from ...core.models import Lead
from . import PipelineStage

log = logging.getLogger(__name__)


class ScoringStage(PipelineStage):
    name = "scoring"

    def __init__(self, db: DatabaseManager, mock: bool = False, dry_run: bool = False):
        self._db = db
        self._mock = mock
        self._dry_run = dry_run

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]

        if self._dry_run:
            emit("Skipping scoring (dry run)", 92)
            return ctx

        # Score leads that passed prefilter and have enrichment data
        leads = self._db.get_leads(
            offset=0, limit=100, status="new",
            order_by="rule_score DESC",
        )
        # Only score leads with prefilter_result=="Yes" and not already scored by LLM
        to_score = [l for l in leads if l.prefilter_result == "Yes" and not l.scoring_provider]
        if not to_score:
            emit("No leads to LLM-score", 92)
            return ctx

        emit(f"LLM scoring {len(to_score)} leads…", 85)

        # Get historical context for scoring
        context_leads = self._db.get_scored_leads_for_context(limit=20)
        scoring_context = self._build_scoring_context(context_leads)

        # Try local LLM first, fall back to cloud
        provider, provider_name = self._get_scoring_provider()
        scored = 0
        for lead in to_score:
            if cancel and cancel.is_set():
                break
            try:
                self._score_lead(lead, provider, provider_name, scoring_context, stats)
                scored += 1
            except Exception as e:
                log.error("Scoring failed for %s: %s", lead.lead_id, e)
                stats["errors"].append(f"score {lead.lead_id}: {e}")

        stats["llm_scored"] = scored
        emit(f"LLM scored {scored} leads", 92)
        return ctx

    def _score_lead(self, lead: Lead, provider, provider_name: str,
                    scoring_context: str, stats: dict):
        """Score a single lead."""
        # Load scoring prompt
        scoring_prompt = self._get_scoring_prompt()

        # Build prompt with enrichment data and context
        enrichment_str = "No enrichment data."
        if lead.enrichment_json and lead.enrichment_json != "{}":
            try:
                enrich = json.loads(lead.enrichment_json)
                parts = []
                for k, v in enrich.items():
                    if k.startswith("_"):
                        continue
                    if v:
                        parts.append(f"  {k}: {v}")
                enrichment_str = "\n".join(parts) if parts else "No enrichment data."
            except json.JSONDecodeError:
                pass

        prompt = scoring_prompt.format(
            title=lead.title,
            url=lead.url,
            text=lead.text[:2000],
            domain=lead.domain,
            keyword_group=lead.keyword_group_id,
            keyword=lead.keyword_used or lead.query_used,
            enrichment=enrichment_str,
            context=scoring_context,
        )

        if provider is None:
            # No provider available – use rule score as fallback
            self._db.update_lead_scoring_v2(
                lead.lead_id,
                auto_score=lead.rule_score,
                score_reason="rule-based (no LLM provider)",
                agent_json=lead.agent_json or "{}",
                lead_type="unknown",
                author=lead.author,
                scoring_provider=provider_name,
            )
            return

        if hasattr(provider, 'enrich'):
            # Local LLM provider
            raw = provider.enrich(prompt)
        elif hasattr(provider, 'score_candidate'):
            # Cloud provider - create a mock candidate for scoring
            from ...core.models import LeadCandidate
            cand = LeadCandidate(
                title=lead.title, text=lead.text, url=lead.url,
                domain=lead.domain, source=lead.source,
                actor_name=lead.actor_name, query_used=lead.query_used,
            )
            result = provider.score_candidate(cand, {"enrichment": enrichment_str, "context": scoring_context})
            self._db.update_lead_scoring_v2(
                lead.lead_id,
                auto_score=result.score,
                score_reason=result.score_reason,
                agent_json=result.to_json(),
                lead_type=result.lead_type,
                author=result.client_name,
                scoring_provider=provider_name,
                client_name=result.client_name,
            )
            return
        else:
            return

        # Parse local LLM response
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            parsed = json.loads(cleaned)
            client_name_parsed = str(parsed.get("company_name", "")) or str(parsed.get("client_name", ""))
            self._db.update_lead_scoring_v2(
                lead.lead_id,
                auto_score=float(parsed.get("score", 5)),
                score_reason=str(parsed.get("reason", "")),
                agent_json=cleaned,
                lead_type=str(parsed.get("lead_type", "unknown")),
                author=client_name_parsed or lead.author,
                scoring_provider=provider_name,
                client_name=client_name_parsed,
            )
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Score parse error: %s", e)
            self._db.update_lead_scoring_v2(
                lead.lead_id,
                auto_score=lead.rule_score,
                score_reason=f"parse_error: {raw[:200]}",
                agent_json="{}",
                lead_type="unknown",
                author=lead.author,
                scoring_provider=provider_name,
            )

    def _build_scoring_context(self, context_leads: list[Lead]) -> str:
        """Build historical context string from previously scored leads."""
        if not context_leads:
            return "No historical data available."
        lines = []
        for l in context_leads[:10]:
            star = "★" if l.is_starred else ""
            lines.append(
                f"- [{l.auto_score:.0f}] {star} {l.title[:60]} | {l.domain} | "
                f"{l.score_reason[:60] if l.score_reason else ''}"
            )
        return "\n".join(lines)

    def _get_scoring_provider(self) -> tuple:
        """Get provider for scoring. Uses configurable provider selection."""
        from ..provider_manager import ProviderManager
        
        pm = ProviderManager(self._db, mock=self._mock)
        provider, provider_name = pm.get_provider_for_stage("scoring")
        
        # If local provider is not available, try fallback to cloud provider
        if not provider:
            # Fallback to active cloud provider
            from ...core.secrets_manager import SecretsManager
            from ...providers import get_provider_instance
            active_id = self._db.get_active_provider_id()
            provider_data = self._db.get_provider(active_id)
            if not provider_data or not provider_data.enabled or active_id in ("local_llm", "qwen"):
                return None, "none"
            secrets = SecretsManager(self._db.db_path)
            api_key = secrets.get_secret(provider_data.secret_key_name) or ""
            if not api_key and not self._mock:
                return None, "none"
            p = get_provider_instance(active_id, api_key, provider_data.config, mock=self._mock)
            return p, active_id
        
        return provider, provider_name

    def _get_scoring_prompt(self) -> str:
        pt = self._db.get_prompt_template("scoring_prompt")
        if pt and pt.template_text:
            return pt.template_text
        return (
            "You are a lead scorer for a 3D animation outsourcing studio.\n\n"
            "Evaluate this lead:\n"
            "Title: {title}\nURL: {url}\nDomain: {domain}\n"
            "Keyword group: {keyword_group}\nKeyword: {keyword}\n"
            "Text: {text}\n\nEnrichment:\n{enrichment}\n\n"
            "Context from previously scored leads:\n{context}\n\n"
            "Return JSON: {{\"score\": 0-10, \"reason\": \"...\", "
            "\"lead_type\": \"game_trailer|commercial|other\", \"company_name\": \"...\"}}"
        )
