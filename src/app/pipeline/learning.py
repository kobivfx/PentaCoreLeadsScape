"""Learning loop: update keyword weights, propose new keywords, domain blacklist suggestions."""
from __future__ import annotations

import logging
from collections import defaultdict

from ..core.db import DatabaseManager
from ..core.models import Keyword, NegativeKeyword, AgentResult

log = logging.getLogger(__name__)


def run_learning(db: DatabaseManager):
    """Update keyword weights based on manual score correlations."""
    leads = db.get_leads_for_learning()
    if not leads:
        return

    # keyword → list of manual scores
    kw_scores: dict[str, list[int]] = defaultdict(list)
    for lead in leads:
        if lead.manual_score is None:
            continue
        kw = lead.query_used
        if kw:
            kw_scores[kw].append(lead.manual_score)

    for kw, scores in kw_scores.items():
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        db.update_keyword_stats(kw, avg_manual_score=avg)

        # Adjust weight based on performance
        keyword_obj = None
        for k in db.get_keywords():
            if k.keyword == kw:
                keyword_obj = k
                break
        if keyword_obj:
            if avg >= 7:
                new_weight = min(10, keyword_obj.weight + 1)
            elif avg <= 3:
                new_weight = max(1, keyword_obj.weight - 1)
            else:
                new_weight = keyword_obj.weight
            if new_weight != keyword_obj.weight:
                keyword_obj.weight = new_weight
                db.save_keyword(keyword_obj)
                log.info("Adjusted keyword '%s' weight to %d (avg_score=%.1f)",
                         kw, new_weight, avg)

    log.info("Learning loop completed for %d leads", len(leads))


def process_agent_suggestions(db: DatabaseManager, results: list[AgentResult]):
    """Store keyword/negative-keyword suggestions from agent scoring."""
    existing_kw = {k.keyword.lower() for k in db.get_keywords()}
    existing_neg = {n.phrase.lower() for n in db.get_negative_keywords()}

    new_kw_count = 0
    new_neg_count = 0

    for result in results:
        for suggestion in result.keyword_suggestions:
            s = suggestion.strip()
            if s and s.lower() not in existing_kw:
                db.save_keyword(Keyword(
                    keyword=s, status="paused", weight=5,
                    added_by="learned", notes="Suggested by scoring agent",
                ))
                existing_kw.add(s.lower())
                new_kw_count += 1

        for neg in result.negative_keywords:
            n = neg.strip()
            if n and n.lower() not in existing_neg:
                db.save_negative_keyword(NegativeKeyword(
                    phrase=n, enabled=0, notes="Suggested by scoring agent",
                ))
                existing_neg.add(n.lower())
                new_neg_count += 1

    if new_kw_count:
        log.info("Added %d new keyword suggestions (paused)", new_kw_count)
    if new_neg_count:
        log.info("Added %d new negative keyword suggestions (disabled)", new_neg_count)


def suggest_blacklist_domains(db: DatabaseManager, threshold: int = 5):
    """Suggest blacklisting domains that repeatedly produce low-scored leads."""
    leads = db.get_leads_for_learning()
    domain_scores: dict[str, list[int]] = defaultdict(list)
    for lead in leads:
        if lead.manual_score is not None and lead.domain:
            domain_scores[lead.domain].append(lead.manual_score)

    existing_bl = {d.domain for d in db.get_domain_blacklist()}
    for domain, scores in domain_scores.items():
        if domain in existing_bl:
            continue
        if len(scores) >= threshold and (sum(scores) / len(scores)) <= 2.0:
            db.add_domain_blacklist(domain, reason=f"Auto-suggested: avg score {sum(scores)/len(scores):.1f} over {len(scores)} leads")
            log.info("Auto-blacklisted domain: %s", domain)
