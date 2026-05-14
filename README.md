# LeadsScraper

> **AI-powered lead discovery desktop app for 3D animation studios.**  
> Automatically scrapes the web, pre-filters with LLM, scores leads, and builds a client database — all running locally on Windows.

---

## Overview

LeadsScraper 2 is a local-first Windows desktop application built for 3D animation outsourcing studios. It continuously discovers and ranks potential clients from Google, X/Twitter, LinkedIn and other sources — then uses an LLM to score each lead's relevance, extract client information, and build an enriched contact database.

**Target use cases:**
- Game studios looking for outsourcing partners
- Brand / commercial animation studios prospecting new clients
- Any B2B studio that needs a steady pipeline of qualified leads

---

## Features

| Feature | Description |
|---|---|
| **Desktop UI** | PySide6 native Windows app — no browser required |
| **Multi-source scraping** | Apify actors for Google, X/Twitter, LinkedIn (extensible) |
| **5-stage pipeline** | Scrape → Normalize → Pre-filter → Analyze → Client Analysis |
| **LLM scoring** | Gemini, DeepSeek, Qwen, local LLM (llama.cpp), OpenAI-compatible |
| **Client database** | Auto-extracts client records from scored leads |
| **Keyword groups** | Per-group prefilter prompts and analysis prompts |
| **Keyword learning** | Automatic weight adjustment from manual feedback |
| **Secure secrets** | API keys stored in Windows Credential Manager or Fernet-encrypted |
| **Fully local** | SQLite database, no cloud sync, no telemetry |
| **CLI support** | Run pipeline headlessly via Task Scheduler |

---

## Requirements

- Windows 10 / 11
- Python 3.11+
- [Apify](https://apify.com) account + API token (for scraping)
- At least one LLM provider API key (Gemini, DeepSeek, etc.) **or** a local LLM server

---

## Installation

```powershell
git clone https://github.com/kobivfx/PentaCoreLeadsScape.git
cd LeadsScraper2
pip install -r requirements.txt
```

### Optional — Local LLM (llama.cpp direct mode)

If you want to run a local `.gguf` model without an HTTP server:

```powershell
pip install llama-cpp-python
```

**Recommended model:** [supergemma4-26b-uncensored-fast-v2-Q4_K_M.gguf](https://huggingface.co/Jiunsong/supergemma4-26b-uncensored-gguf-v2/blob/main/supergemma4-26b-uncensored-fast-v2-Q4_K_M.gguf)  
*(SuperGemma4 26B — Q4_K_M quantized, optimized for speed)*

---

## Running

### Desktop UI

```powershell
cd src
python -m app
```

### Headless CLI (for Task Scheduler)

```powershell
cd src
python -m app.pipeline --once            # full run
python -m app.pipeline --once --mock     # mock data (no API calls)
python -m app.pipeline --once --dry-run  # skip LLM stages
```

---

## First-Time Setup

On first launch the app auto-creates `data/leads.db` and seeds default data:

1. Open **Providers** page → enter your LLM API key (Gemini, DeepSeek, etc.)
2. Open **Settings** page → enter your Apify API token
3. Open **Actors** page → review the default actors (Google, X, LinkedIn)
4. Open **Keywords** page → review or customize seed keywords
5. Click **Run Pipeline Now** on the Dashboard (or use **Mock Run** to test without API calls)

> **Tip:** Use Mock Run first to verify the UI and pipeline flow without spending any API credits.

---

## Pipeline Stages

```
[Scrape]  →  Apify actors fetch raw posts/pages via keywords
    ↓
[Normalize]  →  Deduplicate, rule-score, upsert leads to DB
    ↓
[Group Prefilter]  →  LLM Yes/No per keyword group (fast filter)
    ↓
[Analysis]  →  LLM scores each lead 0–100, extracts client info
    ↓
[Client Analysis]  →  LLM evaluates each new client record
```

---

## Project Structure

```
LeadsScraper2/
├── src/app/
│   ├── core/
│   │   ├── db.py               # SQLite schema, CRUD, migrations
│   │   ├── models.py           # Dataclasses: Lead, Client, Keyword…
│   │   ├── config.py           # Paths, defaults
│   │   └── secrets_manager.py  # Keyring / Fernet encrypted secrets
│   ├── pipeline/
│   │   ├── engine.py           # Pipeline orchestrator
│   │   ├── apify_runner.py     # Apify HTTP client
│   │   ├── provider_manager.py # Per-stage LLM provider routing
│   │   ├── prefilter.py        # Rule-based scoring
│   │   ├── learning.py         # Keyword weight learning
│   │   └── stages/             # Scrape, Normalize, Prefilter, Analysis, ClientAnalysis
│   ├── providers/
│   │   ├── gemini_provider.py
│   │   ├── deepseek_provider.py
│   │   ├── local_provider.py   # llama.cpp (direct or HTTP)
│   │   ├── qwen_provider.py
│   │   └── base.py
│   └── ui/
│       ├── main_window.py
│       ├── pages/              # Dashboard, Leads, Clients, Keywords, Actors, Providers, Settings
│       └── widgets/
├── data/                       # ← gitignored: leads.db, logs, .secret_key
├── requirements.txt
└── README.md
```

---

## Security

API keys are **never stored in plain text in source code**.

- If `keyring` is available → keys are stored in **Windows Credential Manager**
- Otherwise → keys are **Fernet-encrypted** using a machine-local key at `data/.secret_key`

⚠️ **Never commit the `data/` folder.** It contains your database, encrypted keys, and logs.  
A `.gitignore` excluding `data/` should be in place before you push.

---

## Providers Supported

| Provider | Type | Notes |
|---|---|---|
| Google Gemini | Cloud API | Default, recommended |
| DeepSeek | Cloud API | Cost-effective alternative |
| OpenAI-compatible | Cloud API | Any OpenAI-compatible endpoint |
| Local LLM (llama.cpp) | Local | Direct `.gguf` or HTTP server mode |
| Qwen | Local / HTTP | Ollama or direct mode |

---

## Scheduling (Windows Task Scheduler)

The **Settings** page has a "Generate .bat Script" button.  
It creates a `.bat` file you can register with Windows Task Scheduler to run the pipeline automatically on a schedule.

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you'd like to change.

---

## License

MIT
