"""SQLite database manager – schema, CRUD, seed data."""
from __future__ import annotations

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR, DB_PATH
from .models import (
    Actor, ActorGroupVars, Client, DomainBlacklist, EnrichmentCache, Keyword, KeywordGroup, Lead,
    NegativeKeyword, PromptTemplate, Provider, RawItem, Run,
)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT
);

CREATE TABLE IF NOT EXISTS secrets (
    key TEXT PRIMARY KEY,
    encrypted_value TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS providers (
    provider_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    display_name TEXT DEFAULT '',
    config_json TEXT DEFAULT '{}',
    secret_key_name TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS keyword_groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    prefilter_prompt TEXT DEFAULT '',
    prefilter_input_template TEXT DEFAULT '',
    analysis_prompt TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS actors (
    actor_name TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    source TEXT DEFAULT 'google',
    actor_id TEXT DEFAULT '',
    input_template_json TEXT DEFAULT '{}',
    query_strategy_json TEXT DEFAULT '{}',
    output_mapping_json TEXT DEFAULT '{}',
    transform_hook TEXT,
    notes TEXT DEFAULT '',
    allowed_groups_json TEXT DEFAULT '[]',
    extraction_rules TEXT DEFAULT '',
    default_maxresults INTEGER DEFAULT 10,
    default_region TEXT DEFAULT 'us',
    default_timelimit TEXT DEFAULT '3'
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    status TEXT DEFAULT 'running',
    stats_json TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    log_path TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS raw_items (
    raw_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    actor_name TEXT,
    source TEXT,
    query_used TEXT,
    url TEXT,
    raw_json TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    first_seen_at TEXT,
    last_seen_at TEXT,
    source TEXT,
    actor_name TEXT,
    query_used TEXT,
    title TEXT DEFAULT '',
    text TEXT DEFAULT '',
    url TEXT DEFAULT '',
    author TEXT DEFAULT '',
    lead_type TEXT DEFAULT '',
    rule_score REAL DEFAULT 0,
    auto_score INTEGER DEFAULT 0,
    score_reason TEXT DEFAULT '',
    agent_json TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    manual_score INTEGER,
    manual_feedback TEXT DEFAULT '',
    tags_json TEXT DEFAULT '[]',
    is_starred INTEGER DEFAULT 0,
    keyword_group_id TEXT DEFAULT '',
    keyword_used TEXT DEFAULT '',
    prefilter_result TEXT DEFAULT '',
    prefilter_model TEXT DEFAULT '',
    prefilter_raw TEXT DEFAULT '',
    prefilter_checked_at TEXT DEFAULT '',
    enrichment_json TEXT DEFAULT '{}',
    enrichment_provider TEXT DEFAULT '',
    scoring_provider TEXT DEFAULT '',
    client_name TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS keywords (
    keyword TEXT PRIMARY KEY,
    status TEXT DEFAULT 'active',
    weight INTEGER DEFAULT 5,
    added_by TEXT DEFAULT 'seed',
    last_used_at TEXT,
    avg_manual_score REAL DEFAULT 0,
    uses_count INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    group_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS negative_keywords (
    phrase TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS domain_blacklist (
    domain TEXT PRIMARY KEY,
    reason TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS enrichment_cache (
    cache_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    query TEXT,
    result_json TEXT DEFAULT '{}',
    source_url TEXT DEFAULT '',
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    template_id TEXT PRIMARY KEY,
    template_text TEXT DEFAULT '',
    description TEXT DEFAULT '',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS actor_group_vars (
    actor_name TEXT NOT NULL,
    group_id TEXT NOT NULL,
    maxresults INTEGER DEFAULT 10,
    region TEXT DEFAULT 'us',
    timelimit TEXT DEFAULT '3',
    PRIMARY KEY (actor_name, group_id)
);

CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT DEFAULT '',
    contact TEXT DEFAULT '',
    lead_count INTEGER DEFAULT 0,
    lead_ids_json TEXT DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT,
    client_score INTEGER DEFAULT 0,
    client_reason TEXT DEFAULT '',
    revenue_scale TEXT DEFAULT '',
    introduction TEXT DEFAULT '',
    client_analyzed_at TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    tag TEXT DEFAULT '',
    row_color TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS keyword_group_memberships (
    keyword TEXT NOT NULL,
    group_id TEXT NOT NULL,
    PRIMARY KEY (keyword, group_id)
);
"""

_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_auto_score ON leads(auto_score);
CREATE INDEX IF NOT EXISTS idx_leads_manual_score ON leads(manual_score);
CREATE INDEX IF NOT EXISTS idx_leads_last_seen ON leads(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);
CREATE INDEX IF NOT EXISTS idx_leads_lead_type ON leads(lead_type);
CREATE INDEX IF NOT EXISTS idx_leads_group ON leads(keyword_group_id);
CREATE INDEX IF NOT EXISTS idx_leads_prefilter ON leads(prefilter_result);
CREATE INDEX IF NOT EXISTS idx_raw_items_run ON raw_items(run_id);
CREATE INDEX IF NOT EXISTS idx_keywords_group ON keywords(group_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_lead ON enrichment_cache(lead_id);
CREATE INDEX IF NOT EXISTS idx_clients_name ON clients(name);
"""

# ──────────────────────────────────────────────────────────────
# Migration helpers for existing v1 databases
# ──────────────────────────────────────────────────────────────
_MIGRATION_SQL = [
    # V2 columns on keywords
    "ALTER TABLE keywords ADD COLUMN group_id TEXT DEFAULT ''",
    # V2 columns on actors
    "ALTER TABLE actors ADD COLUMN allowed_groups_json TEXT DEFAULT '[]'",
    # V2 columns on leads
    "ALTER TABLE leads ADD COLUMN keyword_group_id TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN keyword_used TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN prefilter_result TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN prefilter_model TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN prefilter_raw TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN prefilter_checked_at TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN enrichment_json TEXT DEFAULT '{}'",
    "ALTER TABLE leads ADD COLUMN enrichment_provider TEXT DEFAULT ''",
    "ALTER TABLE leads ADD COLUMN scoring_provider TEXT DEFAULT ''",
    # V3: rename company_guess → author, drop domain
    "ALTER TABLE leads RENAME COLUMN company_guess TO author",
    "ALTER TABLE leads DROP COLUMN domain",
    # V4: prefilter input template per keyword group
    "ALTER TABLE keyword_groups ADD COLUMN prefilter_input_template TEXT DEFAULT ''",
    # V5: analysis prompt per keyword group
    "ALTER TABLE keyword_groups ADD COLUMN analysis_prompt TEXT DEFAULT ''",
    # V6: extraction rules per actor
    "ALTER TABLE actors ADD COLUMN extraction_rules TEXT DEFAULT ''",
    # V7: client analysis fields
    "ALTER TABLE clients ADD COLUMN client_score INTEGER DEFAULT 0",
    "ALTER TABLE clients ADD COLUMN client_reason TEXT DEFAULT ''",
    "ALTER TABLE clients ADD COLUMN revenue_scale TEXT DEFAULT ''",
    "ALTER TABLE clients ADD COLUMN introduction TEXT DEFAULT ''",
    "ALTER TABLE clients ADD COLUMN client_analyzed_at TEXT DEFAULT ''",
    # V8: client starred and contacted flags
    "ALTER TABLE clients ADD COLUMN starred INTEGER DEFAULT 0",
    "ALTER TABLE clients ADD COLUMN contacted INTEGER DEFAULT 0",
    # V9: client_name on leads
    "ALTER TABLE leads ADD COLUMN client_name TEXT DEFAULT ''",
    # V10: actor_group_vars table
    """CREATE TABLE IF NOT EXISTS actor_group_vars (
        actor_name TEXT NOT NULL,
        group_id TEXT NOT NULL,
        maxresults INTEGER DEFAULT 10,
        region TEXT DEFAULT 'us',
        timelimit INTEGER DEFAULT 3,
        PRIMARY KEY (actor_name, group_id)
    )""",
    # V11: change timelimit from INTEGER to TEXT in actor_group_vars
    """CREATE TABLE IF NOT EXISTS actor_group_vars_new (
        actor_name TEXT NOT NULL,
        group_id TEXT NOT NULL,
        maxresults INTEGER DEFAULT 10,
        region TEXT DEFAULT 'us',
        timelimit TEXT DEFAULT '3',
        PRIMARY KEY (actor_name, group_id)
    )""",
    "INSERT INTO actor_group_vars_new (actor_name, group_id, maxresults, region, timelimit) SELECT actor_name, group_id, maxresults, region, CAST(timelimit AS TEXT) FROM actor_group_vars",
    "DROP TABLE actor_group_vars",
    "ALTER TABLE actor_group_vars_new RENAME TO actor_group_vars",
    # V12: add default variable columns to actors table
    "ALTER TABLE actors ADD COLUMN default_maxresults INTEGER DEFAULT 10",
    "ALTER TABLE actors ADD COLUMN default_region TEXT DEFAULT 'us'",
    "ALTER TABLE actors ADD COLUMN default_timelimit TEXT DEFAULT '3'",
    # V13: add notes column to clients table
    "ALTER TABLE clients ADD COLUMN notes TEXT DEFAULT ''",
    # V14: keyword many-to-many groups
    """CREATE TABLE IF NOT EXISTS keyword_group_memberships (
        keyword TEXT NOT NULL,
        group_id TEXT NOT NULL,
        PRIMARY KEY (keyword, group_id)
    )""",
    "INSERT OR IGNORE INTO keyword_group_memberships (keyword, group_id) SELECT keyword, group_id FROM keywords WHERE group_id IS NOT NULL AND group_id != ''",
    # V15: add tag column to clients table
    "ALTER TABLE clients ADD COLUMN tag TEXT DEFAULT ''",
    # V16: add row_color column for bulk color editing
    "ALTER TABLE clients ADD COLUMN row_color TEXT DEFAULT ''",
]

# ──────────────────────────────────────────────────────────────
# Seed data
# ──────────────────────────────────────────────────────────────
SEED_KEYWORDS_GAME = [
    "3D animation outsourcing", "game cinematics outsourcing", "game trailer animation",
    "cutscene animation studio", "AAA game animation vendor", "indie game cinematic",
    "character animation outsourcing", "motion capture cleanup service",
    "rigging outsourcing studio", "facial animation service", "game reveal trailer studio",
    "real-time cinematic production", "game marketing animation", "Unreal Engine cinematic",
    "Unity cutscene animation", "in-game animation outsourcing", "game animation pipeline",
    "keyframe animation studio", "3D game asset animation", "game studio cinematic partner",
]

SEED_KEYWORDS_BRAND = [
    "animated commercial production", "brand mascot animation", "product animation studio",
    "3D animated advertisement", "brand character animation", "animated social media ad",
    "3D product visualization animation", "animated campaign production",
    "brand animation studio", "explainer animation 3D", "commercial animation outsourcing",
    "animated brand content", "3D animated logo reveal", "agency animation production",
    "CGI commercial", "advertising animation studio", "product launch animation",
    "corporate animation vendor", "digital campaign animation", "motion graphics 3D commercial",
]

SEED_NEGATIVE = [
    "anime watch order", "animation tutorial beginner", "how to animate blender",
    "blender tutorial", "animation degree program", "animation school ranking",
    "animation salary survey", "free animation software", "2D animation course",
    "animation meme", "cartoon drawing tutorial", "animation job posting",
    "learn maya free", "student animation reel", "animation internship",
]

SEED_KEYWORD_GROUPS = [
    KeywordGroup(
        group_id="game_trailer",
        name="Game Trailer",
        description="Keywords for game announcement / release / cinematics outsourcing",
        prefilter_prompt="You are an expert lead-qualification agent for a 3D animation outsourcing studio. Your studio provides: game cinematics, brand mascot animation, animated commercials, product animation, and CGI content, animation feature film, animation IP, animation series, game trailer. Is the information below have a chance to be a lead? Answer Yes or No only.",
        analysis_prompt="You are an expert lead-qualification agent for a 3D animation outsourcing studio. Your studio provides: game cinematics, brand mascot animation, animated commercials, product animation, and CGI content.Please score bellow infomation (can this become my client?):\nContent: {content}\nAuthor: {author}\nURL (for more infomation): {url}\nReturn answer in this JSON format:\n{\"score\": <0-100>, \"reason\": \"<why>\", \"client_name\": \"<potential client company>\", \"contact\": \"<email if you find>\", \"domain\": \"<client domain if you find>\"}\n",
    ),
    KeywordGroup(
        group_id="commercial",
        name="Commercial / Brand",
        description="Keywords for brand mascot, commercial, product animation campaigns",
        prefilter_prompt="You are an expert lead-qualification agent for a 3D animation outsourcing studio. Your studio provides: game cinematics, brand mascot animation, animated commercials, product animation, and CGI content, animation feature film, animation IP, animation series, game trailer. Is the information below have a chance to be a lead? Answer Yes or No only.",
        analysis_prompt="You are an expert lead-qualification agent for a 3D animation outsourcing studio. Your studio provides: game cinematics, brand mascot animation, animated commercials, product animation, and CGI content.Please score bellow infomation (can this become my client?):\nContent: {content}\nAuthor: {author}\nURL (for more infomation): {url}\nReturn answer in this JSON format:\n{\"score\": <0-100>, \"reason\": \"<why>\", \"client_name\": \"<potential client company>\", \"contact\": \"<email if you find>\", \"domain\": \"<client domain if you find>\"}\n",
    ),
]

SEED_PROVIDERS = [
    Provider("gemini", 1, "Google Gemini", json.dumps({
        "model": "gemini-2.0-flash", "max_output_tokens": 2048,
        "temperature": 0.2, "rate_limit_rpm": 15,
    }), "gemini_api_key"),
    Provider("openai", 0, "OpenAI GPT", json.dumps({
        "model": "gpt-4o-mini", "max_tokens": 2048,
        "temperature": 0.2, "rate_limit_rpm": 20,
    }), "openai_api_key"),
    Provider("anthropic", 0, "Anthropic Claude", json.dumps({
        "model": "claude-sonnet-4-20250514", "max_tokens": 2048,
        "temperature": 0.2, "rate_limit_rpm": 20,
    }), "anthropic_api_key"),
    Provider("local_llm", 1, "Local LLM (Gemma 4)", json.dumps({
        "mode": "http",
        "model_path": "",
        "http_base_url": "http://localhost:8080",
        "http_model": "gemma-4",
        "context_size": 8192,
        "temperature": 0.1,
        "max_tokens": 2048,
        "n_gpu_layers": -1,
    }), ""),
    Provider("qwen", 0, "Qwen (Local)", json.dumps({
        "mode": "direct",
        "model_path": "",
        "http_base_url": "http://localhost:11434",
        "http_model": "qwen",
        "context_size": 8192,
        "temperature": 0.1,
        "max_tokens": 2048,
        "n_gpu_layers": -1,
    }), ""),
    Provider("deepseek", 0, "DeepSeek API", json.dumps({
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "max_output_tokens": 2048,
        "temperature": 0.2,
    }), "deepseek_api_key"),
]

SEED_ACTORS = [
    Actor(
        actor_name="google_search",
        enabled=1,
        source="google",
        actor_id="apify/google-search-scraper",
        input_template_json=json.dumps({
            "queries": "{keywords}",
            "maxPagesPerQuery": 3,
            "languageCode": "en",
            "resultsPerPage": 20,
        }),
        query_strategy_json=json.dumps({
            "mode": "weighted_sample", "max_queries": 10, "template": "{keyword}",
        }),
        output_mapping_json=json.dumps({
            "url": "url", "title": "title", "text": "description",
        }),
        notes="Default Google Search actor",
        allowed_groups_json=json.dumps(["game_trailer", "commercial"]),
    ),
    Actor(
        actor_name="x_search",
        enabled=1,
        source="x",
        actor_id="apidojo/tweet-scraper",
        input_template_json=json.dumps({
            "searchTerms": ["{keywords}"],
            "maxTweets": 50,
            "sort": "Latest",
        }),
        query_strategy_json=json.dumps({
            "mode": "weighted_sample", "max_queries": 5,
            "template": "{keyword} 3D animation",
        }),
        output_mapping_json=json.dumps({
            "url": "url", "title": "full_text[:120]", "text": "full_text",
        }),
        notes="Default X/Twitter search actor",
        allowed_groups_json=json.dumps(["game_trailer", "commercial"]),
    ),
    Actor(
        actor_name="linkedin_search",
        enabled=1,
        source="linkedin",
        actor_id="anchor/linkedin-search",
        input_template_json=json.dumps({
            "searchTerms": "{keywords}",
            "deepScrape": False,
            "maxResults": 25,
        }),
        query_strategy_json=json.dumps({
            "mode": "weighted_sample", "max_queries": 5,
            "template": "{keyword} outsourcing vendor",
        }),
        output_mapping_json=json.dumps({
            "url": "url", "title": "title", "text": "description",
        }),
        notes="Default LinkedIn search actor",
        allowed_groups_json=json.dumps(["game_trailer", "commercial"]),
    ),
]

SEED_PROMPT_TEMPLATES = [
    PromptTemplate(
        template_id="enrichment_prompt",
        template_text=(
            "You are a research assistant. Given the following lead information, find missing details.\n\n"
            "Lead:\n- Title: {title}\n- URL: {url}\n- Text: {text}\n- Domain: {domain}\n\n"
            "Find and return a JSON object with these fields:\n"
            '{{\n  "company_name": "<company or brand name>",\n'
            '  "contact_email": "<email if found, else empty>",\n'
            '  "contact_name": "<contact person if found>",\n'
            '  "publisher": "<publisher or parent company>",\n'
            '  "project_details": "<brief description of the project/campaign>",\n'
            '  "budget_indicator": "<any budget/scale indicators>",\n'
            '  "sources": ["<URLs used>"]\n}}\n\n'
            "Return ONLY valid JSON."
        ),
        description="Prompt for the enrichment stage to find missing lead information",
    ),
    PromptTemplate(
        template_id="enrichment_schema",
        template_text=json.dumps({
            "company_name": "", "contact_email": "", "contact_name": "",
            "publisher": "", "project_details": "", "budget_indicator": "",
            "sources": [],
        }, indent=2),
        description="Expected JSON schema for enrichment output fields",
    ),
    PromptTemplate(
        template_id="scoring_prompt",
        template_text=(
            "You are an expert lead-qualification agent for a 3D animation outsourcing studio.\n"
            "Your studio provides: game cinematics, cutscenes, character animation, rigging, mocap cleanup,\n"
            "facial animation, brand mascot animation, animated commercials, product animation, and CGI content.\n\n"
            "Analyze the following lead with enrichment data and return a JSON object ONLY.\n\n"
            "Lead:\n- URL: {url}\n- Title: {title}\n- Text: {text}\n- Source: {source}\n- Domain: {domain}\n"
            "- Enrichment: {enrichment}\n\n"
            "Historical context (similar leads scored):\n{history}\n\n"
            "Return EXACTLY this JSON schema:\n"
            '{{\n  "lead_type": "vendor_search | outsourcing | announcement | brand_campaign | irrelevant",\n'
            '  "score": <integer 0-10>,\n'
            '  "score_reason": "<one-sentence explanation>",\n'
            '  "buyer_signals": ["<signal1>", "<signal2>"],\n'
            '  "client_name": "<company name or empty string>",\n'
            '  "project_type_guess": ["<from: game cinematics, marketing, in-game, character animation, rigging, mocap cleanup, facial, brand mascot, animated commercial, product animation, unknown>"],\n'
            '  "recommended_action": "save | contact | ignore",\n'
            '  "keyword_suggestions": ["<new keywords to track>"],\n'
            '  "negative_keywords": ["<phrases to filter out>"]\n}}\n\n'
            "Return ONLY valid JSON."
        ),
        description="Prompt for the lead scoring stage",
    ),
    PromptTemplate(
        template_id="analysis_prompt",
        template_text=(
            "You are an expert lead-qualification agent for a 3D animation outsourcing studio. "
            "Your studio provides: game cinematics, brand mascot animation, animated commercials, "
            "product animation, and CGI content.\n\n"
            "Please score this content (can this become my client?):\n"
            "URL: {url}\n"
            "Author: {author}\n"
            "Content: {content}\n\n"
            "Return answer in this JSON format:\n"
            '{{"score": <0-10>, "reason": "<why>", "client_name": "<potential client company>", '
            '"brand": "<if have>", "contact": "<email if have>", "domain": "<business domain if have>"}}'
        ),
        description="Prompt for the merged analysis stage (scoring + enrichment in one call)",
    ),
]


# ──────────────────────────────────────────────────────────────
# DatabaseManager
# ──────────────────────────────────────────────────────────────
class DatabaseManager:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = DB_PATH
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.row_factory = sqlite3.Row
        return con

    def switch_database(self, new_path: str | Path):
        """Switch to a different database file. Validates and initialises schema."""
        new_path = Path(new_path)
        if not new_path.exists():
            raise FileNotFoundError(f"Database file not found: {new_path}")
        # Validate it's a real SQLite file
        try:
            con = sqlite3.connect(str(new_path))
            con.execute("PRAGMA integrity_check")
            con.close()
        except sqlite3.DatabaseError as e:
            raise ValueError(f"Invalid SQLite database: {e}")
        self.db_path = new_path
        self._init_schema()

    @staticmethod
    def create_new_database(path: str | Path) -> "DatabaseManager":
        """Create a fresh database with the full schema at the given path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return DatabaseManager(path)

    def _init_schema(self):
        with self.connect() as con:
            con.executescript(_SCHEMA_SQL)
            self._run_migrations(con)
            con.executescript(_INDEXES_SQL)
            self._seed_if_empty(con)

    def _run_migrations(self, con: sqlite3.Connection):
        """Apply ALTER TABLE migrations for v1→v2 upgrades (safe to re-run)."""
        for stmt in _MIGRATION_SQL:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists

    def _seed_if_empty(self, con: sqlite3.Connection):
        # Keyword groups
        cnt = con.execute("SELECT COUNT(*) FROM keyword_groups").fetchone()[0]
        if cnt == 0:
            log.info("Seeding keyword groups …")
            now = _now()
            for g in SEED_KEYWORD_GROUPS:
                con.execute(
                    "INSERT OR IGNORE INTO keyword_groups "
                    "(group_id, name, description, prefilter_prompt, prefilter_input_template, analysis_prompt, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (g.group_id, g.name, g.description, g.prefilter_prompt,
                     getattr(g, "prefilter_input_template", ""),
                     getattr(g, "analysis_prompt", ""), now),
                )
        # Keywords
        cnt = con.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]
        if cnt == 0:
            log.info("Seeding keywords …")
            now = _now()
            for kw in SEED_KEYWORDS_GAME:
                con.execute(
                    "INSERT OR IGNORE INTO keywords (keyword, status, weight, added_by, last_used_at, group_id) VALUES (?,?,?,?,?,?)",
                    (kw, "active", 5, "seed", now, "game_trailer"),
                )
            for kw in SEED_KEYWORDS_BRAND:
                con.execute(
                    "INSERT OR IGNORE INTO keywords (keyword, status, weight, added_by, last_used_at, group_id) VALUES (?,?,?,?,?,?)",
                    (kw, "active", 5, "seed", now, "commercial"),
                )
            for neg in SEED_NEGATIVE:
                con.execute(
                    "INSERT OR IGNORE INTO negative_keywords (phrase, enabled, notes) VALUES (?,?,?)",
                    (neg, 1, "seed"),
                )
        # Providers
        cnt = con.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
        if cnt == 0:
            log.info("Seeding providers …")
            for p in SEED_PROVIDERS:
                con.execute(
                    "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?)",
                    (p.provider_id, p.enabled, p.display_name, p.config_json, p.secret_key_name),
                )
        else:
            # Ensure local_llm provider exists
            r = con.execute("SELECT 1 FROM providers WHERE provider_id='local_llm'").fetchone()
            if not r:
                p = SEED_PROVIDERS[-3]  # local_llm is third to last
                con.execute(
                    "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?)",
                    (p.provider_id, p.enabled, p.display_name, p.config_json, p.secret_key_name),
                )
            # Ensure qwen provider exists
            r = con.execute("SELECT 1 FROM providers WHERE provider_id='qwen'").fetchone()
            if not r:
                p = SEED_PROVIDERS[-2]  # qwen is second to last
                con.execute(
                    "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?)",
                    (p.provider_id, p.enabled, p.display_name, p.config_json, p.secret_key_name),
                )
            # Ensure deepseek provider exists
            r = con.execute("SELECT 1 FROM providers WHERE provider_id='deepseek'").fetchone()
            if not r:
                p = SEED_PROVIDERS[-1]  # deepseek is last
                con.execute(
                    "INSERT OR IGNORE INTO providers VALUES (?,?,?,?,?)",
                    (p.provider_id, p.enabled, p.display_name, p.config_json, p.secret_key_name),
                )
        # Actors
        cnt = con.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
        if cnt == 0:
            log.info("Seeding actors …")
            for a in SEED_ACTORS:
                con.execute(
                    "INSERT OR IGNORE INTO actors "
                    "(actor_name, enabled, source, actor_id, input_template_json, "
                    "query_strategy_json, output_mapping_json, transform_hook, notes, "
                    "allowed_groups_json, extraction_rules) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (a.actor_name, a.enabled, a.source, a.actor_id,
                     a.input_template_json, a.query_strategy_json,
                     a.output_mapping_json, a.transform_hook, a.notes,
                     a.allowed_groups_json, getattr(a, "extraction_rules", "")),
                )
        # Prompt templates
        cnt = con.execute("SELECT COUNT(*) FROM prompt_templates").fetchone()[0]
        if cnt == 0:
            log.info("Seeding prompt templates …")
            for pt in SEED_PROMPT_TEMPLATES:
                con.execute(
                    "INSERT OR IGNORE INTO prompt_templates VALUES (?,?,?,?)",
                    (pt.template_id, pt.template_text, pt.description, _now()),
                )
        else:
            # Ensure analysis_prompt template exists
            r = con.execute("SELECT 1 FROM prompt_templates WHERE template_id='analysis_prompt'").fetchone()
            if not r:
                pt = [t for t in SEED_PROMPT_TEMPLATES if t.template_id == "analysis_prompt"][0]
                con.execute(
                    "INSERT OR IGNORE INTO prompt_templates VALUES (?,?,?,?)",
                    (pt.template_id, pt.template_text, pt.description, _now()),
                )

    # ── Settings ──────────────────────────────────────────────
    def get_setting(self, key: str, default=None):
        with self.connect() as con:
            from .config import get_setting
            return get_setting(con, key, default)

    def set_setting(self, key: str, value):
        with self.connect() as con:
            from .config import set_setting
            set_setting(con, key, value)

    # ── Providers ─────────────────────────────────────────────
    def get_providers(self) -> list[Provider]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM providers ORDER BY display_name").fetchall()
        return [Provider(**dict(r)) for r in rows]

    def get_provider(self, pid: str) -> Provider | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM providers WHERE provider_id=?", (pid,)).fetchone()
        return Provider(**dict(r)) if r else None

    def save_provider(self, p: Provider):
        with self.connect() as con:
            con.execute(
                """INSERT INTO providers VALUES (?,?,?,?,?)
                   ON CONFLICT(provider_id) DO UPDATE SET
                     enabled=excluded.enabled, display_name=excluded.display_name,
                     config_json=excluded.config_json, secret_key_name=excluded.secret_key_name""",
                (p.provider_id, p.enabled, p.display_name, p.config_json, p.secret_key_name),
            )

    def get_active_provider_id(self) -> str:
        return self.get_setting("active_provider", "gemini")

    # ── Actors ────────────────────────────────────────────────
    def get_actors(self, enabled_only: bool = False) -> list[Actor]:
        with self.connect() as con:
            q = "SELECT * FROM actors"
            if enabled_only:
                q += " WHERE enabled=1"
            q += " ORDER BY actor_name"
            rows = con.execute(q).fetchall()
        return [Actor(**dict(r)) for r in rows]

    def get_actor(self, name: str) -> Actor | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM actors WHERE actor_name=?", (name,)).fetchone()
        return Actor(**dict(r)) if r else None

    def save_actor(self, a: Actor):
        with self.connect() as con:
            con.execute(
                """INSERT INTO actors (actor_name, enabled, source, actor_id,
                     input_template_json, query_strategy_json, output_mapping_json,
                     transform_hook, notes, allowed_groups_json, extraction_rules,
                     default_maxresults, default_region, default_timelimit)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(actor_name) DO UPDATE SET
                     enabled=excluded.enabled, source=excluded.source,
                     actor_id=excluded.actor_id,
                     input_template_json=excluded.input_template_json,
                     query_strategy_json=excluded.query_strategy_json,
                     output_mapping_json=excluded.output_mapping_json,
                     transform_hook=excluded.transform_hook, notes=excluded.notes,
                     allowed_groups_json=excluded.allowed_groups_json,
                     extraction_rules=excluded.extraction_rules,
                     default_maxresults=excluded.default_maxresults,
                     default_region=excluded.default_region,
                     default_timelimit=excluded.default_timelimit""",
                (a.actor_name, a.enabled, a.source, a.actor_id,
                 a.input_template_json, a.query_strategy_json,
                 a.output_mapping_json, a.transform_hook, a.notes,
                 a.allowed_groups_json, a.extraction_rules,
                 a.default_maxresults, a.default_region, a.default_timelimit),
            )

    def delete_actor(self, name: str):
        with self.connect() as con:
            con.execute("DELETE FROM actors WHERE actor_name=?", (name,))
            con.execute("DELETE FROM actor_group_vars WHERE actor_name=?", (name,))

    # ── Actor-Group Variables ─────────────────────────────────
    def get_actor_group_vars(self, actor_name: str, group_id: str) -> ActorGroupVars:
        with self.connect() as con:
            r = con.execute(
                "SELECT * FROM actor_group_vars WHERE actor_name=? AND group_id=?",
                (actor_name, group_id),
            ).fetchone()
        if r:
            return ActorGroupVars(**dict(r))
        # Fallback: use actor's own defaults
        actor = self.get_actor(actor_name)
        if actor:
            return ActorGroupVars(
                actor_name=actor_name, group_id=group_id,
                maxresults=actor.default_maxresults,
                region=actor.default_region,
                timelimit=actor.default_timelimit,
            )
        return ActorGroupVars(actor_name=actor_name, group_id=group_id)

    def save_actor_group_vars(self, v: ActorGroupVars):
        with self.connect() as con:
            con.execute(
                """INSERT INTO actor_group_vars (actor_name, group_id, maxresults, region, timelimit)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(actor_name, group_id) DO UPDATE SET
                     maxresults=excluded.maxresults, region=excluded.region,
                     timelimit=excluded.timelimit""",
                (v.actor_name, v.group_id, v.maxresults, v.region, v.timelimit),
            )

    def delete_actor_group_vars(self, actor_name: str, group_id: str):
        with self.connect() as con:
            con.execute(
                "DELETE FROM actor_group_vars WHERE actor_name=? AND group_id=?",
                (actor_name, group_id),
            )

    # ── Keywords ──────────────────────────────────────────────
    def get_keywords(self, status: str | None = None) -> list[Keyword]:
        base = """
            SELECT k.keyword, k.status, k.weight, k.added_by, k.last_used_at,
                   k.avg_manual_score, k.uses_count, k.notes,
                   COALESCE(GROUP_CONCAT(m.group_id), '') AS group_id
            FROM keywords k
            LEFT JOIN keyword_group_memberships m ON k.keyword = m.keyword
        """
        with self.connect() as con:
            if status:
                rows = con.execute(
                    base + "WHERE k.status=? GROUP BY k.keyword ORDER BY k.weight DESC, k.keyword",
                    (status,)
                ).fetchall()
            else:
                rows = con.execute(
                    base + "GROUP BY k.keyword ORDER BY k.weight DESC, k.keyword"
                ).fetchall()
        return [Keyword(**dict(r)) for r in rows]

    def save_keyword(self, kw: Keyword):
        with self.connect() as con:
            con.execute(
                """INSERT INTO keywords VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(keyword) DO UPDATE SET
                     status=excluded.status, weight=excluded.weight,
                     added_by=excluded.added_by, last_used_at=excluded.last_used_at,
                     avg_manual_score=excluded.avg_manual_score,
                     uses_count=excluded.uses_count, notes=excluded.notes""",
                (kw.keyword, kw.status, kw.weight, kw.added_by,
                 kw.last_used_at, kw.avg_manual_score, kw.uses_count, kw.notes,
                 kw.group_id),
            )
            # Also register in junction table if group_id is set
            if kw.group_id and ',' not in kw.group_id:
                con.execute(
                    "INSERT OR IGNORE INTO keyword_group_memberships (keyword, group_id) VALUES (?,?)",
                    (kw.keyword, kw.group_id),
                )

    def delete_keyword(self, kw: str):
        with self.connect() as con:
            con.execute("DELETE FROM keyword_group_memberships WHERE keyword=?", (kw,))
            con.execute("DELETE FROM keywords WHERE keyword=?", (kw,))

    def get_negative_keywords(self) -> list[NegativeKeyword]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM negative_keywords ORDER BY phrase").fetchall()
        return [NegativeKeyword(**dict(r)) for r in rows]

    def save_negative_keyword(self, nk: NegativeKeyword):
        with self.connect() as con:
            con.execute(
                """INSERT INTO negative_keywords VALUES (?,?,?)
                   ON CONFLICT(phrase) DO UPDATE SET
                     enabled=excluded.enabled, notes=excluded.notes""",
                (nk.phrase, nk.enabled, nk.notes),
            )

    def delete_negative_keyword(self, phrase: str):
        with self.connect() as con:
            con.execute("DELETE FROM negative_keywords WHERE phrase=?", (phrase,))

    # ── Domain blacklist ──────────────────────────────────────
    def get_domain_blacklist(self) -> list[DomainBlacklist]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM domain_blacklist ORDER BY domain").fetchall()
        return [DomainBlacklist(**dict(r)) for r in rows]

    def add_domain_blacklist(self, domain: str, reason: str = ""):
        with self.connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO domain_blacklist VALUES (?,?,?)",
                (domain, reason, _now()),
            )

    def delete_domain_blacklist(self, domain: str):
        with self.connect() as con:
            con.execute("DELETE FROM domain_blacklist WHERE domain=?", (domain,))

    # ── Runs ──────────────────────────────────────────────────
    def create_run(self, run: Run):
        with self.connect() as con:
            con.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                (run.run_id, run.started_at, run.finished_at,
                 run.status, run.stats_json, run.error, run.log_path),
            )

    def update_run(self, run: Run):
        with self.connect() as con:
            con.execute(
                """UPDATE runs SET finished_at=?, status=?, stats_json=?,
                   error=?, log_path=? WHERE run_id=?""",
                (run.finished_at, run.status, run.stats_json,
                 run.error, run.log_path, run.run_id),
            )

    def get_runs(self, limit: int = 50) -> list[Run]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Run(**dict(r)) for r in rows]

    def get_run(self, run_id: str) -> Run | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return Run(**dict(r)) if r else None

    # ── Raw items ─────────────────────────────────────────────
    def insert_raw_items(self, items: list[RawItem]):
        with self.connect() as con:
            con.executemany(
                "INSERT INTO raw_items (run_id, actor_name, source, query_used, url, raw_json, fetched_at) VALUES (?,?,?,?,?,?,?)",
                [(i.run_id, i.actor_name, i.source, i.query_used, i.url, i.raw_json, i.fetched_at) for i in items],
            )

    # ── Leads ─────────────────────────────────────────────────
    def upsert_lead(self, lead: Lead):
        with self.connect() as con:
            con.execute(
                """INSERT INTO leads (
                     lead_id, first_seen_at, last_seen_at, source, actor_name,
                     query_used, title, text, url, author,
                     lead_type, rule_score, auto_score, score_reason, agent_json,
                     status, manual_score, manual_feedback, tags_json, is_starred,
                     keyword_group_id, keyword_used, prefilter_result, prefilter_model,
                     prefilter_raw, prefilter_checked_at,
                     enrichment_json, enrichment_provider, scoring_provider
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(lead_id) DO UPDATE SET
                     last_seen_at=excluded.last_seen_at,
                     rule_score=MAX(leads.rule_score, excluded.rule_score),
                     auto_score=CASE WHEN excluded.auto_score>0 THEN excluded.auto_score ELSE leads.auto_score END,
                     score_reason=CASE WHEN excluded.score_reason!='' THEN excluded.score_reason ELSE leads.score_reason END,
                     agent_json=CASE WHEN excluded.agent_json!='' THEN excluded.agent_json ELSE leads.agent_json END,
                     author=CASE WHEN excluded.author!='' THEN excluded.author ELSE leads.author END,
                     lead_type=CASE WHEN excluded.lead_type!='' THEN excluded.lead_type ELSE leads.lead_type END,
                     keyword_group_id=CASE WHEN excluded.keyword_group_id!='' THEN excluded.keyword_group_id ELSE leads.keyword_group_id END,
                     keyword_used=CASE WHEN excluded.keyword_used!='' THEN excluded.keyword_used ELSE leads.keyword_used END,
                     prefilter_result=CASE WHEN excluded.prefilter_result!='' THEN excluded.prefilter_result ELSE leads.prefilter_result END,
                     prefilter_model=CASE WHEN excluded.prefilter_model!='' THEN excluded.prefilter_model ELSE leads.prefilter_model END,
                     prefilter_raw=CASE WHEN excluded.prefilter_raw!='' THEN excluded.prefilter_raw ELSE leads.prefilter_raw END,
                     prefilter_checked_at=CASE WHEN excluded.prefilter_checked_at!='' THEN excluded.prefilter_checked_at ELSE leads.prefilter_checked_at END,
                     enrichment_json=CASE WHEN excluded.enrichment_json!='{}' THEN excluded.enrichment_json ELSE leads.enrichment_json END,
                     enrichment_provider=CASE WHEN excluded.enrichment_provider!='' THEN excluded.enrichment_provider ELSE leads.enrichment_provider END,
                     scoring_provider=CASE WHEN excluded.scoring_provider!='' THEN excluded.scoring_provider ELSE leads.scoring_provider END
                """,
                (lead.lead_id, lead.first_seen_at, lead.last_seen_at,
                 lead.source, lead.actor_name, lead.query_used,
                 lead.title, lead.text, lead.url,
                 lead.author, lead.lead_type, lead.rule_score,
                 lead.auto_score, lead.score_reason, lead.agent_json,
                 lead.status, lead.manual_score, lead.manual_feedback,
                 lead.tags_json, lead.is_starred,
                 lead.keyword_group_id, lead.keyword_used,
                 lead.prefilter_result, lead.prefilter_model,
                 lead.prefilter_raw, lead.prefilter_checked_at,
                 lead.enrichment_json, lead.enrichment_provider,
                 lead.scoring_provider),
            )

    def update_lead_scoring(self, lead_id: str, auto_score: int, score_reason: str,
                            agent_json: str, lead_type: str, author: str):
        with self.connect() as con:
            con.execute(
                """UPDATE leads SET auto_score=?, score_reason=?, agent_json=?,
                   lead_type=?, author=? WHERE lead_id=?""",
                (auto_score, score_reason, agent_json, lead_type, author, lead_id),
            )

    def update_lead_manual(self, lead_id: str, *, status: str | None = None,
                           manual_score: int | None = None, manual_feedback: str | None = None,
                           tags_json: str | None = None, is_starred: int | None = None):
        sets, vals = [], []
        if status is not None:
            sets.append("status=?"); vals.append(status)
        if manual_score is not None:
            sets.append("manual_score=?"); vals.append(manual_score)
        if manual_feedback is not None:
            sets.append("manual_feedback=?"); vals.append(manual_feedback)
        if tags_json is not None:
            sets.append("tags_json=?"); vals.append(tags_json)
        if is_starred is not None:
            sets.append("is_starred=?"); vals.append(is_starred)
        if not sets:
            return
        vals.append(lead_id)
        with self.connect() as con:
            con.execute(f"UPDATE leads SET {', '.join(sets)} WHERE lead_id=?", vals)

    def get_leads(self, *, offset: int = 0, limit: int = 100,
                  status: str | None = None, source: str | None = None,
                  lead_type: str | None = None, actor_name: str | None = None,
                  min_auto_score: int | None = None, max_auto_score: int | None = None,
                  min_manual_score: int | None = None, max_manual_score: int | None = None,
                  is_starred: int | None = None, search: str | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  prefilter_result: str | None = None,
                  order_by: str = "last_seen_at DESC") -> list[Lead]:
        wheres, vals = [], []
        if status:
            wheres.append("status=?"); vals.append(status)
        if source:
            wheres.append("source=?"); vals.append(source)
        if lead_type:
            wheres.append("lead_type=?"); vals.append(lead_type)
        if actor_name:
            wheres.append("actor_name=?"); vals.append(actor_name)
        if prefilter_result:
            wheres.append("prefilter_result=?"); vals.append(prefilter_result)
        if min_auto_score is not None:
            wheres.append("auto_score>=?"); vals.append(min_auto_score)
        if max_auto_score is not None:
            wheres.append("auto_score<=?"); vals.append(max_auto_score)
        if min_manual_score is not None:
            wheres.append("manual_score>=?"); vals.append(min_manual_score)
        if max_manual_score is not None:
            wheres.append("manual_score<=?"); vals.append(max_manual_score)
        if is_starred is not None:
            wheres.append("is_starred=?"); vals.append(is_starred)
        if search:
            wheres.append("(title LIKE ? OR text LIKE ? OR url LIKE ? OR author LIKE ? OR client_name LIKE ?)")
            s = f"%{search}%"
            vals.extend([s, s, s, s, s])
        if date_from:
            wheres.append("last_seen_at>=?"); vals.append(date_from)
        if date_to:
            wheres.append("last_seen_at<=?"); vals.append(date_to)

        where_clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        # Sanitize order_by to prevent injection
        allowed_orders = {
            "last_seen_at DESC", "last_seen_at ASC", "auto_score DESC", "auto_score ASC",
            "manual_score DESC", "manual_score ASC", "rule_score DESC", "rule_score ASC",
            "first_seen_at DESC", "first_seen_at ASC", "title ASC", "title DESC",
        }
        if order_by not in allowed_orders:
            order_by = "last_seen_at DESC"

        q = f"SELECT * FROM leads{where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
        vals.extend([limit, offset])

        with self.connect() as con:
            rows = con.execute(q, vals).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def count_leads(self, **filters) -> int:
        wheres, vals = [], []
        for k, v in filters.items():
            if v is not None:
                wheres.append(f"{k}=?"); vals.append(v)
        where_clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        with self.connect() as con:
            return con.execute(f"SELECT COUNT(*) FROM leads{where_clause}", vals).fetchone()[0]

    def get_lead(self, lead_id: str) -> Lead | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
        return Lead.from_row(dict(r)) if r else None

    def get_lead_stats(self) -> dict:
        with self.connect() as con:
            total = con.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            new = con.execute("SELECT COUNT(*) FROM leads WHERE status='new'").fetchone()[0]
            saved = con.execute("SELECT COUNT(*) FROM leads WHERE status='saved'").fetchone()[0]
            contacted = con.execute("SELECT COUNT(*) FROM leads WHERE status='contacted'").fetchone()[0]
            ignored = con.execute("SELECT COUNT(*) FROM leads WHERE status='ignored'").fetchone()[0]
            starred = con.execute("SELECT COUNT(*) FROM leads WHERE is_starred=1").fetchone()[0]
        return {"total": total, "new": new, "saved": saved,
                "contacted": contacted, "ignored": ignored, "starred": starred}

    def get_unscored_leads(self, limit: int = 50) -> list[Lead]:
        with self.connect() as con:
            rows = con.execute(
                """SELECT * FROM leads WHERE auto_score=0 AND status='new'
                   ORDER BY rule_score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def get_leads_for_learning(self) -> list[Lead]:
        """Leads with manual scores for keyword-weight learning."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM leads WHERE manual_score IS NOT NULL"
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def bulk_update_status(self, lead_ids: list[str], status: str):
        if not lead_ids:
            return
        with self.connect() as con:
            placeholders = ",".join("?" * len(lead_ids))
            con.execute(
                f"UPDATE leads SET status=? WHERE lead_id IN ({placeholders})",
                [status] + lead_ids,
            )

    def bulk_delete_leads(self, lead_ids: list[str]):
        if not lead_ids:
            return
        with self.connect() as con:
            placeholders = ",".join("?" * len(lead_ids))
            con.execute(
                f"DELETE FROM leads WHERE lead_id IN ({placeholders})",
                lead_ids,
            )

    # ── Keyword weight update ─────────────────────────────────
    def update_keyword_stats(self, keyword: str, *, uses_count_delta: int = 0,
                             avg_manual_score: float | None = None):
        sets, vals = [], []
        if uses_count_delta:
            sets.append("uses_count = uses_count + ?"); vals.append(uses_count_delta)
        if avg_manual_score is not None:
            sets.append("avg_manual_score=?"); vals.append(avg_manual_score)
        sets.append("last_used_at=?"); vals.append(_now())
        vals.append(keyword)
        if sets:
            with self.connect() as con:
                con.execute(f"UPDATE keywords SET {', '.join(sets)} WHERE keyword=?", vals)

    # ── Keyword Groups ────────────────────────────────────────
    def get_keyword_groups(self) -> list[KeywordGroup]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM keyword_groups ORDER BY name").fetchall()
        return [KeywordGroup(**dict(r)) for r in rows]

    def get_keyword_group(self, group_id: str) -> KeywordGroup | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM keyword_groups WHERE group_id=?", (group_id,)).fetchone()
        return KeywordGroup(**dict(r)) if r else None

    def save_keyword_group(self, g: KeywordGroup):
        with self.connect() as con:
            con.execute(
                """INSERT INTO keyword_groups
                   (group_id, name, description, prefilter_prompt,
                    prefilter_input_template, analysis_prompt, created_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(group_id) DO UPDATE SET
                     name=excluded.name, description=excluded.description,
                     prefilter_prompt=excluded.prefilter_prompt,
                     prefilter_input_template=excluded.prefilter_input_template,
                     analysis_prompt=excluded.analysis_prompt""",
                (g.group_id, g.name, g.description, g.prefilter_prompt,
                 g.prefilter_input_template, g.analysis_prompt,
                 g.created_at or _now()),
            )

    def delete_keyword_group(self, group_id: str):
        with self.connect() as con:
            # Remove all keyword memberships for this group
            con.execute("DELETE FROM keyword_group_memberships WHERE group_id=?", (group_id,))
            con.execute("DELETE FROM keyword_groups WHERE group_id=?", (group_id,))

    def get_keywords_by_group(self, group_id: str) -> list[Keyword]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT k.keyword, k.status, k.weight, k.added_by, k.last_used_at,
                       k.avg_manual_score, k.uses_count, k.notes,
                       COALESCE(GROUP_CONCAT(m2.group_id), '') AS group_id
                FROM keyword_group_memberships m
                JOIN keywords k ON k.keyword = m.keyword
                LEFT JOIN keyword_group_memberships m2 ON k.keyword = m2.keyword
                WHERE m.group_id = ?
                GROUP BY k.keyword
                ORDER BY k.weight DESC, k.keyword
                """,
                (group_id,),
            ).fetchall()
        return [Keyword(**dict(r)) for r in rows]

    def get_keywords_not_in_group(self, group_id: str, status: str | None = None) -> list[Keyword]:
        """Return active keywords that are NOT yet assigned to the given group."""
        base = """
            SELECT k.keyword, k.status, k.weight, k.added_by, k.last_used_at,
                   k.avg_manual_score, k.uses_count, k.notes,
                   COALESCE(GROUP_CONCAT(m.group_id), '') AS group_id
            FROM keywords k
            LEFT JOIN keyword_group_memberships m ON k.keyword = m.keyword
            WHERE k.keyword NOT IN (
                SELECT keyword FROM keyword_group_memberships WHERE group_id = ?
            )
        """
        with self.connect() as con:
            if status:
                rows = con.execute(
                    base + "AND k.status=? GROUP BY k.keyword ORDER BY k.weight DESC, k.keyword",
                    (group_id, status)
                ).fetchall()
            else:
                rows = con.execute(
                    base + "GROUP BY k.keyword ORDER BY k.weight DESC, k.keyword",
                    (group_id,)
                ).fetchall()
        return [Keyword(**dict(r)) for r in rows]

    def get_keyword_uses_in_group(self, keyword: str, group_id: str) -> int:
        """Count how many times a keyword was used in a specific group."""
        with self.connect() as con:
            row = con.execute(
                "SELECT COUNT(*) as count FROM leads WHERE keyword_used=? AND keyword_group_id=?",
                (keyword, group_id),
            ).fetchone()
        return row[0] if row else 0

    def get_keyword_last_run_in_group(self, keyword: str, group_id: str) -> str:
        """Get the last run date of a keyword in a specific group (yyyy-mm-dd)."""
        with self.connect() as con:
            row = con.execute(
                "SELECT MAX(last_seen_at) FROM leads WHERE keyword_used=? AND keyword_group_id=?",
                (keyword, group_id),
            ).fetchone()
        if row and row[0]:
            return row[0][:10]
        return ""

    def move_keyword_to_group(self, keyword: str, group_id: str):
        """Add a keyword to a group (many-to-many). Pass group_id='' to remove from all groups."""
        with self.connect() as con:
            if group_id:
                con.execute(
                    "INSERT OR IGNORE INTO keyword_group_memberships (keyword, group_id) VALUES (?,?)",
                    (keyword, group_id),
                )
            else:
                con.execute(
                    "DELETE FROM keyword_group_memberships WHERE keyword=?",
                    (keyword,),
                )

    def remove_keyword_from_group(self, keyword: str, group_id: str):
        """Remove a keyword from a specific group only."""
        with self.connect() as con:
            con.execute(
                "DELETE FROM keyword_group_memberships WHERE keyword=? AND group_id=?",
                (keyword, group_id),
            )

    def bulk_update_keyword_status(self, keywords: list[str], status: str):
        """Update the status of multiple keywords at once."""
        with self.connect() as con:
            con.executemany(
                "UPDATE keywords SET status=? WHERE keyword=?",
                [(status, kw) for kw in keywords],
            )

    def bulk_move_keywords_to_group(self, keywords: list[str], group_id: str):
        """Add multiple keywords to a group at once (many-to-many, no removal)."""
        with self.connect() as con:
            con.executemany(
                "INSERT OR IGNORE INTO keyword_group_memberships (keyword, group_id) VALUES (?,?)",
                [(kw, group_id) for kw in keywords],
            )

    # ── Prompt Templates ──────────────────────────────────────
    def get_prompt_template(self, template_id: str) -> PromptTemplate | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)).fetchone()
        return PromptTemplate(**dict(r)) if r else None

    def get_prompt_templates(self) -> list[PromptTemplate]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM prompt_templates ORDER BY template_id").fetchall()
        return [PromptTemplate(**dict(r)) for r in rows]

    def save_prompt_template(self, pt: PromptTemplate):
        with self.connect() as con:
            con.execute(
                """INSERT INTO prompt_templates VALUES (?,?,?,?)
                   ON CONFLICT(template_id) DO UPDATE SET
                     template_text=excluded.template_text,
                     description=excluded.description,
                     updated_at=excluded.updated_at""",
                (pt.template_id, pt.template_text, pt.description, _now()),
            )

    # ── Enrichment Cache ──────────────────────────────────────
    def add_enrichment_cache(self, lead_id: str, query: str, result_json: str, source_url: str = ""):
        with self.connect() as con:
            con.execute(
                "INSERT INTO enrichment_cache (lead_id, query, result_json, source_url, fetched_at) VALUES (?,?,?,?,?)",
                (lead_id, query, result_json, source_url, _now()),
            )

    def get_enrichment_cache(self, lead_id: str) -> list[EnrichmentCache]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM enrichment_cache WHERE lead_id=? ORDER BY fetched_at DESC",
                (lead_id,),
            ).fetchall()
        return [EnrichmentCache(**dict(r)) for r in rows]

    # ── Lead enrichment/scoring updates ───────────────────────
    def update_lead_enrichment(self, lead_id: str, enrichment_json: str, enrichment_provider: str):
        with self.connect() as con:
            con.execute(
                "UPDATE leads SET enrichment_json=?, enrichment_provider=? WHERE lead_id=?",
                (enrichment_json, enrichment_provider, lead_id),
            )

    def update_lead_prefilter(self, lead_id: str, prefilter_result: str,
                              prefilter_model: str, prefilter_raw: str = ""):
        with self.connect() as con:
            con.execute(
                """UPDATE leads SET prefilter_result=?, prefilter_model=?,
                   prefilter_raw=?, prefilter_checked_at=? WHERE lead_id=?""",
                (prefilter_result, prefilter_model, prefilter_raw,
                 _now(), lead_id),
            )

    def update_lead_scoring_v2(self, lead_id: str, auto_score: int, score_reason: str,
                               agent_json: str, lead_type: str, author: str,
                               scoring_provider: str, client_name: str = ""):
        with self.connect() as con:
            con.execute(
                """UPDATE leads SET auto_score=?, score_reason=?, agent_json=?,
                   lead_type=?, author=?, scoring_provider=?, client_name=? WHERE lead_id=?""",
                (auto_score, score_reason, agent_json, lead_type, author,
                 scoring_provider, client_name, lead_id),
            )

    def update_lead_analysis(self, lead_id: str, auto_score: float,
                             score_reason: str, agent_json: str,
                             lead_type: str, author: str,
                             enrichment_json: str, enrichment_provider: str,
                             scoring_provider: str, client_name: str = ""):
        """Update a lead with merged analysis results (scoring + enrichment)."""
        with self.connect() as con:
            con.execute(
                """UPDATE leads SET auto_score=?, score_reason=?, agent_json=?,
                   lead_type=?, author=?, client_name=?,
                   enrichment_json=?, enrichment_provider=?,
                   scoring_provider=? WHERE lead_id=?""",
                (auto_score, score_reason, agent_json, lead_type, author, client_name,
                 enrichment_json, enrichment_provider, scoring_provider, lead_id),
            )

    def get_scored_leads_for_context(self, limit: int = 20) -> list[Lead]:
        """Get high-quality scored leads to use as context for scoring."""
        with self.connect() as con:
            rows = con.execute(
                """SELECT * FROM leads WHERE auto_score >= 6
                   ORDER BY auto_score DESC, last_seen_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def get_leads_needing_enrichment(self, limit: int = 50) -> list[Lead]:
        """Leads that passed prefilter but have no enrichment."""
        with self.connect() as con:
            rows = con.execute(
                """SELECT * FROM leads WHERE prefilter_result='Yes'
                   AND enrichment_json='{}' AND status='new'
                   ORDER BY rule_score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    # ── Clients ───────────────────────────────────────────────
    def insert_client_manual(self, name: str, domain: str, notes: str, contact: str = "", tag: str = "") -> Client:
        """Insert a manually-created client record. Returns the new Client."""
        import hashlib
        now = _now()
        client_id = "manual_" + hashlib.md5((name + domain).encode()).hexdigest()[:12]
        with self.connect() as con:
            con.execute(
                """INSERT OR IGNORE INTO clients
                   (client_id, name, domain, contact, lead_count, lead_ids_json,
                    created_at, updated_at, client_score, client_reason,
                    revenue_scale, introduction, client_analyzed_at, notes, tag)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (client_id, name, domain, contact, 0, "[]",
                 now, now, 0, "", "", "", "", notes, tag),
            )
        return self.get_client(client_id)

    def upsert_client(self, client: Client):
        """Insert or update a client record, merging lead_ids."""
        now = _now()
        with self.connect() as con:
            existing = con.execute(
                "SELECT * FROM clients WHERE client_id=?", (client.client_id,)
            ).fetchone()
            if existing:
                old = Client(**dict(existing))
                merged_ids = list(set(old.lead_ids + client.lead_ids))
                con.execute(
                    """UPDATE clients SET domain=CASE WHEN ?!='' THEN ? ELSE domain END,
                       contact=CASE WHEN ?!='' THEN ? ELSE contact END,
                       lead_count=?, lead_ids_json=?, updated_at=?
                       WHERE client_id=?""",
                    (client.domain, client.domain,
                     client.contact, client.contact,
                     len(merged_ids), json.dumps(merged_ids), now,
                     client.client_id),
                )
            else:
                con.execute(
                    """INSERT INTO clients (client_id, name, domain, contact,
                       lead_count, lead_ids_json, created_at, updated_at,
                       client_score, client_reason, revenue_scale, introduction, client_analyzed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (client.client_id, client.name, client.domain,
                     client.contact, client.lead_count,
                     client.lead_ids_json, now, now,
                     client.client_score, client.client_reason,
                     client.revenue_scale, client.introduction,
                     client.client_analyzed_at),
                )

    def get_clients(self, *, search: str | None = None,
                    min_score: int = 0, min_leads: int = 0,
                    starred: bool | None = None,
                    contacted: bool | None = None,
                    order_by: str = "lead_count DESC",
                    limit: int = 200, offset: int = 0) -> list[Client]:
        wheres, vals = [], []
        if search:
            wheres.append("(name LIKE ? OR domain LIKE ? OR contact LIKE ?)")
            s = f"%{search}%"
            vals.extend([s, s, s])
        if min_score > 0:
            wheres.append("client_score >= ?")
            vals.append(min_score)
        if min_leads > 0:
            wheres.append("lead_count >= ?")
            vals.append(min_leads)
        if starred is not None:
            wheres.append("starred = ?")
            vals.append(1 if starred else 0)
        if contacted is not None:
            wheres.append("contacted = ?")
            vals.append(1 if contacted else 0)
        where_clause = (" WHERE " + " AND ".join(wheres)) if wheres else ""
        allowed = {"lead_count DESC", "lead_count ASC", "name ASC", "name DESC",
                   "updated_at DESC", "updated_at ASC",
                   "created_at DESC", "created_at ASC",
                   "client_score DESC", "client_score ASC",
                   "domain ASC", "domain DESC",
                   "contact ASC", "contact DESC",
                   "starred ASC", "starred DESC",
                   "contacted ASC", "contacted DESC"}
        if order_by not in allowed:
            order_by = "lead_count DESC"
        q = f"SELECT * FROM clients{where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
        vals.extend([limit, offset])
        with self.connect() as con:
            rows = con.execute(q, vals).fetchall()
        return [Client(**dict(r)) for r in rows]

    def count_clients(self) -> int:
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) FROM clients").fetchone()[0]

    def get_client(self, client_id: str) -> Client | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM clients WHERE client_id=?", (client_id,)).fetchone()
        return Client(**dict(r)) if r else None

    def delete_client(self, client_id: str):
        with self.connect() as con:
            con.execute("DELETE FROM clients WHERE client_id=?", (client_id,))

    def bulk_delete_clients(self, client_ids: list[str]):
        if not client_ids:
            return
        with self.connect() as con:
            placeholders = ",".join("?" * len(client_ids))
            con.execute(
                f"DELETE FROM clients WHERE client_id IN ({placeholders})",
                client_ids,
            )

    def update_client_analysis(self, client_id: str, score: int, reason: str,
                               revenue_scale: str, introduction: str,
                               contact: str = "", tag: str = ""):
        """Update client analysis fields. Only updates contact/tag if non-empty."""
        now = _now()
        with self.connect() as con:
            sets = "client_score=?, client_reason=?, revenue_scale=?, introduction=?, client_analyzed_at=?, updated_at=?"
            vals = [score, reason, revenue_scale, introduction, now, now]
            if contact:
                sets += ", contact=?"
                vals.append(contact)
            if tag:
                sets += ", tag=?"
                vals.append(tag)
            vals.append(client_id)
            con.execute(f"UPDATE clients SET {sets} WHERE client_id=?", vals)

    def toggle_client_starred(self, client_id: str, starred: bool):
        """Toggle starred status for a client."""
        now = _now()
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET starred=?, updated_at=? WHERE client_id=?",
                (1 if starred else 0, now, client_id),
            )

    def toggle_client_contacted(self, client_id: str, contacted: bool):
        """Toggle contacted status for a client."""
        now = _now()
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET contacted=?, updated_at=? WHERE client_id=?",
                (1 if contacted else 0, now, client_id),
            )

    def update_client_info(self, client_id: str, name: str, domain: str, contact: str, tag: str = ""):
        """Update basic info fields of a client."""
        now = _now()
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET name=?, domain=?, contact=?, tag=?, updated_at=? WHERE client_id=?",
                (name, domain, contact, tag, now, client_id),
            )

    def update_client_notes(self, client_id: str, notes: str):
        """Save manual notes for a client."""
        now = _now()
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET notes=?, updated_at=? WHERE client_id=?",
                (notes, now, client_id),
            )

    def update_client_row_color(self, client_id: str, color: str):
        """Update the row color for a client."""
        now = _now()
        with self.connect() as con:
            con.execute(
                "UPDATE clients SET row_color=?, updated_at=? WHERE client_id=?",
                (color, now, client_id),
            )

    def bulk_update_client_colors(self, client_ids: list[str], color: str):
        """Bulk update row colors for multiple clients."""
        if not client_ids:
            return
        now = _now()
        with self.connect() as con:
            placeholders = ",".join("?" * len(client_ids))
            con.execute(
                f"UPDATE clients SET row_color=?, updated_at=? WHERE client_id IN ({placeholders})",
                [color, now] + client_ids,
            )

    def count_clients_by_status(self) -> dict[str, int]:
        """Get counts of total, starred, and contacted clients."""
        with self.connect() as con:
            total = con.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
            starred = con.execute("SELECT COUNT(*) FROM clients WHERE starred=1").fetchone()[0]
            contacted = con.execute("SELECT COUNT(*) FROM clients WHERE contacted=1").fetchone()[0]
        return {"total": total, "starred": starred, "contacted": contacted}

    def get_clients_for_analysis(self, limit: int = 50) -> list[Client]:
        """Get clients that have not been analyzed yet."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM clients WHERE client_analyzed_at='' OR client_analyzed_at IS NULL "
                "ORDER BY lead_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Client.from_row(dict(r)) for r in rows]

    def get_leads_for_prefilter(self, limit: int = 99999999) -> list[Lead]:
        """Get leads that have not been prefiltered yet."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM leads "
                "WHERE status='new' "
                "AND (prefilter_result='' OR prefilter_result IS NULL) "
                "ORDER BY rule_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]

    def get_leads_for_analysis(self, limit: int = 99999999) -> list[Lead]:
        """Get leads that passed prefilter but have not been analyzed yet."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM leads "
                "WHERE prefilter_result='Yes' "
                "AND (scoring_provider='' OR scoring_provider IS NULL) "
                "ORDER BY rule_score DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Lead.from_row(dict(r)) for r in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
