"""GroupPrefilterStage – local LLM Yes/No filtering per keyword group."""
from __future__ import annotations

import logging
from typing import Any

from ...core.db import DatabaseManager
from ...core.models import Lead
from . import PipelineStage

log = logging.getLogger(__name__)

DEFAULT_PREFILTER_PROMPT = (
    "You are an expert lead-qualification agent for a 3D animation outsourcing studio. "
    "Your studio provides: game cinematics, brand mascot animation, animated commercials, "
    "product animation, and CGI content, animation feature film, animation IP, animation series, "
    "game trailer. Is the information below have a chance to be a lead? Answer Yes or No only."
)

DEFAULT_INPUT_TEMPLATE = "{lead.text}\nTitle: {lead.title}\nAuthor: {lead.author}"


def render_prefilter_input(lead: Lead, template: str) -> str:
    """Render a prefilter input template with lead fields."""
    return (template
            .replace("{lead.text}", lead.text or "")
            .replace("{lead.title}", lead.title or "")
            .replace("{lead.author}", lead.author or ""))


class GroupPrefilterStage(PipelineStage):
    name = "group_prefilter"

    def __init__(self, db: DatabaseManager, mock: bool = False):
        self._db = db
        self._mock = mock

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        cancel = ctx.get("cancel_event")
        emit = ctx.get("emit", lambda m, p: None)
        stats = ctx["stats"]

        # Get ALL leads that haven't been prefiltered yet
        unfiltered = self._db.get_leads_for_prefilter(limit=5000)
        if not unfiltered:
            emit("No leads to prefilter", 68)
            return ctx

        emit(f"Group prefilter on {len(unfiltered)} leads…", 65)

        # Load groups
        groups = {g.group_id: g for g in self._db.get_keyword_groups()}

        # Get prefilter provider (now flexible via provider manager)
        from ..provider_manager import ProviderManager
        pm = ProviderManager(self._db, mock=self._mock)
        provider, provider_name = pm.get_provider_for_stage("prefilter")
        model_name = "mock" if self._mock else (provider.config.get("http_model", "local") if provider else "rule")

        passed = 0
        rejected = 0
        errors = 0
        total = len(unfiltered)
        for i, lead in enumerate(unfiltered):
            if cancel and cancel.is_set():
                break

            # Emit progress every lead
            done = i + 1
            pct = 50 + int(20 * done / total)  # 50-70% range
            emit(f"Prefilter: {done}/{total} (✓{passed} ✗{rejected})", pct)

            group = groups.get(lead.keyword_group_id)
            prompt = (group.prefilter_prompt if group and group.prefilter_prompt
                      else DEFAULT_PREFILTER_PROMPT)

            input_template = (group.prefilter_input_template if group and group.prefilter_input_template
                              else DEFAULT_INPUT_TEMPLATE)
            content = render_prefilter_input(lead, input_template)

            if provider:
                try:
                    result, raw = provider.prefilter(content, prompt)
                except RuntimeError as e:
                    # Provider giving up (e.g. max retries hit) – stop prefiltering
                    log.error("Prefilter stage aborted: %s", e)
                    stats["errors"].append(f"prefilter aborted: {e}")
                    break
            elif self._mock:
                import random
                result = random.choice(["Yes", "No"])
                raw = f"mock: {result}"
            else:
                # Fallback: rule-based (accept if rule_score > 5)
                result = "Yes" if lead.rule_score > 5 else "No"
                raw = f"rule-based: rule_score={lead.rule_score}"

            self._db.update_lead_prefilter(
                lead.lead_id, result, model_name, prefilter_raw=raw,
            )

            if result == "Yes":
                passed += 1
            else:
                rejected += 1

        stats["prefilter_passed"] = passed
        stats["prefilter_rejected"] = rejected
        stats["prefilter_errors"] = errors
        emit(f"Prefilter: {passed} passed, {rejected} rejected, {errors} errors", 70)
        return ctx
