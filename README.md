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

```bash
docker compose -f docker-compose.agift.yml up -d --build
```

Then open the dashboard at http://localhost:5050 and click "Full Pipeline" or "Graph Only".

## Embedding providers

| Provider | Cost | Dimensions | Setup |
|----------|------|-----------|-------|
| local (sentence-transformers) | Free | 384, 768 | Nothing — runs on CPU |
| isaacus (kanon-2-embedder) | Paid | 256–1792 | Set API key in dashboard |

The local provider uses `all-MiniLM-L6-v2` (384d) or `all-mpnet-base-v2` (768d). Models are downloaded on first run and cached in a Docker volume.

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
cp agift/.env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_PASSWORD` | `changeme` | Neo4j database password |
| `ISAACUS_API_KEY` | (empty) | Isaacus API key (optional) |

All other settings (dimension, provider, similarity threshold, semantic edge weight) are configured via the dashboard UI and stored in Neo4j.

## Services

| Service | Port | Description |
|---------|------|-------------|
| Neo4j Browser | 7474 | Graph database UI |
| Neo4j Bolt | 7687 | Database protocol |
| Dashboard | 5050 | Config, run controls, logs |

## CLI usage

```bash
# Full pipeline (fetch + graph + embed + semantic edges)
docker exec agift-worker python import_agift.py

# Graph only (no embeddings)
docker exec agift-worker python import_agift.py --skip-embed --skip-semantic

# Local embeddings, 384 dimensions
docker exec agift-worker python import_agift.py --provider local --dimension 384

# Force re-embed all terms
docker exec agift-worker python import_agift.py --force-embed

# Dry run (fetch from API, no writes)
docker exec agift-worker python import_agift.py --dry-run
```

## Docker Hub (no source code needed)

```bash
docker compose -f docker-compose.agift.hub.yml up -d
```

## Project structure

```
agift/
├── import_agift.py          # 4-stage pipeline (fetch/graph/embed/link)
├── dashboard/
│   ├── Dockerfile
│   ├── app.py               # Flask dashboard + run controls
│   └── templates/
│       └── index.html
├── worker/
│   ├── Dockerfile
│   └── entrypoint.sh        # Cron scheduler + manual trigger
├── .env.example
├── LICENSE                   # Apache 2.0
└── README.md
```

## Data source

AGIFT is maintained by the National Archives of Australia and published via TemaTres at https://vocabularyserver.com/agift/

## License

Apache 2.0 — see [LICENSE](LICENSE).
