"""Main pipeline engine – orchestrates the full lead-discovery cycle."""
from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timezone
from threading import Event
from typing import Callable

from ..core.db import DatabaseManager, _now
from ..core.models import (
    Actor, AgentResult, Keyword, Lead, LeadCandidate, NegativeKeyword, RawItem, Run,
)
from ..core.secrets_manager import SecretsManager
from .apify_runner import ApifyRunner
from .mapping import canonicalize_url, compute_lead_id, extract_domain, map_raw_item
from .prefilter import compute_rule_score, is_blacklisted, passes_negative_filter
from .learning import run_learning, process_agent_suggestions, suggest_blacklist_domains
from .stages.scrape import ScrapeStage
from .stages.normalize import NormalizeStage
from .stages.group_prefilter import GroupPrefilterStage
from .stages.analysis import AnalysisStage
from .stages.client_analysis import ClientAnalysisStage

log = logging.getLogger(__name__)


class PipelineEngine:
    """Full lead-discovery pipeline, designed to run in a background thread."""

    def __init__(self, db: DatabaseManager, secrets: SecretsManager,
                 cancel_event: Event | None = None,
                 progress_callback: Callable[[str, int], None] | None = None,
                 dry_run: bool = False, mock_run: bool = False, group_ids: list = None):
        self.db = db
        self.secrets = secrets
        self._cancel = cancel_event or Event()
        self._progress = progress_callback or (lambda msg, pct: None)
        self._dry_run = dry_run
        self._mock_run = mock_run
        self._group_ids = group_ids or ["all"]

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _emit(self, msg: str, pct: int = -1):
        log.info(msg)
        self._progress(msg, pct)

    # ------------------------------------------------------------------
    def run(self) -> str:
        """Execute the full stage-based pipeline. Returns run_id."""
        run_id = uuid.uuid4().hex[:16]
        log_path = str(self.db.db_path.parent / "logs" / f"run_{run_id}.log")
        run = Run(run_id=run_id, started_at=_now(), status="running", log_path=log_path)
        self.db.create_run(run)
        stats = {
            "raw_items": 0, "leads_new": 0, "leads_updated": 0, "scored": 0,
            "prefilter_passed": 0, "prefilter_rejected": 0, "enriched": 0,
            "llm_scored": 0, "errors": [],
        }

        try:
            # Build shared context
            ctx = {
                "run_id": run_id,
                "stats": stats,
                "cancel_event": self._cancel,
                "emit": self._emit,
                "group_ids": self._group_ids,
            }

            # Stage 1: Scrape
            self._emit("Stage 1/5: Scraping…", 5)
            scrape = ScrapeStage(self.db, self.secrets, mock=self._mock_run, dry_run=self._dry_run)
            ctx = scrape.execute(ctx)
            if self.cancelled:
                self._finish_run(run, run_id, stats, "cancelled")
                return run_id

            # Stage 2: Normalize (prefilter, rule-score, dedupe, upsert)
            self._emit("Stage 2/5: Normalizing…", 30)
            normalize = NormalizeStage(self.db)
            ctx = normalize.execute(ctx)
            if self.cancelled:
                self._finish_run(run, run_id, stats, "cancelled")
                return run_id

            # Stage 3: Group Prefilter (local LLM Yes/No)
            self._emit("Stage 3/5: Group prefiltering…", 50)
            prefilter = GroupPrefilterStage(self.db, mock=self._mock_run)
            ctx = prefilter.execute(ctx)
            if self.cancelled:
                self._finish_run(run, run_id, stats, "cancelled")
                return run_id

            # Stage 4: Analysis (merged scoring + enrichment)
            self._emit("Stage 4/5: Analyzing…", 70)
            analysis = AnalysisStage(self.db, mock=self._mock_run, dry_run=self._dry_run)
            ctx = analysis.execute(ctx)
            if self.cancelled:
                self._finish_run(run, run_id, stats, "cancelled")
                return run_id

            # Stage 5: Client Analysis (analyze new clients with LLM)
            self._emit("Stage 5/5: Analyzing clients…", 85)
            client_analysis = ClientAnalysisStage(self.db, mock=self._mock_run, dry_run=self._dry_run)
            ctx = client_analysis.execute(ctx)
            if self.cancelled:
                self._finish_run(run, run_id, stats, "cancelled")
                return run_id

            # Learning loop (kept from v1)
            if not self._dry_run:
                self._emit("Running learning loop…", 95)
                run_learning(self.db)
                suggest_blacklist_domains(self.db)

            self._finish_run(run, run_id, stats, "success")
            self._emit("Pipeline completed successfully!", 100)

        except Exception as e:
            log.exception("Pipeline failed: %s", e)
            stats["errors"].append(str(e))
            self._finish_run(run, run_id, stats, "failed", error=str(e))

        return run_id

    # ------------------------------------------------------------------
    def _run_actor(self, runner: ApifyRunner, actor: Actor,
                   keywords: list[Keyword], run_id: str, stats: dict) -> list[LeadCandidate]:
        """Build queries and run a single actor."""
        queries = self._build_queries(actor, keywords)
        candidates = []

        for query in queries:
            if self.cancelled:
                break
            input_data = self._build_input(actor, query)
            log.info("Running %s with query: %s", actor.actor_name, query[:80])
            raw_items = runner.run_actor(actor.actor_id, input_data)
            stats["raw_items"] += len(raw_items)

            # Store raw items
            now = _now()
            db_items = []
            for item in raw_items:
                url = item.get("url", "")
                db_items.append(RawItem(
                    run_id=run_id, actor_name=actor.actor_name,
                    source=actor.source, query_used=query,
                    url=str(url), raw_json=json.dumps(item, default=str),
                    fetched_at=now,
                ))
            if db_items:
                self.db.insert_raw_items(db_items)

            # Map to candidates
            mapping = actor.output_mapping
            for item in raw_items:
                cand = map_raw_item(item, mapping, actor.actor_name, actor.source, query)
                if cand:
                    candidates.append(cand)

        return candidates

    def _build_queries(self, actor: Actor, keywords: list[Keyword]) -> list[str]:
        """Build search queries from keywords using actor's query strategy."""
        strategy = actor.query_strategy
        mode = strategy.get("mode", "all")
        template = strategy.get("template", "{keyword}")
        max_queries = strategy.get("max_queries", 10)

        active_kw = [kw for kw in keywords if kw.status == "active"]
        if not active_kw:
            return []

        if mode == "weighted_sample":
            weights = [kw.weight for kw in active_kw]
            total = sum(weights)
            n = min(max_queries, len(active_kw))
            if total == 0:
                selected = random.sample(active_kw, n)
            else:
                # Weighted sampling WITHOUT replacement
                selected = []
                pool = list(active_kw)
                pool_weights = list(weights)
                for _ in range(n):
                    if not pool:
                        break
                    pick = random.choices(pool, weights=pool_weights, k=1)[0]
                    selected.append(pick)
                    idx = pool.index(pick)
                    pool.pop(idx)
                    pool_weights.pop(idx)
        else:
            selected = active_kw[:max_queries]

        queries = []
        for kw in selected:
            q = template.replace("{keyword}", kw.keyword)
            queries.append(q)
            # Update usage
            self.db.update_keyword_stats(kw.keyword, uses_count_delta=1)

        return queries

    def _build_input(self, actor: Actor, query: str) -> dict:
        """Build Apify actor input from template, substituting the query."""
        template = actor.input_template
        input_data = {}
        for k, v in template.items():
            if isinstance(v, str) and "{keywords}" in v:
                input_data[k] = v.replace("{keywords}", query)
            elif isinstance(v, list):
                input_data[k] = [
                    item.replace("{keywords}", query) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                input_data[k] = v
        return input_data

    # ------------------------------------------------------------------
    def _score_leads(self, leads: list[Lead], keywords: list[Keyword],
                     stats: dict) -> list[AgentResult]:
        """Score leads using the active LLM provider."""
        provider_id = self.db.get_active_provider_id()
        provider_data = self.db.get_provider(provider_id)
        if not provider_data or not provider_data.enabled:
            log.warning("Active provider '%s' not enabled, skipping scoring", provider_id)
            return []

        # Get the provider implementation
        from ..providers import get_provider_instance
        api_key = self.secrets.get_secret(provider_data.secret_key_name) or ""
        if not api_key and not self._mock_run:
            log.warning("No API key for provider '%s', skipping scoring", provider_id)
            return []

        provider_instance = get_provider_instance(
            provider_id, api_key, provider_data.config,
            mock=self._mock_run,
        )

        context = {
            "keywords": [k.keyword for k in keywords[:20]],
            "purpose": "3D animation outsourcing/vendor services for games and brands",
        }

        results = []
        for i, lead in enumerate(leads):
            if self.cancelled:
                break
            try:
                candidate = LeadCandidate(
                    url=lead.url, title=lead.title, text=lead.text,
                    source=lead.source, domain=lead.domain,
                )
                result = provider_instance.score_candidate(candidate, context)
                self.db.update_lead_scoring(
                    lead.lead_id,
                    auto_score=result.score,
                    score_reason=result.score_reason,
                    agent_json=result.to_json(),
                    lead_type=result.lead_type,
                    author=result.client_name,
                )
                results.append(result)
                stats["scored"] += 1
            except Exception as e:
                log.error("Scoring failed for lead %s: %s", lead.lead_id, e)
                stats["errors"].append(f"scoring {lead.lead_id}: {e}")

        return results

    # ------------------------------------------------------------------
    def _finish_run(self, run: Run, run_id: str, stats: dict, status: str,
                    error: str = ""):
        run.finished_at = _now()
        run.status = status
        run.stats_json = json.dumps(stats, default=str)
        run.error = error
        self.db.update_run(run)
        self._emit(f"Run {run_id} finished: {status}", 100)
