# CLAUDE.md

## Project Overview

AGIFT Graph Builder — a Neo4j-based knowledge graph that ingests the Australian Government Interactive Functions Thesaurus (AGIFT) vocabulary, enriches it with vector embeddings, and builds semantic similarity edges. Apache 2.0 licensed open source project.

## Project Rules

### Open Source Hygiene
- **No working files in the repo.** Do not commit scratch files, temp outputs, notebooks, `.env` files, or editor configs. If a file is only useful during development, add it to `.gitignore`.
- **No secrets or credentials.** API keys, tokens, and passwords must come from environment variables. Default placeholders (e.g. `"changeme"`) are acceptable only as dev fallbacks alongside `os.environ.get()`.
- **No absolute or machine-specific paths.** All file references must be relative to the project root.

### File Size Limit
- **750 lines max per file.** If a file exceeds this, propose a refactoring plan to the human for approval before splitting. Do not refactor without confirmation.

### Refactored: `import_agift.py` → `agift/` package
- The original 952-line monolith has been split into the `agift/` package:
  - `agift/cli.py` — CLI entry point + `run_pipeline()` programmatic API
  - `agift/common.py` — constants, Neo4j helpers, run logging, summary
  - `agift/fetch.py` — TemaTres API hierarchy fetching + alt-labels
  - `agift/graph.py` — schema setup + node/edge upsert
  - `agift/embed.py` — Isaacus + local sentence-transformer providers
  - `agift/link.py` — cosine similarity + semantic edge building
  - `import_agift.py` — backward-compatible entry point (imports from the package)

## Architecture

```
agift/cli.py         — CLI entry point (`agift` command) + run_pipeline() API
agift/               — pipeline package (common, fetch, graph, embed, link)
docker-compose.yml   — full stack: Neo4j + dashboard + worker
dashboard/app.py     — Flask web UI for config, run control, and monitoring
worker/              — Docker + cron for scheduled pipeline runs
import_agift.py      — backward-compatible entry point
```

**Data flow:** TemaTres REST API → Neo4j nodes/edges → embeddings → semantic similarity edges

## Build & Run

```bash
# Full Docker stack (Neo4j + dashboard + worker)
docker compose up -d --build

# Or standalone with existing Neo4j
pip install agift-graph[all]
agift
agift --dry-run
agift --skip-embed
agift --force-embed

# Programmatic usage
from agift import run_pipeline
run_pipeline(provider="local", dimension=384)
```

## Key Dependencies

- Python 3.13+, Neo4j 5.0+, Flask 3.0+
- neo4j (driver), sentence-transformers (local embeddings)
- Isaacus kanon-2-embedder API (optional cloud embeddings)
