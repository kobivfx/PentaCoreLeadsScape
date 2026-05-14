"""EnrichmentStage – find missing info using local LLM + web search."""
from __future__ import annotations

import json
import logging
from typing import Any

from ...core.db import DatabaseManager
from ...core.models import Lead
from ..web_search import WebSearchConnector
from . import PipelineStage

log = logging.getLogger(__name__)


class EnrichmentStage(PipelineStage):
    name = "enrichment"

    def __init__(self, db: DatabaseManager, mock: bool = False, dry_run: bool = False):
        self._db = db
        self._mock = mock
        self._dry_run = dry_run

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]

        if self._dry_run:
            emit("Skipping enrichment (dry run)", 78)
            return ctx

        # Get leads that passed prefilter but have no enrichment
        leads = self._db.get_leads_needing_enrichment(limit=30)
        if not leads:
            emit("No leads need enrichment", 78)
            return ctx

        emit(f"Enriching {len(leads)} leads…", 75)

        provider = self._get_enrichment_provider()
        searcher = WebSearchConnector(self._db)

        # Load enrichment prompt and schema from DB
        enrichment_template = self._get_enrichment_prompt()
        enrichment_schema = self._get_enrichment_schema()

        enriched = 0
        for lead in leads:
            if cancel and cancel.is_set():
                break

            try:
                result = self._enrich_lead(lead, provider, searcher, enrichment_template)
                if result:
                    provider_name = "mock" if self._mock else "local_llm"
                    self._db.update_lead_enrichment(
                        lead.lead_id,
                        json.dumps(result),
                        provider_name,
                    )
                    enriched += 1
            except Exception as e:
                log.error("Enrichment failed for %s: %s", lead.lead_id, e)
                stats["errors"].append(f"enrich {lead.lead_id}: {e}")

        stats["enriched"] = enriched
        emit(f"Enriched {enriched} leads", 80)
        return ctx

    def _enrich_lead(self, lead: Lead, provider, searcher: WebSearchConnector,
                     prompt_template: str) -> dict | None:
        """Enrich a single lead with web search + LLM analysis."""
        # Step 1: Search for additional info
        search_queries = self._build_search_queries(lead)
        search_context = []
        for query in search_queries[:3]:
            results = searcher.search(query, lead_id=lead.lead_id, max_results=3)
            for r in results:
                search_context.append(f"- {r['title']}: {r['snippet']}")

        # Step 2: Run enrichment prompt through LLM
        search_text = "\n".join(search_context) if search_context else "No additional search results found."

        prompt = prompt_template.format(
            title=lead.title,
            url=lead.url,
            text=lead.text[:2000],
            domain=lead.domain,
            search_results=search_text,
        )

        if provider:
            try:
                raw = provider.enrich(prompt)
                # Parse structured response
                cleaned = raw.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    cleaned = "\n".join(lines)
                result = json.loads(cleaned)
                # Add citations
                result["_search_results"] = search_context[:5]
                return result
            except (json.JSONDecodeError, Exception) as e:
                log.error("Enrichment parse error: %s", e)
                return {"_raw_response": raw[:1000] if 'raw' in dir() else "",
                        "_search_results": search_context[:5], "_error": str(e)}
        else:
            # No provider, just return search results
            return {"_search_results": search_context[:5]} if search_context else None

    def _build_search_queries(self, lead: Lead) -> list[str]:
        """Build search queries from lead info."""
        queries = []
        if lead.author:
            queries.append(f"{lead.author} 3D animation outsourcing")
        if lead.domain and lead.domain != "":
            queries.append(f"site:{lead.domain} contact email animation")
        if lead.title:
            # Use key terms from title
            queries.append(f"{lead.title[:60]} company contact")
        return queries

    def _get_enrichment_provider(self):
        """Get enrichment provider via provider manager."""
        from ..provider_manager import ProviderManager
        
        pm = ProviderManager(self._db, mock=self._mock)
        provider, _ = pm.get_provider_for_stage("enrichment")
        
        if not provider:
            # Try fallback to active cloud provider
            return self._get_cloud_fallback()
        
        return provider

    def _get_cloud_fallback(self):
        """Get cloud provider as fallback."""
        from ...core.secrets_manager import SecretsManager
        from ...providers import get_provider_instance
        active_id = self._db.get_active_provider_id()
        provider_data = self._db.get_provider(active_id)
        if not provider_data or not provider_data.enabled or active_id in ("local_llm", "qwen"):
            return None
        secrets = SecretsManager(self._db.db_path)
        api_key = secrets.get_secret(provider_data.secret_key_name) or ""
        if not api_key and not self._mock:
            return None
        return get_provider_instance(active_id, api_key, provider_data.config, mock=self._mock)

    def _get_enrichment_prompt(self) -> str:
        pt = self._db.get_prompt_template("enrichment_prompt")
        if pt and pt.template_text:
            # Add search_results placeholder if not present
            tmpl = pt.template_text
            if "{search_results}" not in tmpl:
                tmpl += "\n\nAdditional web search results:\n{search_results}"
            return tmpl
        return (
            "You are a research assistant. Given the following lead information, "
            "find missing details.\n\n"
            "Lead:\n- Title: {title}\n- URL: {url}\n- Text: {text}\n- Domain: {domain}\n\n"
            "Additional web search results:\n{search_results}\n\n"
            "Return a JSON object with: company_name, contact_email, contact_name, "
            "publisher, project_details, budget_indicator, sources."
        )

    def _get_enrichment_schema(self) -> dict:
        pt = self._db.get_prompt_template("enrichment_schema")
        if pt and pt.template_text:
            try:
                return json.loads(pt.template_text)
            except json.JSONDecodeError:
                pass
        return {
            "company_name": "", "contact_email": "", "contact_name": "",
            "publisher": "", "project_details": "", "budget_indicator": "",
            "sources": [],
        }
