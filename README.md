# 🐼 Panda Research Agent

Panda Research Agent is an enterprise-grade autonomous multi-agent research and architecture pipeline. It features multi-engine web & academic discovery, a 3-layer deterministic and LLM factual verification ladder, a Typed Decision Layer powered by TypeSafe Jev for deterministic discrete scoring and consensus arbitration, cross-run semantic vector memory powered by Voyage AI, real-time WebSocket event streaming, and rubric-driven self-scoring.

---

## 🏛️ System Architecture

```
                               ┌─────────────────────────────┐
                               │     CoordinatorAgent        │
                               └──────────────┬──────────────┘
                                              │
         ┌────────────────────────────────────┼────────────────────────────────────┐
         ▼                                    ▼                                    ▼
┌──────────────────┐               ┌──────────────────┐               ┌──────────────────┐
│   Phase 0        │               │   Phase 1        │               │   Phase 2        │
│   MemoryAgent    │               │ ResearcherAgent  │               │ SurveyorAgent    │
│ (Voyage Vector)  │               │ PaperReaderAgent │               │ (Landscape & SOTA)│
└──────────────────┘               └──────────┬───────┘               └──────────┬───────┘
                                              │ (Layer 1 Check)                  │ (Layer 2 Check)
         ┌────────────────────────────────────┼──────────────────────────────────┘
         ▼                                    ▼
┌──────────────────┐               ┌──────────────────┐
│   Phase 3        │               │   Phase 4        │
│  GapAnalystAgent │               │   IdeatorAgent   │
│ (Technical Gaps) │               │(Novel Architect.)│
└────────┬─────────┘               └──────────┬───────┘
         │ (Layer 2 Check)                    │ (Layer 2 Check)
         └─────────────────┬──────────────────┘
                           ▼
┌─────────────────────────────────────────────────────┐
│                      Phase 5                        │
│   TechStackAgent (Stack Layers & GitHub Health)     │
│   EvaluatorAgent (Feasibility, Complexity, Risks)   │
└──────────────────────────┬──────────────────────────┘
                           │ ◄─── [Typed Decision Layer: TypeSafe Jev]
                           ▼
┌─────────────────────────────────────────────────────┐
│                      Phase 6                        │
│   VerificationPipeline: Layer 3 Consistency Audit   │
└──────────────────────────┬──────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────┐
│                      Phase 7                        │
│   GradingAlignmentAgent (Rubric-Driven Self-Audit)  │
└──────────────────────────┬──────────────────────────┘
                           │ ◄─── [Typed Decision Layer: TypeSafe Jev]
                           ▼
┌─────────────────────────────────────────────────────┐
│                      Phase 8                        │
│   ReporterAgent (Publication-Grade Markdown Report) │
└──────────────────────────┬──────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────┐
│                      Phase 9                        │
│   MemoryAgent: Save Run Digest to Voyage AI Index   │
│   SQLite Persistence: storage/db.py                 │
└─────────────────────────────────────────────────────┘
```

---

## 🤖 The 11 Pipeline Agents

1. **`CoordinatorAgent`**: Manages the multi-phase lifecycle, dispatches parallel agent batches, coordinates fallback degradation, and persists run records to SQLite.
2. **`MemoryAgent`**: Pre-run semantic retrieval of relevant prior run digests from the local vector store; post-run embedding generation via Voyage AI.
3. **`ResearcherAgent`**: Multi-engine parallel web search across Anthropic Claude web search, Tavily, and Gemini with automated deduplication and domain scoring.
4. **`PaperReaderAgent`**: Queries arXiv XML, Semantic Scholar, Unpaywall, and CORE APIs, resolving open-access full texts and synthesizing academic findings without unapproved external scrapers.
5. **`SurveyorAgent`**: Analyzes state-of-the-art landscape across commercial, open-source, and academic solutions enriched by OpenAlex and Crossref, featuring deterministic Phase B1.5 Jev relevance triage (`noul` decision arbiter).
6. **`GapAnalystAgent`**: Cross-references findings against literature evidence and architectural constraints to isolate critical technical, market, and usability gaps (grounded dynamically in existing solution limitations).
7. **`IdeatorAgent`**: Designs novel mechanisms, mathematical formulations, and system architectures mapped directly to identified gap IDs.
8. **`TechStackAgent`**: Recommends practical technology choices across 5 architecture layers, validated with live GitHub repository health metrics (stars, forks, open issues, recency).
9. **`EvaluatorAgent`**: Performs feasibility scoring (1-5), complexity scoring (1-5), and risk/mitigation mapping for proposed features via LLM qualitative analysis and TypeSafe Jev discrete calibration.
10. **`GradingAlignmentAgent`**: Parses arbitrary rubrics (YAML weighted categories, Markdown checklists, or free-text) and audits Blackboard evidence to self-score the research run.
11. **`ReporterAgent`**: Assembles a publication-grade markdown report complete with verification badges, provenance matrix, technology stack breakdown, and rubric scorecard.

