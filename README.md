# AGIFT Graph

Australian Government Interactive Functions Thesaurus (AGIFT) as a knowledge graph with embeddings and dual edge types.

## What it does

Fetches the full AGIFT vocabulary from the [TemaTres API](https://vocabularyserver.com/agift/), builds a graph with structural hierarchy edges, generates embeddings (free local or Isaacus API), then creates semantic similarity edges between related terms.

```
TemaTres API ──►  Graph ──► Embeddings ──► Semantic Edges
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

[CogDB](https://github.com/arun1729/cog) is a persistent embedded graph database written in pure Python. No server process, no Docker — data is stored to local files.

```bash
pip install agift-graph[cogdb]
agift --backend cogdb                # stores graph in ./agift_cogdb_data/
agift --backend cogdb --cogdb-dir /path/to/data
```

The pipeline runs identically to Neo4j — same fetch, embed, and semantic edge stages. CogDB terms, edges, and embeddings are stored as triples with JSON property blobs. Set `COGDB_DATA_DIR` as an environment variable or pass `--cogdb-dir` to control the storage location.

## Install extras

| Install | What you get | Size |
|---------|-------------|------|
| `pip install agift-graph` | Neo4j driver + fetch + graph build | Lightweight |
| `pip install agift-graph[cogdb]` | + CogDB embedded graph backend | Small |
| `pip install agift-graph[embeddings]` | + sentence-transformers + torch | ~2 GB |
| `pip install agift-graph[isaacus]` | + Isaacus API client | Small |
| `pip install agift-graph[all]` | Everything (Neo4j + CogDB + embeddings + Isaacus) | ~2 GB |

## Embedding providers

| Provider | Cost | Dimensions | Setup |
|----------|------|-----------|-------|
| local (sentence-transformers) | Free | 384, 768 | Nothing — runs on CPU |
| isaacus (kanon-2-embedder) | Paid | 256–1792 | Set API key in dashboard |

The local provider uses `all-MiniLM-L6-v2` (384d) or `all-mpnet-base-v2` (768d). Models are downloaded on first run and cached.

## Programmatic usage

```python
from agift import run_pipeline

# Run the full pipeline with Neo4j (default)
run_pipeline(provider="local", dimension=384)

# Explicit Neo4j connection
run_pipeline(
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="changeme",
    skip_embed=True,
)

# Use CogDB instead of Neo4j
run_pipeline(backend_type="cogdb", provider="local", dimension=384)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `changeme` | Neo4j password |
| `COGDB_DATA_DIR` | `agift_cogdb_data` | CogDB storage directory |
| `ISAACUS_API_KEY` | (empty) | Isaacus API key (optional) |

All other settings (dimension, provider, similarity threshold, semantic edge weight) are configured via the dashboard UI and stored in the graph backend.

## Full Docker stack

The included `docker-compose.yml` runs Neo4j and the AGIFT container (dashboard + cron worker):

```bash
docker compose up -d --build
```

Then open the dashboard at http://localhost:5050 and click "Full Pipeline" or "Graph Only".

| Service | Port | Description |
|---------|------|-------------|
| Neo4j Browser | 7474 | Graph database UI |
| Neo4j Bolt | 7687 | Database protocol |
| AGIFT | 5050 | Dashboard, pipeline runner, cron worker |

The `AGIFT_MODE` env var controls container behaviour:

| Mode | Description |
|------|-------------|
| `dashboard` (default) | Gunicorn web server + optional cron |
| `worker` | Cron only, no web server |
| `cli` | Run pipeline once and exit |

## CLI usage

```bash
# Full pipeline (fetch + graph + embed + semantic edges)
agift

# Use CogDB instead of Neo4j
agift --backend cogdb
agift --backend cogdb --cogdb-dir /path/to/data

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
├── backend.py               # GraphBackend abstract interface
├── neo4j_backend.py         # Neo4j backend implementation
├── cogdb_backend.py         # CogDB backend implementation
├── cli.py                   # CLI entry point + run_pipeline()
├── common.py                # Constants, backend factory, summary
├── fetch.py                 # TemaTres API fetching (concurrent)
├── graph.py                 # Schema setup + node/edge upsert
├── embed.py                 # Embedding providers (local + Isaacus)
├── link.py                  # Cosine similarity + semantic edges
Dockerfile                   # Unified image (dashboard + worker + CLI)
entrypoint.sh                # Container mode dispatch
docker-compose.yml           # Full stack (Neo4j + AGIFT container)
dashboard/
├── app.py                   # Flask dashboard + in-process pipeline
├── templates/index.html
import_agift.py              # Backward-compatible entry point
pyproject.toml
CHANGELOG.md                 # Version history (release notes source)
release.sh                   # Version bump + tag helper
LICENSE                      # Apache 2.0
```

## Data source

AGIFT is maintained by the National Archives of Australia and published via TemaTres at https://vocabularyserver.com/agift/

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Publishing

This project uses a tag-based release workflow with a single CI definition:

- `ci.yml` is the single source of truth for lint, test, and Docker checks
- `publish.yml` calls `ci.yml` as a reusable workflow — no duplicated jobs

Pipeline sequence on tag push:
1. CI runs (lint + test + Docker tests)
2. Build PyPI package
3. Publish to PyPI
4. Build and push Docker image to Docker Hub (`deepcivic/agift`)
5. Create GitHub Release with changelog entry

To release:
1. Update `CHANGELOG.md` with a new version entry
2. Run `./release.sh 0.2.0` (updates `pyproject.toml`, commits, tags)
3. Push: `git push origin main --tags`

Secrets required in GitHub repo settings:
- `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (repo-level secrets)
- PyPI trusted publishing is configured via OIDC (no secret needed)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.