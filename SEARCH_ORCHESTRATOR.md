# Search Orchestrator Subsystem

The `search/` subsystem provides parallel, multi-engine search capabilities with automatic URL normalization, deduplication, and cross-engine provenance tracking.

## Architecture

```
                    ┌─────────────────────────┐
                    │   SearchOrchestrator    │
                    └───────────┬─────────────┘
                                │ (parallel dispatch)
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
┌───────────────────────┐ ┌───────────────┐ ┌───────────────┐
│AnthropicSearchAdapter │ │ TavilyAdapter │ │ GeminiAdapter │
│ (Claude web_search)   │ │  (REST API)   │ │ (Grounding)   │
└───────────┬───────────┘ └───────┬───────┘ └───────┬───────┘
            │                     │                 │
            └─────────────────────┼─────────────────┘
                                  ▼
                   ┌────────────────────────────┐
                   │ Normalize URLs & Dedupe    │
                   │ Multi-engine score boost   │
                   └──────────────┬─────────────┘
                                  ▼
                     List[Blackboard.Source]
```

## Features

1. **Parallel Execution**: Adapters execute concurrently via `asyncio.gather`.
2. **Graceful Fault Tolerance**: If any adapter fails (network timeout, invalid key, rate limit), the orchestrator logs the failure and merges results from the remaining adapters without failing the search run.
3. **URL Normalization**: Normalizes scheme (`http`/`https`), removes `www.`, strips trailing slashes, and ignores query parameters/hash anchors for canonical deduplication.
4. **Cross-Engine Provenance**: Retains all engine names that found a given source (`engines: ["claude_web_search", "tavily"]`), granting confidence boosts in Layer 1/2 verification.

## Configuration

Search backends are configured in `llm/models.yaml` under each agent (e.g. `ResearcherAgent`, `SurveyorAgent`):

```yaml
ResearcherAgent:
  model: "claude-sonnet-5"
  search_backends:
    - "claude_web_search"
    - "tavily"
```
