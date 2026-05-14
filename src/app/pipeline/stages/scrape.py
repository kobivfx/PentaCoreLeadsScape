"""ScrapeStage – run Apify actors, collect raw items, map to candidates."""
from __future__ import annotations

import json
import logging
import random
from typing import Any

from ...core.db import DatabaseManager, _now
from ...core.models import Actor, Keyword, LeadCandidate, RawItem
from ...core.secrets_manager import SecretsManager
from ..apify_runner import ApifyRunner
from ..mapping import map_raw_item
from . import PipelineStage

log = logging.getLogger(__name__)


class ScrapeStage(PipelineStage):
    name = "scrape"

    def __init__(self, db: DatabaseManager, secrets: SecretsManager,
                 mock: bool = False, dry_run: bool = False):
        self._db = db
        self._secrets = secrets
        self._mock = mock
        self._dry_run = dry_run

    @staticmethod
    def _parse_extraction_path(path_expr: str) -> list[str]:
        """Parse a path like 'raw_items["organicResults"]["a"]' into key list.
        
        Returns list of keys, e.g. ["organicResults", "a"].
        Returns empty list for bare 'raw_items'.
        """
        path_expr = path_expr.strip()
        if not path_expr:
            return []
        # Remove 'raw_items' prefix
        if path_expr.startswith("raw_items"):
            path_expr = path_expr[len("raw_items"):]
        if not path_expr:
            return []
        # Parse bracket notation: ["key1"]["key2"] or ['key1']['key2']
        keys = []
        remaining = path_expr
        while remaining:
            remaining = remaining.strip()
            if not remaining:
                break
            if remaining[0] != "[":
                break
            close = remaining.find("]")
            if close < 0:
                break
            inner = remaining[1:close].strip()
            # Strip quotes
            if (inner.startswith('"') and inner.endswith('"')) or \
               (inner.startswith("'") and inner.endswith("'")):
                inner = inner[1:-1]
            keys.append(inner)
            remaining = remaining[close + 1:]
        return keys

    @staticmethod
    def _extract_by_path(item: dict, keys: list[str]) -> list[dict]:
        """Navigate into a dict using a list of keys and return items.
        
        Returns list of dicts found at the path. Handles:
        - Missing keys (returns [])
        - Non-dict intermediates (returns [])
        - Final value is a list of dicts (returns that list)
        - Final value is a single dict (returns [dict])
        """
        current = item
        for key in keys:
            if not isinstance(current, dict):
                return []
            current = current.get(key)
            if current is None:
                return []
        if isinstance(current, list):
            return [x for x in current if isinstance(x, dict)]
        if isinstance(current, dict):
            return [current]
        return []

    @staticmethod
    def apply_extraction_rules(raw_items: list[dict], rules_text: str) -> list[dict]:
        """Apply extraction rules to raw items.
        
        Rules format (one per line):
            raw_items                         → use top-level items as-is
            raw_items["organicResults"]        → extract from nested field
            raw_items["organicResults"]["a"]   → deeper nesting
        
        Multiple lines combine results from all paths.
        Empty/blank rules default to raw_items (top-level).
        """
        if not rules_text or not rules_text.strip():
            return raw_items
        
        lines = [l.strip() for l in rules_text.strip().splitlines() if l.strip()]
        if not lines:
            return raw_items
        
        # Check if all lines are just "raw_items" (default behavior)
        if all(l == "raw_items" for l in lines):
            return raw_items
        
        extracted = []
        for line in lines:
            keys = ScrapeStage._parse_extraction_path(line)
            if not keys:
                # Bare "raw_items" → use top-level items
                extracted.extend(raw_items)
            else:
                for item in raw_items:
                    try:
                        nested = ScrapeStage._extract_by_path(item, keys)
                        extracted.extend(nested)
                    except Exception as e:
                        log.warning("Extraction rule '%s' failed on item: %s", line, e)
        return extracted

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]
        group_ids = ctx.get("group_ids", ["all"])

        # Get Apify tokens (supports multiple with fallback)
        apify_tokens = self._secrets.get_apify_tokens()
        if not apify_tokens and not self._mock and not self._dry_run:
            raise RuntimeError("No Apify API tokens configured")

        runner = ApifyRunner(tokens=apify_tokens or [""], mock=self._mock or self._dry_run)

        # Load all keyword groups
        all_groups = self._db.get_keyword_groups()
        if not all_groups:
            raise RuntimeError("No keyword groups configured")

        # Filter to selected groups
        if group_ids != ["all"]:
            group_id_set = set(group_ids)
            groups = [g for g in all_groups if g.group_id in group_id_set]
            if not groups:
                raise RuntimeError(f"Selected groups not found: {group_ids}")
        else:
            groups = all_groups

        # Load all enabled actors
        all_actors = self._db.get_actors(enabled_only=True)
        if not all_actors:
            raise RuntimeError("No enabled actors configured")

        all_candidates: list[LeadCandidate] = []
        run_id = ctx["run_id"]

        total_steps = len(groups)
        for g_idx, group in enumerate(groups):
            if cancel and cancel.is_set():
                break

            # Find actors assigned to this group
            actors_for_group = [a for a in all_actors if group.group_id in a.allowed_groups]
            if not actors_for_group:
                log.warning("No actors assigned to group %s (%s)", group.group_id, group.name)
                continue

            # Get keywords for this group
            keywords = self._db.get_keywords_by_group(group.group_id)
            keywords = [kw for kw in keywords if kw.status == "active"]
            if not keywords:
                log.warning("No active keywords in group %s (%s)", group.group_id, group.name)
                continue

            for a_idx, actor in enumerate(actors_for_group):
                if cancel and cancel.is_set():
                    break
                pct = 10 + int(50 * (g_idx / total_steps + a_idx / (len(actors_for_group) * total_steps)))
                emit(f"Group '{group.name}' → Actor: {actor.actor_name} ({g_idx+1}/{total_steps})", pct)

                try:
                    candidates = self._run_actor(runner, actor, keywords, run_id, stats, group.group_id)
                    all_candidates.extend(candidates)
                except Exception as e:
                    log.error("Actor %s failed for group %s: %s", actor.actor_name, group.group_id, e)
                    stats["errors"].append(f"{actor.actor_name}@{group.group_id}: {e}")

        runner.close()
        ctx["candidates"] = all_candidates
        return ctx

    def _run_actor(self, runner: ApifyRunner, actor: Actor,
                   keywords: list[Keyword], run_id: str, stats: dict,
                   group_id: str = "") -> list[LeadCandidate]:
        queries = self._build_queries(actor, keywords)
        # Load per-actor-group variables
        actor_vars = self._db.get_actor_group_vars(actor.actor_name, group_id) if group_id else None
        candidates = []
        for query_info in queries:
            query = query_info["query"]
            kw_obj = query_info["keyword"]
            input_data = self._build_input(actor, query, actor_vars)
            raw_items = runner.run_actor(actor.actor_id, input_data)

            # Store raw items before extraction (full API response)
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
                self._db.insert_raw_items(db_items)

            # Apply extraction rules to get the actual items to map
            extracted_items = self.apply_extraction_rules(raw_items, actor.extraction_rules)
            stats["raw_items"] += len(extracted_items)

            mapping = actor.output_mapping
            for item in extracted_items:
                cand = map_raw_item(item, mapping, actor.actor_name, actor.source, query)
                if cand:
                    cand.keyword_group_id = kw_obj.group_id
                    cand.keyword_used = kw_obj.keyword
                    candidates.append(cand)
        return candidates

    def _build_queries(self, actor: Actor, keywords: list[Keyword]) -> list[dict]:
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

        result = []
        for kw in selected:
            q = template.replace("{keyword}", kw.keyword)
            result.append({"query": q, "keyword": kw})
            self._db.update_keyword_stats(kw.keyword, uses_count_delta=1)
        return result

    def _build_input(self, actor: Actor, query: str, actor_vars=None) -> dict:
        """Build input data with smart placeholder replacement.
        
        Placeholders in quotes like "{maxresults}" are replaced intelligently:
        - Numeric placeholders (maxresults, timelimit) → actual number (no quotes)
        - String placeholders (region) → quoted string
        """
        template = actor.input_template
        
        # Define which placeholders are numeric (will be unquoted in JSON)
        numeric_placeholders = {"maxresults", "timelimit", "keywords"}
        
        # Get values
        maxresults_val = actor_vars.maxresults if actor_vars else 10
        region_val = actor_vars.region if actor_vars else "us"
        timelimit_val = actor_vars.timelimit if actor_vars else "3"
        
        # Convert to JSON string, replace with placeholders, then parse back
        template_json = json.dumps(template, default=str)
        
        # Replace numeric placeholders: "{maxresults}" → 10 (unquoted)
        template_json = template_json.replace('"{maxresults}"', str(maxresults_val))
        template_json = template_json.replace('"{timelimit}"', str(timelimit_val))
        template_json = template_json.replace('"{keywords}"', json.dumps(query))  # Re-quote for JSON safety
        
        # Replace string placeholders: "{region}" stays as "us" (quoted)
        template_json = template_json.replace('"{region}"', json.dumps(region_val))
        
        # Parse back to dict
        try:
            input_data = json.loads(template_json)
        except json.JSONDecodeError as e:
            log.error("Failed to parse input template after placeholder replacement: %s", e)
            # Fallback: return original template
            input_data = template
        
        return input_data
