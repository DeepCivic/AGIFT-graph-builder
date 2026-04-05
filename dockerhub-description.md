# AGIFT Graph

Australian Government Interactive Functions Thesaurus (AGIFT) as a knowledge graph with embeddings and dual edge types.

## Image: `deepcivic/agift`

A unified container that runs the dashboard, pipeline worker, or CLI depending on the `AGIFT_MODE` environment variable.

| Mode | Description |
|------|-------------|
| `dashboard` (default) | Gunicorn web server on port 5050 + optional cron |
| `worker` | Cron-scheduled pipeline runs only, no web server |
| `cli` | Run the pipeline once and exit |

## Quick Start

```bash
# Clone the repository
git clone https://github.com/DeepCivic/AGIFT-graph-builder
cd AGIFT-graph-builder

# Start the full stack (Neo4j + AGIFT dashboard/worker)
docker compose up -d --build
```

Then open the dashboard at http://localhost:5050

## Docker Compose Services

| Service | Image | Port | Description |
|---------|-------|------|-------------|
| Neo4j | `neo4j:5-community` | 7474, 7687 | Graph database |
| AGIFT | `deepcivic/agift` | 5050 | Dashboard + pipeline + cron |

## What It Does

Fetches the full AGIFT vocabulary from the [TemaTres API](https://vocabularyserver.com/agift/), builds a graph with structural hierarchy edges, generates embeddings (free local or Isaacus API), then creates semantic similarity edges between related terms.

```
TemaTres API ──►  Graph ──► Embeddings ──► Semantic Edges
  (AGIFT)        (PARENT_OF)     (384/512/768d)  (SIMILAR_TO)
```

## Graph Model

| Edge | Type | Weight | Description |
|------|------|--------|-------------|
| `PARENT_OF` | structural | 1.0 | AGIFT hierarchy (L1 → L2 → L3) |
| `SIMILAR_TO` | semantic | 0.5 | Cosine similarity above threshold |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGIFT_MODE` | `dashboard` | Container mode: `dashboard`, `worker`, `cli` |
| `AGIFT_CRON_ENABLED` | `1` | Enable weekly cron in dashboard mode |
| `BACKEND_TYPE` | `neo4j` | Graph backend: `neo4j` or `cogdb` |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `changeme` | Neo4j password |
| `TRANSFORMERS_CACHE` | `/app/models` | Model cache directory |

### Volumes
- `neo4j_data`: Neo4j database storage
- `model_cache`: Cached embedding models

## Embedding Providers

| Provider | Cost | Dimensions | Setup |
|----------|------|-----------|-------|
| local (sentence-transformers) | Free | 384, 768 | Nothing — runs on CPU |
| isaacus (kanon-2-embedder) | Paid | 256–1792 | Set API key in dashboard |

## Usage Examples

### Dashboard mode (default)
```bash
docker run -p 5050:5050 \
  -e NEO4J_URI=bolt://your-neo4j:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=yourpassword \
  deepcivic/agift:latest
```

### Worker mode (cron only)
```bash
docker run \
  -e AGIFT_MODE=worker \
  -e NEO4J_URI=bolt://your-neo4j:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=yourpassword \
  -v model_cache:/app/models \
  deepcivic/agift:latest
```

### CLI mode (one-shot)
```bash
docker run --rm \
  -e AGIFT_MODE=cli \
  -e BACKEND_TYPE=cogdb \
  deepcivic/agift:latest --dry-run
```

## Development

### Building locally
```bash
docker build -t deepcivic/agift:local .
```

## Source Code

- **GitHub:** https://github.com/DeepCivic/AGIFT-graph-builder
- **PyPI:** https://pypi.org/project/agift-graph/
- **Issues:** https://github.com/DeepCivic/AGIFT-graph-builder/issues

## License

Apache 2.0 — see [LICENSE](https://github.com/DeepCivic/AGIFT-graph-builder/blob/main/LICENSE).

## Data Source

AGIFT is maintained by the National Archives of Australia and published via TemaTres at https://vocabularyserver.com/agift/

## Changelog

See [CHANGELOG.md](https://github.com/DeepCivic/AGIFT-graph-builder/blob/main/CHANGELOG.md) for version history.
