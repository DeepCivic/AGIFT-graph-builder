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
  - `agift/common.py` — constants, Neo4j helpers, run logging, summary
  - `agift/fetch.py` — TemaTres API hierarchy fetching + alt-labels
  - `agift/graph.py` — schema setup + node/edge upsert
  - `agift/embed.py` — Isaacus + local sentence-transformer providers
  - `agift/link.py` — cosine similarity + semantic edge building
  - `import_agift.py` — thin CLI entry point (imports from the package)

## Architecture

```
import_agift.py    — CLI entry point for the 4-stage ETL pipeline
agift/             — pipeline package (common, fetch, graph, embed, link)
dashboard/app.py   — Flask web UI for config, run control, and monitoring
worker/            — Docker + cron for scheduled pipeline runs
```

**Data flow:** TemaTres REST API → Neo4j nodes/edges → embeddings → semantic similarity edges

## Build & Run

```bash
# Prerequisites: Neo4j running on bolt://localhost:7687
# Set environment variables: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# Run the pipeline
python import_agift.py
python import_agift.py --dry-run
python import_agift.py --skip-embed
python import_agift.py --force-embed

# Dashboard
cd dashboard && flask run --port 5050
```

## Key Dependencies

- Python 3.13+, Neo4j 5.0+, Flask 3.0+
- neo4j (driver), sentence-transformers (local embeddings)
- Isaacus kanon-2-embedder API (optional cloud embeddings)