---

## 🧠 Typed Decision Layer (TypeSafe Jev)

The system integrates a **Typed Decision Layer** via TypeSafe Jev (`sources/jev_client.py`) that handles discrete, deterministic decision making across key evaluation agents:

- **`EvaluatorAgent`**: When `TYPESAFE_API_KEY` is configured, Jev serves as the primary discrete scoring engine for `feasibility_score` (1-5), `complexity_score` (1-5), and `risk_level` (`low`, `medium`, `high`) based on the structured qualitative risk assessment.
- **`GapAnalystAgent`**: Jev classifies gap `severity` (`low`, `medium`, `high`, `critical`) and `category` (`technical`, `market`, `usability`, `architectural`). Fallback gaps (`_fallback_gaps`) dynamically derive from existing solution limitations and academic literature findings rather than static boilerplate.
- **`GradingAlignmentAgent`**: Jev deterministically calibrates rubric scores and evaluations across defined benchmark categories.
- **`Layer2ClaimVerifier`**: Evaluates atomic claims against extracted source evidence to assign consensus verification statuses.

---

## 🌐 6 Free-Tier Data Source & Decision Fallback Ladders

Panda Research Agent features a robust **Primary → Backup → Baseline** 3-tier fallback architecture across 6 specialized domains to maximize data quality while maintaining 100% offline resilience:

| Domain / Specialization | Primary Provider | Backup Provider | Baseline Fallback | Target Agents / Layers | Config / Credentials |
|---|---|---|---|---|---|
| **1. Repo Health** | GitHub REST API (`github.com/repos/...`) | Unauthenticated GitHub REST | Baseline LLM architectural memory | `TechStackAgent` | `GITHUB_TOKEN` (optional) |
| **2. Academic Full Text** | Unpaywall API (`api.unpaywall.org/v2`) | CORE API (`api.core.ac.uk/v3`) | Baseline arXiv / Semantic Scholar abstracts | `PaperReaderAgent` | `UNPAYWALL_EMAIL`, `CORE_API_KEY` |
| **3. Second-Model Claim Check** | Groq Cloud API (Llama 3.3 70B Versatile) | Google Gemini API (`gemini-2.5-flash`) | Baseline single-model Claude Haiku | Layer 2 Claim Verifier | `GROQ_API_KEY`, `GEMINI_API_KEY` |
| **4. Broader Academic Discovery** | OpenAlex API (`api.openalex.org/works`) | Crossref REST API (`api.crossref.org/works`) | Baseline web search / literature | `SurveyorAgent`, `GapAnalystAgent` | `OPENALEX_API_KEY`, `CROSSREF_MAILTO` |
| **5. Computational Claim Check** | Wolfram Alpha API (hard cap: 5 calls/run) | Local Offline Deterministic AST Engine | Baseline textual claim check | Layer 2/3 Verification | `WOLFRAM_APP_ID` (optional) |
| **6. Typed Decision Layer** | TypeSafe Jev Cloud API (`api.typesafe.ai/v1`) | Local Resilient Decision Engine | Heuristic deterministic decision rules | `EvaluatorAgent`, `GapAnalystAgent`, `GradingAlignmentAgent`, Layer 2 | `TYPESAFE_API_KEY` (optional) |

### Computational Claim Verification & Safe AST Engine (`sources/local_compute.py`)
- **Safe Deterministic AST Evaluation**: Uses Python's built-in `ast` module to safely parse and calculate arithmetic expressions without ever calling `eval()` or `exec()`.
- **Unit & Latency Conversions**: Converts and verifies data size (B, KB, MB, GB, TB), time (ns, µs, ms, s, min, hr), and frequency (Hz, kHz, MHz, GHz).
- **Asymptotic Complexity Hierarchy**: Formally checks algorithmic speedup claims against the standard asymptotic ordering:
  $$\mathcal{O}(1) < \mathcal{O}(\log \log n) < \mathcal{O}(\log n) < \mathcal{O}(\text{polylog } n) < \mathcal{O}(\sqrt{n}) < \mathcal{O}(n) < \mathcal{O}(n \log n) < \mathcal{O}(n^2) < \mathcal{O}(n^3) < \mathcal{O}(n^k) < \mathcal{O}(2^n) < \mathcal{O}(k^n) < \mathcal{O}(n!) < \mathcal{O}(n^n)$$
