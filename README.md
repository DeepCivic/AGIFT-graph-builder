# AGIFT Graph

Australian Government Interactive Functions Thesaurus (AGIFT) as a Neo4j knowledge graph with embeddings and dual edge types.

## What it does

Fetches the full AGIFT vocabulary from the [TemaTres API](https://vocabularyserver.com/agift/), builds a Neo4j graph with structural hierarchy edges, generates embeddings (free local or Isaacus API), then creates semantic similarity edges between related terms.

```
TemaTres API ──► Neo4j Graph ──► Embeddings ──► Semantic Edges
  (AGIFT)        (PARENT_OF)     (384/512/768d)  (SIMILAR_TO)
```

## Graph model

Two edge types with different weights for query-time flexibility:

| Edge | Type | Weight | Description |
|------|------|--------|-------------|
| `PARENT_OF` | structural | 1.0 | AGIFT hierarchy (L1 → L2 → L3) |
| `SIMILAR_TO` | semantic | 0.5 | Cosine similarity above threshold |

Nodes carry DCAT-AP theme mappings for interoperability with European open data standards.

## Quick start

### Path A — Docker (zero config)

```bash
pip install agift-graph[all]
docker compose up -d          # starts Neo4j on localhost:7687
agift                         # fetches AGIFT, builds graph, embeds
```

### Path B — existing Neo4j

```bash
pip install agift-graph[all]
export NEO4J_URI=bolt://my-server:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=mypassword
agift
```

The CLI reads env vars with sensible defaults (`bolt://localhost:7687`, `neo4j`/`changeme`) that match the included `docker-compose.yml`.

### Path C — CogDB (embedded, no server)

[CogDB](https://github.com/arun1729/cog) is a persistent embedded graph database written in pure Python — no server process, no Docker, just a pip install. Good fit if the graph is small (AGIFT is ~500 terms) and you want zero infrastructure.

```bash
pip install cogdb
```

CogDB stores triples (`node → edge → node`) to local files. The AGIFT pipeline currently targets Neo4j, so using CogDB requires writing a thin adapter that maps `PARENT_OF`/`SIMILAR_TO` edges to CogDB's `put(source, edge, dest)` API. See the [CogDB README](https://github.com/arun1729/cog) for the query API.

## Install extras

| Install | What you get | Size |
|---------|-------------|------|
| `pip install agift-graph` | Neo4j driver + fetch + graph build | Lightweight |
| `pip install agift-graph[embeddings]` | + sentence-transformers + torch | ~2 GB |
| `pip install agift-graph[isaacus]` | + Isaacus API client | Small |
| `pip install agift-graph[all]` | Everything | ~2 GB |

## Embedding providers

| Provider | Cost | Dimensions | Setup |
|----------|------|-----------|-------|
| local (sentence-transformers) | Free | 384, 768 | Nothing — runs on CPU |
| isaacus (kanon-2-embedder) | Paid | 256–1792 | Set API key in dashboard |

The local provider uses `all-MiniLM-L6-v2` (384d) or `all-mpnet-base-v2` (768d). Models are downloaded on first run and cached.

## Programmatic usage

```python
from agift import run_pipeline

# Run the full pipeline from Python code
run_pipeline(provider="local", dimension=384)

# Or with explicit Neo4j connection
run_pipeline(
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="changeme",
    skip_embed=True,
)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `changeme` | Neo4j password |
| `ISAACUS_API_KEY` | (empty) | Isaacus API key (optional) |

All other settings (dimension, provider, similarity threshold, semantic edge weight) are configured via the dashboard UI and stored in Neo4j.

## Full Docker stack

The included `docker-compose.yml` runs Neo4j, the dashboard, and a cron worker:

```bash
docker compose up -d --build
```

Then open the dashboard at http://localhost:5050 and click "Full Pipeline" or "Graph Only".

| Service | Port | Description |
|---------|------|-------------|
| Neo4j Browser | 7474 | Graph database UI |
| Neo4j Bolt | 7687 | Database protocol |
| Dashboard | 5050 | Config, run controls, logs |
| Worker | — | Cron-scheduled pipeline runs |

## CLI usage

```bash
# Full pipeline (fetch + graph + embed + semantic edges)
agift

# Graph only (no embeddings)
agift --skip-embed --skip-semantic

# Local embeddings, 384 dimensions
agift --provider local --dimension 384

# Force re-embed all terms
agift --force-embed

# Custom similarity threshold for semantic edges
agift --threshold 0.65

# Faster run: skip alt label fetching
agift --skip-alt

# Dry run (fetch from API, no writes)
agift --dry-run
```

## Project structure

```
agift/
├── __init__.py              # Public API exports
├── cli.py                   # CLI entry point + run_pipeline()
├── common.py                # Constants, Neo4j helpers, logging
├── fetch.py                 # TemaTres API fetching
├── graph.py                 # Schema setup + node/edge upsert
├── embed.py                 # Embedding providers (local + Isaacus)
├── link.py                  # Cosine similarity + semantic edges
docker-compose.yml           # Full stack (Neo4j + dashboard + worker)
dashboard/
├── app.py                   # Flask dashboard + run controls
├── templates/index.html
worker/
├── Dockerfile
├── entrypoint.sh            # Cron scheduler + manual trigger
import_agift.py              # Backward-compatible entry point
pyproject.toml
LICENSE                      # Apache 2.0
```

## Data source

AGIFT is maintained by the National Archives of Australia and published via TemaTres at https://vocabularyserver.com/agift/

## License

Apache 2.0 — see [LICENSE](LICENSE).
