"""Provider manager – handles flexible provider selection for different pipeline stages."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.db import DatabaseManager

log = logging.getLogger(__name__)


class ProviderManager:
    """
    Manages provider selection for different pipeline stages.
    
    Allows configuration of which provider to use for:
    - prefilter: Initial Yes/No filtering
    - scoring: Lead scoring and evaluation
    - enrichment: Data enrichment
    
    Features:
    - Per-stage provider override via config
    - Provider fallback chain
    - Mock mode support
    """

    def __init__(self, db: DatabaseManager, mock: bool = False):
        self.db = db
        self.mock = mock
        self._provider_cache = {}

    def get_provider(self, stage: str):
        """
        Get the provider for a specific stage.
        
        Args:
            stage: One of 'prefilter', 'scoring', 'enrichment'
            
        Returns:
            Provider instance or None if not available
            
        Raises:
            RuntimeError: If configuration is invalid
        """
        # Check for stage-specific override in config
        stage_config = self.db.get_setting(f"provider_{stage}", {})
        provider_id = stage_config.get("provider_id")

        if not provider_id:
            # Use default provider for stage
            provider_id = self._get_default_provider_for_stage(stage)

        if not provider_id:
            log.warning("No provider configured for stage: %s", stage)
            return None

        # Check cache
        cache_key = f"{stage}:{provider_id}"
        if cache_key in self._provider_cache:
            return self._provider_cache[cache_key]

        # Load provider
        try:
            provider = self._load_provider(provider_id)
            if provider:
                self._provider_cache[cache_key] = provider
            return provider
        except Exception as e:
            log.error("Failed to load provider %s for stage %s: %s", provider_id, stage, e)
            return None

    def get_provider_for_stage(self, stage: str) -> tuple:
        """
        Get provider and its name for a specific stage.
        
        Returns:
            (provider_instance, provider_name) or (None, "none")
        """
        provider = self.get_provider(stage)
        if not provider:
            return None, "none"

        # Try to get configured provider name
        stage_config = self.db.get_setting(f"provider_{stage}", {})
        provider_id = stage_config.get("provider_id") or self._get_default_provider_for_stage(stage)

        return provider, provider_id

    def get_provider_name_for_stage(self, stage: str) -> str:
        """Return the provider ID for a stage WITHOUT instantiating it."""
        stage_config = self.db.get_setting(f"provider_{stage}", {})
        provider_id = stage_config.get("provider_id") if isinstance(stage_config, dict) else None
        if not provider_id:
            provider_id = self._get_default_provider_for_stage(stage)
        if not provider_id:
            return "none"
        p = self.db.get_provider(provider_id)
        return provider_id if p and p.enabled else "none"

    def invalidate_cache(self):
        """Clear provider cache (call when settings change)."""
        self._provider_cache.clear()

    # -- Private methods ---

    # Provider IDs that are local LLM providers (no API key needed)
    _LOCAL_PROVIDERS = ("local_llm", "qwen")

    # Provider IDs that support API-based access (have API key)
    _API_PROVIDERS = ("deepseek",)

    def _get_default_provider_for_stage(self, stage: str) -> str | None:
        """Get the default provider for a stage if not explicitly configured.

        For prefilter: tries local providers first.
        For analysis: tries DeepSeek first, then local providers.
        Falls back to None when nothing is available.
        """
        if stage not in ("prefilter", "scoring", "enrichment", "analysis"):
            return None

        if stage == "analysis":
            # Prefer API providers (DeepSeek) for analysis, then local
            for pid in (*self._API_PROVIDERS, *self._LOCAL_PROVIDERS):
                p = self.db.get_provider(pid)
                if p and p.enabled:
                    return pid
            return None

        # prefilter / scoring / enrichment → prefer local providers
        for pid in self._LOCAL_PROVIDERS:
            p = self.db.get_provider(pid)
            if p and p.enabled:
                return pid
        return None

    def _load_provider(self, provider_id: str):
        """Load and instantiate a provider."""
        from ..providers import get_provider_instance
        from ..core.secrets_manager import SecretsManager

        # Get provider config from DB
        provider_data = self.db.get_provider(provider_id)
        if not provider_data or not provider_data.enabled:
            return None

        # Get API key if needed
        secrets = SecretsManager(self.db.db_path)
        api_key = ""
        if provider_data.secret_key_name:
            api_key = secrets.get_secret(provider_data.secret_key_name) or ""

        # Instantiate provider
        return get_provider_instance(
            provider_id,
            api_key=api_key,
            config=provider_data.config,
            mock=self.mock,
        )

    def configure_stage_provider(self, stage: str, provider_id: str, config: dict | None = None):
        """
        Configure a specific provider for a stage.
        
        Args:
            stage: One of 'prefilter', 'scoring', 'enrichment'
            provider_id: Provider ID to use for this stage
            config: Optional stage-specific configuration
            
        Raises:
            ValueError: If provider_id is invalid
        """
        from ..providers import list_provider_ids

        available = list_provider_ids()
        if provider_id not in available:
            raise ValueError(f"Unknown provider: {provider_id}. Available: {available}")

        stage_config = {
            "provider_id": provider_id,
        }
        if config:
            stage_config.update(config)

        self.db.set_setting(f"provider_{stage}", stage_config)
        self.invalidate_cache()
        log.info("Configured %s stage to use %s provider", stage, provider_id)

    def get_stage_config(self, stage: str) -> dict:
        """Get the current configuration for a stage."""
        return self.db.get_setting(f"provider_{stage}", {})

    def reset_stage_to_default(self, stage: str):
        """Reset a stage's provider to the default for that stage."""
        self.db.set_setting(f"provider_{stage}", {})
        self.invalidate_cache()
        log.info("Reset %s stage to default provider", stage)
