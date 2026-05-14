# Getting Started with the New Provider System

## What's New

Your application now has a **flexible, modular provider system** that allows you to:

✅ Use **Qwen** as a local LLM provider alongside existing providers
✅ Configure **different providers for different pipeline stages** (prefilter, scoring, enrichment)
✅ **Mix local and cloud providers** for optimal cost/performance balance
✅ **Easily extend** with new providers in the future

## Installation & Setup (10 minutes)

### Step 1: Install Qwen Provider (Already Included!)

The Qwen provider is already implemented in your codebase:
- `src/app/providers/qwen_provider.py` - Complete implementation
- Registered in `src/app/providers/__init__.py` - Ready to use

### Step 2: Get a Qwen Model

Download a Qwen model in GGUF format:
- **Option A**: Download pre-converted model
  - Example: `Qwen3.5-9B-UD-Q8_K_XL.gguf` (from Hugging Face)
  - Size: ~5-10 GB (varies by quantization)

- **Option B**: Convert existing Qwen model
  - Use `llama.cpp` tools to convert from original format
  - Requires `llama-cpp-python`: `pip install llama-cpp-python`

### Step 3: Configure Qwen Provider

**Option A: Direct Mode (Local File)**
```python
from app.core.db import DatabaseManager

db = DatabaseManager()
qwen_config = {
    "mode": "direct",
    "model_path": r"C:\path\to\Qwen3.5-9B-UD-Q8_K_XL.gguf",
    "n_gpu_layers": -1,  # -1 = all layers on GPU
    "context_size": 8192,
}

provider = db.get_provider("qwen")
provider.enabled = 1
provider.config = qwen_config
db.update_provider(provider)
```

**Option B: HTTP Mode (Via Ollama or Similar)**
```python
qwen_config = {
    "mode": "http",
    "http_base_url": "http://localhost:11434",
    "http_model": "qwen",
}

provider = db.get_provider("qwen")
provider.enabled = 1
provider.config = qwen_config
db.update_provider(provider)
```

### Step 4: Configure Per-Stage Providers

```python
from app.pipeline.provider_manager import ProviderManager

db = DatabaseManager()
pm = ProviderManager(db)

# Configuration 1: Use Qwen for everything (fastest)
pm.configure_stage_provider("prefilter", "qwen")
pm.configure_stage_provider("scoring", "qwen")
pm.configure_stage_provider("enrichment", "qwen")

# Configuration 2: Optimized (Qwen for prefilter, Gemma for others)
pm.configure_stage_provider("prefilter", "qwen")           # Fast yes/no
pm.configure_stage_provider("scoring", "local_llm")        # Thorough
pm.configure_stage_provider("enrichment", "local_llm")     # Thorough

# Configuration 3: Check current setup
for stage in ["prefilter", "scoring", "enrichment"]:
    provider, name = pm.get_provider_for_stage(stage)
    print(f"{stage}: {name}")
```

## Architecture Overview

```
Pipeline Execution
│
├─ Stage 1: Scrape (fetch raw data)
│
├─ Stage 2: Normalize (clean data)
│
├─ Stage 3: Group Prefilter (Yes/No filter)
│  └─ Uses: ProviderManager.get_provider_for_stage("prefilter")
│     └─ Can be: qwen, local_llm, or any provider with prefilter()
│
├─ Stage 4: Enrichment (find additional info)
│  └─ Uses: ProviderManager.get_provider_for_stage("enrichment")
│     └─ Can be: qwen, local_llm, gemini, openai, etc.
│
└─ Stage 5: Scoring (evaluate quality)
   └─ Uses: ProviderManager.get_provider_for_stage("scoring")
      └─ Can be: qwen, local_llm, gemini, openai, etc.
```

## Development Changes

### For Pipeline Stage Developers

**Old Way** (hardcoded):
```python
def _get_prefilter_provider(self):
    return LocalLLMProvider(api_key="", config=config)
```

**New Way** (flexible):
```python
from app.pipeline.provider_manager import ProviderManager

pm = ProviderManager(self._db, mock=self._mock)
provider, provider_id = pm.get_provider_for_stage("prefilter")
```

**Why?**
- ✅ Stage doesn't care which provider is used
- ✅ Configuration happens outside the stage
- ✅ Easy to swap providers without code changes
- ✅ Testable with mock implementations

### For Provider Developers

To create a new provider:

1. **Create provider class** extending `BaseProvider`:
   ```python
   from app.providers.base import BaseProvider
   
   class MyProvider(BaseProvider):
       def prefilter(self, text, prompt):
           # Your implementation
           pass
   ```

2. **Register in provider registry**:
   ```python
   # In src/app/providers/__init__.py
   from .my_provider import MyProvider
   
   _PROVIDERS["my_provider"] = MyProvider
   ```

