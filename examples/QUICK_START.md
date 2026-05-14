# Integration Validation & Quick Start

## What You Can Do Now

### 1. Basic Setup (5 minutes)

```python
from app.core.db import DatabaseManager
from app.pipeline.provider_manager import ProviderManager

db = DatabaseManager()
pm = ProviderManager(db)

# Configure Qwen for prefiltering
pm.configure_stage_provider("prefilter", "qwen")

print("✅ Qwen configured for prefiltering!")
```

### 2. Configure Different Providers Per Stage (5 minutes)

```python
# Recommended: Qwen for fast prefilter, Gemma for thorough scoring
pm.configure_stage_provider("prefilter", "qwen")      # Fast
pm.configure_stage_provider("scoring", "local_llm")   # Thorough
pm.configure_stage_provider("enrichment", "local_llm")  # Thorough

print("✅ Mixed provider strategy configured!")
```

### 3. Test Provider Retrieval (2 minutes)

```python
for stage in ["prefilter", "scoring", "enrichment"]:
    provider, provider_id = pm.get_provider_for_stage(stage)
    status = "✅" if provider else "⚠️"
    print(f"{status} {stage}: {provider_id}")
```

## File Structure

```
LeadsScraper2/
├── src/app/providers/
│   ├── qwen_provider.py ..................... ✨ NEW: Qwen provider
│   ├── __init__.py .......................... UPDATED: Qwen registered
│   ├── base.py
│   ├── local_provider.py
│   └── [other providers]
│
├── src/app/pipeline/
│   ├── provider_manager.py ................. ✨ NEW: Provider selection system
│   ├── stages/
│   │   ├── group_prefilter.py .............. UPDATED: Uses ProviderManager
│   │   ├── scoring.py ...................... UPDATED: Uses ProviderManager
│   │   ├── enrichment.py ................... UPDATED: Uses ProviderManager
│   │   └── [other stages]
│   └── [other pipeline files]
│
├── PROVIDER_CONFIG.md ...................... ✨ NEW: Configuration guide
├── QWEN_INTEGRATION_SUMMARY.md ............ ✨ NEW: Complete summary
├── examples/
│   └── setup_qwen_provider.py .............. ✨ NEW: Example setup script
│
└── [other files unchanged]
```

## Key Integration Points

### 1. Provider Manager in Pipeline Stages

GroupPrefilterStage now does:
```python
from app.pipeline.provider_manager import ProviderManager

pm = ProviderManager(self._db, mock=self._mock)
provider, provider_name = pm.get_provider_for_stage("prefilter")

# Use whichever provider was configured (could be qwen, local_llm, etc.)
if provider:
    result, raw = provider.prefilter(content, prompt)
```

### 2. Database Configuration

Settings stored as:
```python
# Example database entries
db.set_setting("provider_prefilter", {"provider_id": "qwen"})
db.set_setting("provider_scoring", {"provider_id": "local_llm"})
db.set_setting("provider_enrichment", {"provider_id": "gemini"})
```

### 3. Provider Interface (Consistent Across All Providers)

```python
# All local providers implement these methods:
provider.prefilter(text, prompt) -> tuple[str, str]     # (Yes/No, raw_output)
provider.score_candidate(candidate, context) -> AgentResult
provider.enrich(prompt) -> str
provider.generate(prompt) -> str
provider.validate_config() -> str | None
```

## Backward Compatibility

✅ **Existing code continues to work unchanged**

```python
# Old way (still works - defaults to local_llm)
provider = LocalLLMProvider(api_key="", config=config)

# New way (flexible per-stage configuration)
pm = ProviderManager(db)
provider, _ = pm.get_provider_for_stage("prefilter")

# Both work! Old code not affected.
```

## Performance Characteristics

| Provider | Speed | Quality | Local | Use Case |
|----------|-------|---------|-------|----------|
| Qwen | ⚡ Fast | ⭐⭐⭐ | Yes | Prefiltering (Yes/No) |
| Gemma (local_llm) | ⚡ Fast | ⭐⭐⭐⭐ | Yes | Scoring, Enrichment |
| Gemini | ⚡⚡ Medium | ⭐⭐⭐⭐⭐ | No | Research, Complex analysis |
| GPT-4 | ⚡⚡ Medium | ⭐⭐⭐⭐⭐ | No | Best quality |
| Claude | ⚡⚡⚡ Slow | ⭐⭐⭐⭐ | No | Good quality, context |

