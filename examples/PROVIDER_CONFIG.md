# Provider Configuration Guide

## Overview

The provider system now supports flexible, modular provider selection for different pipeline stages:
- **Prefilter stage**: Initial Yes/No filtering of leads
- **Scoring stage**: Lead evaluation and ranking
- **Enrichment stage**: Data enrichment and research

## Supported Providers

### Local Providers
- **local_llm**: Gemma 4 or other models via llama-cpp-python (supports both direct and HTTP modes)
- **qwen**: Qwen models via llama-cpp-python (supports both direct and HTTP modes)

### Cloud Providers
- **gemini**: Google Gemini API
- **openai**: OpenAI API
- **anthropic**: Anthropic Claude API

## Configuration

### Per-Stage Provider Configuration

Each stage (prefilter, scoring, enrichment) can be independently configured with its own provider. This allows:

1. **Same provider for all stages**:
   ```
   All stages use "local_llm" (Gemma)
   ```

2. **Different providers per stage**:
   ```
   Prefilter: Qwen (fast, optimized for yes/no)
   Scoring: Gemma (more thorough evaluation)
   Enrichment: Gemini (cloud API for additional research)
   ```

### Setting Up Providers via Database

The provider configuration is stored in the database settings table using the pattern `provider_{stage}`.

**Example: Configure Qwen for prefiltering**

```python
from app.core.db import DatabaseManager

db = DatabaseManager()
db.set_setting("provider_prefilter", {
    "provider_id": "qwen"
})
```

**Example: Configure different providers**

```python
# Prefilter with Qwen (fast)
db.set_setting("provider_prefilter", {"provider_id": "qwen"})

# Scoring with Gemma (thorough)
db.set_setting("provider_scoring", {"provider_id": "local_llm"})

# Enrichment with Gemini (cloud research)
db.set_setting("provider_enrichment", {"provider_id": "gemini"})
```

### Resetting to Defaults

```python
# Reset a stage to its default provider
db.set_setting("provider_prefilter", {})
```

## Qwen Configuration

### Direct Mode (Local Model)

For running Qwen locally with full control:

```python
provider_config = {
    "mode": "direct",
    "model_path": r"C:\path\to\Qwen3.5-9B-UD-Q8_K_XL.gguf",
    "n_gpu_layers": -1,  # Load all layers on GPU (or specify a number)
    "context_size": 8192,
}

provider_data = db.get_provider("qwen")
provider_data.config = provider_config
db.update_provider(provider_data)
```

### HTTP Mode (Local Server)

For running Qwen via an HTTP server (e.g., Ollama):

```python
provider_config = {
    "mode": "http",
    "http_base_url": "http://localhost:11434",
    "http_model": "qwen",  # Model name in your HTTP server
}

provider_data = db.get_provider("qwen")
provider_data.config = provider_config
db.update_provider(provider_data)
```

## Local LLM (Gemma) Configuration

Same configuration pattern as Qwen:

### Direct Mode
```python
provider_config = {
    "mode": "direct",
    "model_path": r"C:\path\to\Gemma-2b.gguf",
    "n_gpu_layers": -1,
    "context_size": 8192,
}
```

### HTTP Mode
```python
provider_config = {
    "mode": "http",
    "http_base_url": "http://localhost:11434",
    "http_model": "gemma",
}
```

## Cloud Provider Configuration

### Gemini
```python
provider_config = {}  # Config is optional for cloud providers

# Ensure the API key is set in secrets
db.set_secret("GEMINI_API_KEY", "your-key-here")

provider_data = db.get_provider("gemini")
provider_data.secret_key_name = "GEMINI_API_KEY"
provider_data.enabled = True
db.update_provider(provider_data)
```

### OpenAI
```python
provider_config = {
    "model": "gpt-4-turbo"  # Or your preferred model
}

db.set_secret("OPENAI_API_KEY", "your-key-here")

provider_data = db.get_provider("openai")
provider_data.config = provider_config
provider_data.secret_key_name = "OPENAI_API_KEY"
provider_data.enabled = True
db.update_provider(provider_data)
```

## Recommended Configurations

### Lightweight & Fast (Best for Quick Prefiltering)
```
Prefilter: qwen (small, fast yes/no decisions)
Scoring: local_llm (more thorough evaluation)
Enrichment: local_llm
```

### Balance (Good Default)
```
Prefilter: local_llm (Gemma, reliable)
Scoring: local_llm (Gemma, thorough)
Enrichment: local_llm (Gemma, data extraction)
```

### Hybrid (Local + Cloud)
```
Prefilter: qwen (local, fast)
Scoring: local_llm (local, thorough)
Enrichment: gemini (cloud, comprehensive research)
```

### Cloud-Only
```
Prefilter: gemini (cloud)
Scoring: gemini (cloud)
Enrichment: gemini (cloud)
```

## Provider Manager API

For programmatic provider management:

```python
from app.pipeline.provider_manager import ProviderManager

# Initialize manager
pm = ProviderManager(db, mock=False)

# Get provider for a stage
provider, provider_id = pm.get_provider_for_stage("prefilter")

# Configure a stage
pm.configure_stage_provider("prefilter", "qwen")

# Get current configuration
config = pm.get_stage_config("prefilter")

# Reset to defaults
pm.reset_stage_to_default("prefilter")

# Clear cache (useful after config changes)
pm.invalidate_cache()
```

## Troubleshooting

### Provider Not Found
- Ensure the provider is registered in `providers/__init__.py`
- Check that the provider ID is correct (one of: gemini, openai, anthropic, local_llm, qwen)

### Model Loading Failed
- Verify the model file path exists
- Ensure llama-cpp-python is installed: `pip install llama-cpp-python`
- Check GPU compatibility and CUDA/Metal setup

### HTTP Connection Failed
- Ensure the HTTP server (e.g., Ollama) is running
- Check the base URL configuration
- Verify the model name matches what's running on the server

### API Key Issues
- Ensure the secret is set in the database
- Check the secret_key_name in the provider configuration
- Verify the API key is valid and not expired

## Environment Variables

You can override configuration via environment variables:

```bash
# Set model path for Qwen
export QWEN_MODEL_PATH="C:\path\to\model.gguf"

# Enable GPU layers
export QWEN_GPU_LAYERS=-1

# Set HTTP server URL
export LOCAL_LLM_HTTP_URL="http://localhost:11434"
```

The application will check for these if configuration is missing.

## Migration from Old System

If upgrading from a system using only local_llm:

1. All existing configurations will continue to work
2. Stages default to local_llm unless explicitly configured
3. No action needed unless you want to use different providers per stage
4. To migrate to Qwen for prefiltering: `db.set_setting("provider_prefilter", {"provider_id": "qwen"})`
