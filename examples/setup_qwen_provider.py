#!/usr/bin/env python
"""Example: Enable Qwen as a local provider with modular stage-specific configuration."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from app.core.db import DatabaseManager
from app.pipeline.provider_manager import ProviderManager


def setup_qwen_provider():
    """Install Qwen provider with direct model loading."""
    db = DatabaseManager()
    
    print("=" * 60)
    print("Setting up Qwen Provider")
    print("=" * 60)
    
    # 1. Configure Qwen provider with direct model loading
    qwen_config = {
        "mode": "direct",
        "model_path": r"C:\Users\anhdd\Downloads\Qwen3.5-9B-UD-Q8_K_XL.gguf",
        "n_gpu_layers": -1,  # Use all GPU layers
        "context_size": 8192,
    }
    
    qwen_provider = db.get_provider("qwen")
    if not qwen_provider:
        print("ERROR: Qwen provider not found in registry!")
        print("Make sure qwen_provider.py is properly imported in providers/__init__.py")
        return False
    
    qwen_provider.enabled = 1
    qwen_provider.display_name = "Qwen 3.5 9B"
    qwen_provider.config = qwen_config
    qwen_provider.secret_key_name = ""  # No API key needed for local models
    
    db.update_provider(qwen_provider)
    print("✅ Qwen provider configured")
    print(f"   Path: {qwen_config['model_path']}")
    print(f"   GPU Layers: {qwen_config['n_gpu_layers']}")
    
    return True


def setup_provider_per_stage():
    """Configure different providers for different stages."""
    db = DatabaseManager()
    pm = ProviderManager(db, mock=False)
    
    print("\n" + "=" * 60)
    print("Setting up Per-Stage Provider Configuration")
    print("=" * 60)
    
    # Configuration 1: Qwen for prefiltering (fast), Gemma for scoring (thorough)
    config_option1 = {
        "prefilter": "qwen",      # Qwen for fast yes/no decisions
        "scoring": "local_llm",   # Gemma for detailed scoring
        "enrichment": "local_llm" # Gemma for enrichment
    }
    
    # Configuration 2: All Qwen
    config_option2 = {
        "prefilter": "qwen",
        "scoring": "qwen",
        "enrichment": "qwen"
    }
    
    # Configuration 3: Hybrid (local + cloud)
    config_option3 = {
        "prefilter": "qwen",      # Local - fast
        "scoring": "local_llm",   # Local - thorough
        "enrichment": "gemini"    # Cloud - research capability
    }
    
    print("\nAvailable configurations:")
    print("1. Qwen (prefilter) + Gemma (scoring/enrichment) — RECOMMENDED")
    print("2. All Qwen — Fast but may be less thorough")
    print("3. Qwen + Gemma + Gemini — Hybrid approach")
    
    # Apply configuration 1 (recommended)
    print("\nApplying Configuration 1 (Recommended)...")
    for stage, provider_id in config_option1.items():
        try:
            pm.configure_stage_provider(stage, provider_id)
            print(f"✅ {stage}: {provider_id}")
        except Exception as e:
            print(f"❌ {stage}: {e}")
    
    return pm


def list_available_providers(db):
    """Show all available providers."""
    print("\n" + "=" * 60)
    print("Available Providers")
    print("=" * 60)
    
    from app.providers import list_provider_ids
    
    provider_ids = list_provider_ids()
    for provider_id in provider_ids:
        provider = db.get_provider(provider_id)
        status = "✅ ENABLED" if provider and provider.enabled else "⚠️  DISABLED"
        print(f"  - {provider_id.ljust(15)} {status}")


def test_provider_retrieval(pm):
    """Test provider retrieval for each stage."""
    print("\n" + "=" * 60)
    print("Testing Provider Retrieval")
    print("=" * 60)
    
    for stage in ["prefilter", "scoring", "enrichment"]:
        try:
            provider, provider_id = pm.get_provider_for_stage(stage)
            if provider:
                print(f"✅ {stage.ljust(12)} -> {provider_id}")
            else:
                print(f"⚠️  {stage.ljust(12)} -> {provider_id} (provider instance is None)")
        except Exception as e:
            print(f"❌ {stage.ljust(12)} -> ERROR: {e}")


def show_configuration(db, pm):
    """Display current configuration."""
    print("\n" + "=" * 60)
    print("Current Configuration")
    print("=" * 60)
    
    for stage in ["prefilter", "scoring", "enrichment"]:
        config = pm.get_stage_config(stage)
        provider_id = config.get("provider_id", "default")
        actual = pm._get_default_provider_for_stage(stage) if not provider_id else provider_id
        print(f"  {stage.ljust(12)} -> {actual}")


def main():
    print("\n" + "🚀 " * 20)
    print("QWEN PROVIDER INTEGRATION EXAMPLE")
    print("🚀 " * 20 + "\n")
    
    db = DatabaseManager()
    
    # Setup
    if not setup_qwen_provider():
        return 1
    
    list_available_providers(db)
    pm = setup_provider_per_stage()
    show_configuration(db, pm)
    
    # Detailed test
    test_provider_retrieval(pm)
    
    print("\n" + "=" * 60)
    print("Integration Complete!")
    print("=" * 60)
    print("""
Next steps:
1. Start the application and configure providers in the UI
2. Run a pipeline and monitor which provider is used for each stage
3. Adjust stage-specific providers as needed for performance

See PROVIDER_CONFIG.md for detailed configuration guide.
    """)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
