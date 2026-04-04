# AGIFT Graph Docker Images

Australian Government Interactive Functions Thesaurus (AGIFT) as a knowledge graph with embeddings and dual edge types.

## Available Images

### `deepcivic/agift-dashboard`
**Port:** 5050  
**Description:** Flask web dashboard for configuring and running the AGIFT graph pipeline. Provides UI for managing embeddings, triggering runs, and viewing logs.

### `deepcivic/agift-worker`
**Description:** Background worker for processing AGIFT data, generating embeddings, and creating semantic similarity edges. Runs on a cron schedule or can be triggered manually.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/DeepCivic/AGIFT-graph-builder
cd AGIFT-graph-builder

# Start the full stack
docker compose up -d --build
```

Then open the dashboard at http://localhost:5050

## Docker Compose Services

| Service | Image | Port | Description |
|---------|-------|------|-------------|
| Neo4j | `neo4j:5-community` | 7474, 7687 | Graph database |
| Dashboard | `deepcivic/agift-dashboard` | 5050 | Web interface |
| Worker | `deepcivic/agift-worker` | - | Background processing |

## What It Does

Fetches the full AGIFT vocabulary from the [TemaTres API](https://vocabularyserver.com/agift/), builds a graph with structural hierarchy edges, generates embeddings (free local or Isaacus API), then creates semantic similarity edges between related terms.

```
TemaTres API ──►  Graph ──► Embeddings ──► Semantic Edges
  (AGIFT)        (PARENT_OF)     (384/512/768d)  (SIMILAR_TO)
```

## Graph Model

Two edge types with different weights for query-time flexibility:

| Edge | Type | Weight | Description |
|------|------|--------|-------------|
| `PARENT_OF` | structural | 1.0 | AGIFT hierarchy (L1 → L2 → L3) |
| `SIMILAR_TO` | semantic | 0.5 | Cosine similarity above threshold |

## Configuration

### Environment Variables

**Dashboard:**
- `BACKEND_TYPE`: `neo4j` (default) or `cogdb`
- `NEO4J_URI`: `bolt://neo4j:7687` (default)
- `NEO4J_USER`: `neo4j` (default)
- `NEO4J_PASSWORD`: `changeme` (default)

**Worker:**
- Same as dashboard plus:
- `TRANSFORMERS_CACHE`: `/app/models` (model cache volume)

### Volumes
- `neo4j_data`: Neo4j database storage
- `model_cache`: Cached embedding models

## Embedding Providers

| Provider | Cost | Dimensions | Setup |
|----------|------|-----------|-------|
| local (sentence-transformers) | Free | 384, 768 | Nothing — runs on CPU |
| isaacus (kanon-2-embedder) | Paid | 256–1792 | Set API key in dashboard |

## Usage Examples

### Standalone Dashboard
```bash
docker run -p 5050:5050 \
  -e NEO4J_URI=bolt://your-neo4j:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=yourpassword \
  deepcivic/agift-dashboard:latest
```

### Standalone Worker
```bash
docker run \
  -e NEO4J_URI=bolt://your-neo4j:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=yourpassword \
  -v model_cache:/app/models \
  deepcivic/agift-worker:latest
```

## Development

### Building Images Locally
```bash
# Build dashboard
docker build -t deepcivic/agift-dashboard:local -f dashboard/Dockerfile .

# Build worker
docker build -t deepcivic/agift-worker:local -f worker/Dockerfile .
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

---

*This description is automatically updated from the project's README when new Docker images are published.*