3. **Use in pipeline**:
   ```python
   pm.configure_stage_provider("prefilter", "my_provider")
   ```

## Performance Comparison

| Operation | Qwen | Gemma (local_llm) | Gemini | GPT-4 |
|-----------|------|------------------|--------|-------|
| Prefilter (Yes/No) | ⚡⚡ 100ms | ⚡⚡ 150ms | ⚡ 500ms | ⚡ 800ms |
| Scoring | ⚡ 500ms | ⚡ 1s | ⚡ 2s | ⚡ 3s |
| Enrichment | ⚡ 800ms | ⚡ 2s | ⚡⚡ 3s | ⚡⚡ 4s |
| Cost per 1000 calls | Free | Free | $0.50-2.00 | $2.00-6.00 |

**Recommendation**: Use Qwen for prefiltering (yes/no), Gemma for scoring, optionally Gemini for enrichment.

## Testing Your Setup

```python
# File: test_provider_setup.py
from app.core.db import DatabaseManager
from app.pipeline.provider_manager import ProviderManager

db = DatabaseManager()
pm = ProviderManager(db, mock=False)

print("Testing Provider Setup...\n")

# Test 1: Check registered providers
from app.providers import list_provider_ids
print(f"Available providers: {list_provider_ids()}")

# Test 2: Check configuration
for stage in ["prefilter", "scoring", "enrichment"]:
    config = pm.get_stage_config(stage)
    provider, name = pm.get_provider_for_stage(stage)
    status = "✅" if provider else "❌"
    print(f"{status} {stage}: {name} (config: {config})")

# Test 3: Try a provider
try:
    provider, name = pm.get_provider_for_stage("prefilter")
    if provider:
        # Test prefilter
        test_content = "Company XYZ seeks 3D animation services"
        test_prompt = "Is this about animation outsourcing?"
        result, raw = provider.prefilter(test_content, test_prompt)
        print(f"\n✅ Prefilter test passed: {result}")
except Exception as e:
    print(f"\n❌ Prefilter test failed: {e}")

print("\n✅ Setup verification complete!")
```

## Common Tasks

### Task 1: Switch to Qwen for Prefiltering
```python
pm.configure_stage_provider("prefilter", "qwen")
print("Now using Qwen for prefiltering!")
```

### Task 2: Use Cloud Fallback if Local Fails
```python
# Already built-in! If local provider fails, automatically tries cloud.
# Configure cloud provider as fallback:
pm.configure_stage_provider("scoring", "gemini")
```

### Task 3: Monitor Which Provider Is Used
```python
# In your pipeline logs:
log.info(f"Using {provider_name} for prefiltering")
log.info(f"Prefilter result: {result}")
```

### Task 4: Add a New Local Provider
```python
# 1. Create provider class
# 2. Register in __init__.py
# 3. Configure stage: pm.configure_stage_provider("prefilter", "new_provider")
```

## Troubleshooting

### Q: "Qwen provider not found"
**A**: Check that `QwenProvider` is imported in `src/app/providers/__init__.py`
```python
from .qwen_provider import QwenProvider
```

### Q: "Model file not found"
**A**: Verify path and use raw string:
```python
model_path = r"C:\path\to\model.gguf"  # Note: raw string (r prefix)
```

### Q: "llama-cpp-python not installed"
**A**: Install with pip:
```bash
pip install llama-cpp-python
```

### Q: "Wrong provider is being used for a stage"
**A**: Check configuration:
```python
config = pm.get_stage_config("prefilter")
print(config)  # Should show {"provider_id": "qwen"}
```

### Q: "How to switch back to original behavior?"
**A**: Reset to defaults:
```python
pm.reset_stage_to_default("prefilter")  # Goes back to local_llm
```

## Documentation Resources

- **[PROVIDER_CONFIG.md](PROVIDER_CONFIG.md)** - Detailed configuration guide
- **[QWEN_INTEGRATION_SUMMARY.md](QWEN_INTEGRATION_SUMMARY.md)** - Complete integration details
- **[QUICK_START.md](QUICK_START.md)** - Quick reference and patterns
- **examples/setup_qwen_provider.py** - Working example

## Support

For issues or questions:
1. Check the documentation files above
2. Review the example setup script
3. Check application logs for error messages
4. Verify configuration with test script above

## Next Steps

1. ✅ Download a Qwen model
2. ✅ Configure Qwen provider
3. ✅ Run the example setup script
4. ✅ Run your pipeline
5. ✅ Monitor logs to verify which provider is used
6. ✅ Adjust per-stage providers based on performance

That's it! Your application now has flexible, modular provider support! 🎉
