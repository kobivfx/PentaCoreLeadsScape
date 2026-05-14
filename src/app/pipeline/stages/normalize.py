"""NormalizeStage – prefilter, rule-score, dedupe, and upsert leads."""
from __future__ import annotations

import logging
from typing import Any

from ...core.db import DatabaseManager, _now
from ...core.models import Lead, LeadCandidate, Keyword, NegativeKeyword
from ..mapping import compute_lead_id
from ..prefilter import compute_rule_score, is_blacklisted, passes_negative_filter
from . import PipelineStage

log = logging.getLogger(__name__)


class NormalizeStage(PipelineStage):
    name = "normalize"

    def __init__(self, db: DatabaseManager):
        self._db = db

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]
        candidates: list[LeadCandidate] = ctx.get("candidates", [])

        keywords = self._db.get_keywords(status="active")
        neg_keywords = self._db.get_negative_keywords()
        blacklisted = {d.domain for d in self._db.get_domain_blacklist()}

        emit(f"Collected {len(candidates)} candidates, filtering…", 55)

        scored: list[tuple[LeadCandidate, float]] = []
        for cand in candidates:
            if cancel and cancel.is_set():
                break
            if is_blacklisted(cand, blacklisted):
                continue
            if not passes_negative_filter(cand, neg_keywords):
                continue
            rule_score = compute_rule_score(cand, keywords, neg_keywords)
            scored.append((cand, rule_score))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Deduplicate candidates by URL – keep highest rule_score per URL
        seen_urls: set[str] = set()
        unique_scored: list[tuple[LeadCandidate, float]] = []
        for cand, rule_score in scored:
            lead_id = compute_lead_id(cand.url)
            if lead_id in seen_urls:
                continue
            seen_urls.add(lead_id)
            unique_scored.append((cand, rule_score))

        dedup_removed = len(scored) - len(unique_scored)
        if dedup_removed:
            log.info("Removed %d duplicate candidates (same URL)", dedup_removed)

        emit(f"Upserting {len(unique_scored)} leads…", 60)
        for cand, rule_score in unique_scored:
            if cancel and cancel.is_set():
                break
            lead_id = compute_lead_id(cand.url)
            existing = self._db.get_lead(lead_id)
            now = _now()
            lead = Lead(
                lead_id=lead_id,
                first_seen_at=existing.first_seen_at if existing else now,
                last_seen_at=now,
                source=cand.source,
                actor_name=cand.actor_name,
                query_used=cand.query_used,
                title=cand.title,
                text=cand.text,
                url=cand.url,
                author=cand.author,
                rule_score=rule_score,
                status=existing.status if existing else "new",
                manual_score=existing.manual_score if existing else None,
                manual_feedback=existing.manual_feedback if existing else "",
                tags_json=existing.tags_json if existing else "[]",
                is_starred=existing.is_starred if existing else 0,
                keyword_group_id=cand.keyword_group_id,
                keyword_used=cand.keyword_used,
            )
            self._db.upsert_lead(lead)
            if existing:
                stats["leads_updated"] += 1
            else:
                stats["leads_new"] += 1

        ctx["lead_count"] = len(unique_scored)
        return ctx
