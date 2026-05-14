"""Domain data classes."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Setting:
    key: str
    value_json: str = "{}"

    @property
    def value(self) -> Any:
        return json.loads(self.value_json)

    @staticmethod
    def from_value(key: str, value: Any) -> "Setting":
        return Setting(key=key, value_json=json.dumps(value))


@dataclass
class SecretRef:
    key: str
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Provider:
    provider_id: str
    enabled: int = 0
    display_name: str = ""
    config_json: str = "{}"
    secret_key_name: str = ""

    @property
    def config(self) -> dict:
        return json.loads(self.config_json) if self.config_json else {}

    @config.setter
    def config(self, v: dict):
        self.config_json = json.dumps(v)


@dataclass
class KeywordGroup:
    group_id: str
    name: str = ""
    description: str = ""
    prefilter_prompt: str = ""
    prefilter_input_template: str = ""
    analysis_prompt: str = ""
    created_at: str = ""


@dataclass
class ActorGroupVars:
    actor_name: str
    group_id: str
    maxresults: int = 10
    region: str = "us"
    timelimit: str = "3"


@dataclass
class Actor:
    actor_name: str
    enabled: int = 1
    source: str = "google"
    actor_id: str = ""
    input_template_json: str = "{}"
    query_strategy_json: str = "{}"
    output_mapping_json: str = "{}"
    transform_hook: str | None = None
    notes: str = ""
    allowed_groups_json: str = "[]"
    extraction_rules: str = ""
    default_maxresults: int = 10
    default_region: str = "us"
    default_timelimit: str = "3"

    @property
    def input_template(self) -> dict:
        return json.loads(self.input_template_json) if self.input_template_json else {}

    @property
    def query_strategy(self) -> dict:
        return json.loads(self.query_strategy_json) if self.query_strategy_json else {}

    @property
    def output_mapping(self) -> dict:
        return json.loads(self.output_mapping_json) if self.output_mapping_json else {}

    @property
    def allowed_groups(self) -> list[str]:
        return json.loads(self.allowed_groups_json) if self.allowed_groups_json else []

    @allowed_groups.setter
    def allowed_groups(self, v: list[str]):
        self.allowed_groups_json = json.dumps(v)


@dataclass
class Run:
    run_id: str
    started_at: str = ""
    finished_at: str = ""
    status: str = "running"
    stats_json: str = "{}"
    error: str = ""
    log_path: str = ""

    @property
    def stats(self) -> dict:
        return json.loads(self.stats_json) if self.stats_json else {}


@dataclass
class RawItem:
    raw_id: int | None = None
    run_id: str = ""
    actor_name: str = ""
    source: str = ""
    query_used: str = ""
    url: str = ""
    raw_json: str = ""
    fetched_at: str = ""


@dataclass
class Lead:
    lead_id: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    source: str = ""
    actor_name: str = ""
    query_used: str = ""
    title: str = ""
    text: str = ""
    url: str = ""
    author: str = ""
    lead_type: str = ""
    rule_score: float = 0.0
    auto_score: int = 0
    score_reason: str = ""
    agent_json: str = ""
    status: str = "new"
    manual_score: int | None = None
    manual_feedback: str = ""
    tags_json: str = "[]"
    is_starred: int = 0
    # V2 fields
    keyword_group_id: str = ""
    keyword_used: str = ""
    prefilter_result: str = ""
    prefilter_model: str = ""
    prefilter_raw: str = ""
    prefilter_checked_at: str = ""
    enrichment_json: str = "{}"
    enrichment_provider: str = ""
    scoring_provider: str = ""
    client_name: str = ""

    @property
    def domain(self) -> str:
        """Compute domain from URL (removed from DB schema)."""
        if not self.url:
            return ""
        try:
            from urllib.parse import urlparse
            host = urlparse(self.url).netloc.lower()
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return ""

    @classmethod
    def from_row(cls, d: dict) -> "Lead":
        """Create Lead from a database row dict, handling schema migrations."""
        d = dict(d)
        d.pop("domain", None)
        if "company_guess" in d:
            d["author"] = d.pop("company_guess")
        return cls(**d)

    @property
    def tags(self) -> list[str]:
        return json.loads(self.tags_json) if self.tags_json else []

    @tags.setter
    def tags(self, v: list[str]):
        self.tags_json = json.dumps(v)

    @property
    def agent_data(self) -> dict:
        return json.loads(self.agent_json) if self.agent_json else {}

    @property
    def enrichment_data(self) -> dict:
        return json.loads(self.enrichment_json) if self.enrichment_json else {}

    @enrichment_data.setter
    def enrichment_data(self, v: dict):
        self.enrichment_json = json.dumps(v)


@dataclass
class Keyword:
    keyword: str
    status: str = "active"
    weight: int = 5
    added_by: str = "seed"
    last_used_at: str = ""
    avg_manual_score: float = 0.0
    uses_count: int = 0
    notes: str = ""
    group_id: str = ""


@dataclass
class NegativeKeyword:
    phrase: str
    enabled: int = 1
    notes: str = ""


@dataclass
class DomainBlacklist:
    domain: str
    reason: str = ""
    created_at: str = ""


@dataclass
class EnrichmentCache:
    cache_id: int | None = None
    lead_id: str = ""
    query: str = ""
    result_json: str = "{}"
    source_url: str = ""
    fetched_at: str = ""


@dataclass
class PromptTemplate:
    template_id: str
    template_text: str = ""
    description: str = ""
    updated_at: str = ""


@dataclass
class LeadCandidate:
    """Intermediate representation before scoring."""
    url: str = ""
    title: str = ""
    text: str = ""
    author: str = ""
    source: str = ""
    actor_name: str = ""
    query_used: str = ""
    domain: str = ""
    keyword_group_id: str = ""
    keyword_used: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentResult:
    """Strict JSON contract from scoring provider."""
    lead_type: str = "irrelevant"
    score: int = 0
    score_reason: str = ""
    buyer_signals: list[str] = field(default_factory=list)
    client_name: str = ""
    project_type_guess: list[str] = field(default_factory=list)
    recommended_action: str = "ignore"
    keyword_suggestions: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_dict(d: dict) -> "AgentResult":
        return AgentResult(
            lead_type=d.get("lead_type", "irrelevant"),
            score=int(d.get("score", 0)),
            score_reason=d.get("score_reason", ""),
            buyer_signals=d.get("buyer_signals", []),
            client_name=d.get("client_name", d.get("company_guess", "")),
            project_type_guess=d.get("project_type_guess", []),
            recommended_action=d.get("recommended_action", "ignore"),
            keyword_suggestions=d.get("keyword_suggestions", []),
            negative_keywords=d.get("negative_keywords", []),
        )


@dataclass
class Client:
    """Deduplicated client record extracted from analysis."""
    client_id: str = ""
    name: str = ""
    domain: str = ""
    contact: str = ""
    lead_count: int = 0
    lead_ids_json: str = "[]"
    created_at: str = ""
    updated_at: str = ""
    client_score: int = 0
    client_reason: str = ""
    revenue_scale: str = ""
    introduction: str = ""
    client_analyzed_at: str = ""
    starred: int = 0
    contacted: int = 0
    notes: str = ""
    tag: str = ""
    row_color: str = ""  # Hex color for row highlighting

    @property
    def lead_ids(self) -> list[str]:
        return json.loads(self.lead_ids_json) if self.lead_ids_json else []

    @lead_ids.setter
    def lead_ids(self, v: list[str]):
        self.lead_ids_json = json.dumps(v)
