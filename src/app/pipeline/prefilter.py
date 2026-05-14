"""Pre-filter: cheap rule-based scoring and blacklist/negative-keyword filtering."""
from __future__ import annotations

import logging
import re

from ..core.models import LeadCandidate, Keyword, NegativeKeyword

log = logging.getLogger(__name__)

# Signal phrases and their weights for rule scoring
_POSITIVE_SIGNALS = {
    "outsourc": 5, "vendor": 4, "partner": 3, "studio": 3,
    "cinemat": 5, "cutscene": 5, "trailer": 4, "reveal": 3,
    "3d anim": 5, "character anim": 4, "motion capture": 4, "mocap": 4,
    "rigging": 3, "facial anim": 4, "real-time": 2,
    "brand mascot": 5, "animated commercial": 5, "product anim": 4,
    "animated ad": 4, "campaign": 2, "cgi": 3,
    "game studio": 3, "publisher": 2, "announce": 2,
    "seeking": 3, "looking for": 3, "hiring": 1, "rfp": 5, "request for proposal": 5,
}

_NEGATIVE_SIGNALS = {
    "tutorial": -3, "course": -3, "how to": -3, "learn": -2,
    "salary": -4, "internship": -3, "school": -3, "degree": -3,
    "anime": -3, "manga": -3, "meme": -4, "watch order": -5,
    "free download": -4, "crack": -5, "torrent": -5,
}


def compute_rule_score(candidate: LeadCandidate,
                       keywords: list[Keyword],
                       negative_keywords: list[NegativeKeyword]) -> float:
    """Compute a cheap rule-based relevance score in [0, 100]."""
    text = f"{candidate.title} {candidate.text}".lower()
    score = 0.0

    # Positive signal matching
    for signal, weight in _POSITIVE_SIGNALS.items():
        if signal in text:
            score += weight

    # Negative signal matching
    for signal, weight in _NEGATIVE_SIGNALS.items():
        if signal in text:
            score += weight  # weight is negative

    # Keyword match bonus
    for kw in keywords:
        if kw.keyword.lower() in text:
            score += kw.weight * 0.5

    # Negative keyword penalty
    for nk in negative_keywords:
        if nk.enabled and nk.phrase.lower() in text:
            score -= 10

    return max(0.0, min(100.0, score))


def is_blacklisted(candidate: LeadCandidate, blacklisted_domains: set[str]) -> bool:
    """Check if the candidate's domain is blacklisted."""
    return candidate.domain in blacklisted_domains


def passes_negative_filter(candidate: LeadCandidate,
                           negative_keywords: list[NegativeKeyword]) -> bool:
    """Return False if candidate matches a enabled negative keyword."""
    text = f"{candidate.title} {candidate.text}".lower()
    for nk in negative_keywords:
        if nk.enabled and nk.phrase.lower() in text:
            # Only reject if it's clearly irrelevant (strict match)
            if len(nk.phrase) > 10 and nk.phrase.lower() in text:
                return False
    return True
