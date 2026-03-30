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

### Known Oversized File
- `import_agift.py` (952 lines) exceeds the 750-line limit. Proposed refactor path:
  - Extract `fetch` stage (hierarchy + alt-labels) into `agift/fetch.py`
  - Extract `graph` stage (schema + upsert) into `agift/graph.py`
  - Extract `embed` stage (Isaacus + local providers) into `agift/embed.py`
  - Extract `link` stage (cosine similarity + semantic edges) into `agift/link.py`
  - Keep shared helpers (`get_neo4j_driver`, `get_config_from_neo4j`, `log_run`) in `agift/common.py`
  - Retain `import_agift.py` as a thin CLI entry point calling into the package
  - **Status: awaiting human approval before proceeding.**

## Architecture

```
import_agift.py    — 4-stage ETL pipeline (fetch → graph → embed → link)
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
