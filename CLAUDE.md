# CLAUDE.md

## Project Overview

AGIFT Graph Builder — a knowledge graph pipeline that ingests the Australian Government Interactive Functions Thesaurus (AGIFT) vocabulary, enriches it with vector embeddings, and builds semantic similarity edges. Supports Neo4j and CogDB backends. Apache 2.0 licensed open source project.

## Project Rules

### Open Source Hygiene
- **No working files in the repo.** Do not commit scratch files, temp outputs, notebooks, `.env` files, or editor configs. If a file is only useful during development, add it to `.gitignore`.
- **No secrets or credentials.** API keys, tokens, and passwords must come from environment variables. Default placeholders (e.g. `"changeme"`) are acceptable only as dev fallbacks alongside `os.environ.get()`.
- **No absolute or machine-specific paths.** All file references must be relative to the project root.

### File Size Limit
- **750 lines max per file.** If a file exceeds this, propose a refactoring plan to the human for approval before splitting. Do not refactor without confirmation.

### Refactored: `import_agift.py` → `agift/` package
- The original 952-line monolith has been split into the `agift/` package:
  - `agift/backend.py` — `GraphBackend` abstract interface
  - `agift/neo4j_backend.py` — Neo4j backend implementation
  - `agift/cogdb_backend.py` — CogDB embedded backend implementation
  - `agift/cli.py` — CLI entry point + `run_pipeline()` programmatic API
  - `agift/common.py` — constants, backend factory, summary output
  - `agift/fetch.py` — TemaTres API hierarchy fetching + alt-labels
  - `agift/graph.py` — schema setup + node/edge upsert (backend-agnostic)
  - `agift/embed.py` — Isaacus + local sentence-transformer providers (backend-agnostic)
  - `agift/link.py` — cosine similarity + semantic edge building (backend-agnostic)
  - `import_agift.py` — backward-compatible entry point (imports from the package)

## Architecture

```
agift/cli.py         — CLI entry point (`agift` command) + run_pipeline() API
agift/backend.py     — GraphBackend ABC (interface for all backends)
agift/neo4j_backend.py — Neo4j implementation
agift/cogdb_backend.py — CogDB implementation
agift/               — pipeline package (common, fetch, graph, embed, link)
docker-compose.yml   — full stack: Neo4j + dashboard + worker
dashboard/app.py     — Flask web UI for config, run control, and monitoring
worker/              — Docker + cron for scheduled pipeline runs
import_agift.py      — backward-compatible entry point
```

**Data flow:** TemaTres REST API → graph nodes/edges → embeddings → semantic similarity edges

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

# CogDB backend (no server required)
pip install agift-graph[cogdb]
agift --backend cogdb

# Programmatic usage
from agift import run_pipeline
run_pipeline(provider="local", dimension=384)
run_pipeline(backend_type="cogdb", provider="local", dimension=384)
```

## Key Dependencies

- Python 3.10+, Neo4j 5.0+, Flask 3.0+
- neo4j (driver), sentence-transformers (local embeddings)
- cogdb (optional embedded graph backend)
- Isaacus kanon-2-embedder API (optional cloud embeddings)