- **Wolfram Alpha Rate Limiter**: Enforces a strict ceiling of at most 5 external API calls per research run to protect free API quotas.

---

## 🛡️ 3-Layer Verification Pipeline

The verification pipeline executes across three independent stages:

```
[Agent Output Text + Evidence Sources]
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ Layer 1: Deterministic Source Verification             │
│ - HTTP HEAD/GET reachability check                     │
│ - Domain reputation weighting & spam filtering         │
│ - Cross-engine consensus multi-source boost            │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Layer 2: Atomic Claim Verification Ladder              │
│ - Stage 1: Secondary LLM (Groq / Gemini) claim extract │
│ - Stage 2: TypeSafe Jev consensus classification       │
│ - Stage 3: Safe AST / Wolfram computational override   │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Layer 3: Consistency & Contradiction Audit             │
│ - Cross-agent contradiction detection                  │
│ - Orphan citation tracking & report validation         │
└────────────────────────────────────────────────────────┘
```

### Visual Confidence Badges

| Badge | Verification Status | Meaning |
|---|---|---|
| `✓ confirmed` | `CONFIRMED` | Corroborated by multi-engine evidence or verified computational calculation. |
| `✓ confirmed (⚠ single-source)` | `CONFIRMED` (Single source) | Backed by only one search provider. |
| `⚠ unsupported` | `UNSUPPORTED` | Statement not confirmed by cited source text. |
| `✗ contradicted` | `CONTRADICTED` | Directly refuted by evidence or failed computational verification. |
| `? unverified` | `NEEDS_HUMAN` | Ambiguous claim or unconfirmed discrete classification flagged for review. |

---

## ⚡ Live Trace & Streamlit Dashboard

- **Live Trace Panel (`live_trace/`)**: Real-time WebSocket streaming server on port `8765` broadcasting agent lifecycle events, message bus dispatches, and blackboard state changes to `live_trace/panel.html`.
- **Streamlit Dashboard (`browser.py`)**: Full interactive dark-canvas dashboard matching the Live Trace chalkboard theme (`#141d18` / `#1e2b23`), providing run history browsing, report markdown downloads, verification tables, and the **🔑 API Keys** management tab.

---

## 🚀 Quickstart & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and configure your API keys:
```env
# Core LLM & Search
ANTHROPIC_API_KEY=your_anthropic_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
VOYAGE_API_KEY=your_voyage_api_key_here

# Typed Decision Layer
TYPESAFE_API_KEY=your_typesafe_api_key_here

# Optional Free-Tier Specialized Data Sources
GITHUB_TOKEN=your_github_token_here
UNPAYWALL_EMAIL=your_email@domain.com
CORE_API_KEY=your_core_api_key_here
GROQ_API_KEY=your_groq_api_key_here
OPENALEX_API_KEY=your_openalex_api_key_here
CROSSREF_MAILTO=your_email@domain.com
WOLFRAM_APP_ID=your_wolfram_app_id_here
```

*(Note: The system includes graceful mock/offline fallbacks if specific optional keys are omitted).*

> 💡 **Tip — Web Dashboard API Keys Tab**: Once the Streamlit dashboard is running (`streamlit run browser.py`), API keys can also be configured and tested directly in the browser via the dedicated **🔑 API Keys** tab. You can choose to store keys in-memory for the active session only, or optionally persist them to your local `.env` file. Using the UI is the most convenient path if you interact via the dashboard; direct CLI runs (`main.py`) continue to read keys directly from `.env` or system environment variables.
>
> *(Note on Concurrency: In-memory session keys are isolated per browser session in Streamlit and scoped to the execution lifetime of each run. For local single-user runs this provides safe, ephemeral key injection without saving to disk. If hosting multi-tenant instances where multiple users run jobs simultaneously, explicit parameter threading is recommended).*

---

## 💻 CLI Usage

### Run a Research Pipeline
```bash
python main.py --topic "On-device real-time speech diarization" --context "Ultra low latency <150ms on ARM64 wearable"
```

### Run with Live Trace Visualization
```bash
python main.py --topic "Vector database indexing architectures" --live-trace
```

### Run with Rubric Self-Scoring
```bash
python main.py --topic "On-device speech diarization" --rubric rubrics/sample_weighted.yaml
```

### Launch the Streamlit Dashboard
```bash
streamlit run browser.py
```

---

## 🧪 Testing

Run the full pytest suite (all 87 unit, integration, and verification ladder tests):
```bash
python -m pytest tests/ -v
```