## Testing Scenarios

### Scenario 1: All Local (No Cloud Costs)
```
Provider Setup:
- prefilter: qwen (fast)
- scoring: local_llm (thorough)
- enrichment: local_llm (thorough)

Result: Zero API costs, all local GPU acceleration
```

### Scenario 2: Optimized Speed
```
Provider Setup:
- prefilter: qwen (very fast yes/no)
- scoring: qwen (faster alternative to gemma)
- enrichment: qwen (acceptable quality)

Result: Maximum pipeline throughput
```

### Scenario 3: Best Quality
```
Provider Setup:
- prefilter: local_llm (reliable)
- scoring: gemini (best quality)
- enrichment: gemini (comprehensive research)

Result: Best lead quality, reasonable cost
```

### Scenario 4: Hybrid (Recommended)
```
Provider Setup:
- prefilter: qwen (fast, local)
- scoring: local_llm (thorough, local)
- enrichment: gemini (research, cloud)

Result: Balance of speed, quality, and cost
```

## Validation Commands

```python
# Check which providers are available
from app.providers import list_provider_ids
print(list_provider_ids())
# Output: ['gemini', 'openai', 'anthropic', 'local_llm', 'qwen']

# Check current stage configuration
from app.pipeline.provider_manager import ProviderManager
pm = ProviderManager(db)
print(pm.get_stage_config("prefilter"))
# Output: {'provider_id': 'qwen'}

# Verify provider can be loaded
provider, name = pm.get_provider_for_stage("prefilter")
print(f"Using {name}: {provider is not None}")
# Output: Using qwen: True
```

## Common Configuration Patterns

### Pattern 1: Migrate to Qwen Only
```python
for stage in ["prefilter", "scoring", "enrichment"]:
    pm.configure_stage_provider(stage, "qwen")
```

### Pattern 2: Keep Existing + Add Qwen Prefilter
```python
pm.configure_stage_provider("prefilter", "qwen")
# scoring and enrichment remain as default (local_llm)
```

### Pattern 3: Reset Everything to Defaults
```python
for stage in ["prefilter", "scoring", "enrichment"]:
    pm.reset_stage_to_default(stage)
```

### Pattern 4: Custom Hybrid Setup
```python
config = {
    "prefilter": "qwen",
    "scoring": "gemini",
    "enrichment": "gemini"
}

for stage, provider_id in config.items():
    pm.configure_stage_provider(stage, provider_id)
```

## Next Steps

1. **Review** the [PROVIDER_CONFIG.md](PROVIDER_CONFIG.md) for detailed configuration

2. **Run** the example setup script:
   ```bash
   python examples/setup_qwen_provider.py
   ```

3. **Configure** your Qwen model path in the provider settings

4. **Set** per-stage providers using the ProviderManager API or UI

5. **Test** by running the pipeline and monitoring logs for which provider is used

6. **Monitor** performance and adjust provider selections as needed

## Troubleshooting Quick Reference

| Issue | Solution |
|-------|----------|
| Qwen not found | Check `providers/__init__.py` - QwenProvider should be imported |
| Model fails to load | Verify path and llama-cpp-python installation |
| HTTP connection fails | Ensure Ollama/server running and base URL correct |
| Wrong provider used | Check stage config with `pm.get_stage_config(stage)` |
| Need to switch providers | Use `pm.configure_stage_provider(stage, provider_id)` |

## Architecture Benefit Recap

✅ **Modular**: Each stage independently chooses its provider
✅ **Flexible**: Mix and match local and cloud providers
✅ **Maintainable**: Clean provider interface
✅ **Extensible**: Easy to add new providers
✅ **Performant**: Intelligent caching and fallbacks
✅ **Configurable**: Database-backed configuration
✅ **Compatible**: Existing code continues to work
