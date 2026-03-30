"""Shared constants, Neo4j helpers, and run logging."""

import os
from datetime import datetime, timezone

from neo4j import GraphDatabase


# ---------------------------------------------------------------------------
# AGIFT top-level function → DCAT-AP theme mapping
# ---------------------------------------------------------------------------
AGIFT_TOP_TO_DCAT: dict[str, str] = {
    "business support and regulation": "ENTR",
    "civic infraestructure": "REGI",  # sic — typo in AGIFT source
    "communications": "INTE",
    "community services": "SOCI",
    "cultural affairs": "CULT",
    "defence": "JUST",
    "education and training": "EDUC",
    "employment": "ECON",
    "environment": "ENVI",
    "finance management": "ECON",
    "governance": "GOVE",
    "health care": "HEAL",
    "immigration": "MIGR",
    "indigenous affairs": "SOCI",
    "international relations": "INTR",
    "justice administration": "JUST",
    "maritime services": "TRAN",
    "natural resources": "ENVI",
    "primary industries": "AGRI",
    "science": "TECH",
    "security": "JUST",
    "sport and recreation": "CULT",
    "statistical services": "GOVE",
    "tourism": "CULT",
    "trade": "ECON",
    "transport": "TRAN",
}

TEMATRES_BASE = "https://vocabularyserver.com/agift/services.php"
VALID_DIMENSIONS = (256, 384, 512, 768, 1024, 1792)

# Embedding provider constants
PROVIDER_ISAACUS = "isaacus"
PROVIDER_LOCAL = "local"
VALID_PROVIDERS = (PROVIDER_ISAACUS, PROVIDER_LOCAL)

# Local sentence-transformers model map: dimension → model name
LOCAL_MODELS: dict[int, str] = {
    384: "all-MiniLM-L6-v2",
    768: "all-mpnet-base-v2",
}

# Semantic edge defaults
SIMILARITY_THRESHOLD = 0.70
SEMANTIC_EDGE_WEIGHT = 0.5
STRUCTURAL_EDGE_WEIGHT = 1.0


# ---------------------------------------------------------------------------
# Neo4j connection helpers
# ---------------------------------------------------------------------------

def get_neo4j_driver():
    """Create Neo4j driver from environment variables.

    Returns:
        Neo4j driver instance.

    Raises:
        RuntimeError: If connection fails.
    """
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    return GraphDatabase.driver(uri, auth=(user, password))


def get_config_from_neo4j(driver) -> dict:
    """Read dashboard config (API key, dimension, provider) from Neo4j.

    Args:
        driver: Neo4j driver.

    Returns:
        Dict with isaacus_api_key, embedding_dimension, embedding_provider,
        similarity_threshold, and semantic_edge_weight.
    """
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Config {name: 'agift'}) "
            "RETURN c.isaacus_api_key AS key, "
            "       c.embedding_dimension AS dim, "
            "       c.embedding_provider AS provider, "
            "       c.similarity_threshold AS sim_thresh, "
            "       c.semantic_edge_weight AS sem_weight"
        )
        record = result.single()
        if record:
            return {
                "isaacus_api_key": record["key"],
                "embedding_dimension": record["dim"] or 512,
                "embedding_provider": record["provider"] or PROVIDER_ISAACUS,
                "similarity_threshold": record["sim_thresh"] or SIMILARITY_THRESHOLD,
                "semantic_edge_weight": record["sem_weight"] or SEMANTIC_EDGE_WEIGHT,
            }
    return {
        "isaacus_api_key": None,
        "embedding_dimension": 512,
        "embedding_provider": PROVIDER_ISAACUS,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "semantic_edge_weight": SEMANTIC_EDGE_WEIGHT,
    }


# ---------------------------------------------------------------------------
# Run logging
# ---------------------------------------------------------------------------

def log_run(driver, status: str, details: dict) -> None:
    """Write a run log node to Neo4j for dashboard display.

    Args:
        driver: Neo4j driver.
        status: "success" or "error".
        details: Dict of run stats to store.
    """
    with driver.session() as session:
        session.run(
            """
            CREATE (r:RunLog {
                worker: 'agift',
                status: $status,
                started_at: datetime($started),
                finished_at: datetime(),
                terms_fetched: $fetched,
                terms_created: $created,
                terms_updated: $updated,
                terms_unchanged: $unchanged,
                terms_embedded: $embedded,
                terms_embed_failed: $embed_failed,
                embedding_provider: $provider,
                semantic_edges_created: $sem_created,
                error_message: $error
            })
            """,
            status=status,
            started=details.get("started_at", datetime.now(timezone.utc).isoformat()),
            fetched=details.get("fetched", 0),
            created=details.get("created", 0),
            updated=details.get("updated", 0),
            unchanged=details.get("unchanged", 0),
            embedded=details.get("embedded", 0),
            embed_failed=details.get("embed_failed", 0),
            provider=details.get("embedding_provider", ""),
            sem_created=details.get("semantic_edges_created", 0),
            error=details.get("error", ""),
        )

        # Prune old logs — keep last 20
        session.run(
            """
            MATCH (r:RunLog {worker: 'agift'})
            WITH r ORDER BY r.finished_at DESC
            SKIP 20
            DELETE r
            """
        )


def print_summary(driver) -> None:
    """Print a summary of the Neo4j graph state."""
    with driver.session() as session:
        result = session.run("MATCH (t:Term) RETURN count(t) AS total")
        total = result.single()["total"]

        result = session.run(
            "MATCH (t:Term) WHERE t.embedding IS NOT NULL RETURN count(t) AS embedded"
        )
        embedded = result.single()["embedded"]

        result = session.run(
            "MATCH (t:Term) RETURN t.depth AS depth, count(t) AS cnt ORDER BY depth"
        )
        by_depth = [(r["depth"], r["cnt"]) for r in result]

        result = session.run(
            "MATCH (t:Term) RETURN t.dcat_theme AS theme, count(t) AS cnt "
            "ORDER BY cnt DESC"
        )
        by_theme = [(r["theme"], r["cnt"]) for r in result]

        result = session.run("MATCH ()-[r:PARENT_OF]->() RETURN count(r) AS edges")
        structural_edges = result.single()["edges"]

        result = session.run("MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) AS edges")
        semantic_edges = result.single()["edges"]

    print(f"\n=== AGIFT Graph Summary ===")
    print(f"Total terms:       {total}")
    print(f"Embedded:          {embedded}")
    print(f"Structural edges:  {structural_edges} (PARENT_OF, weight=1.0)")
    print(f"Semantic edges:    {semantic_edges} (SIMILAR_TO, weight=0.5)")
    print(f"\nBy depth:")
    for depth, cnt in by_depth:
        print(f"  L{depth}: {cnt}")
    print(f"\nBy DCAT-AP theme:")
    for theme, cnt in by_theme:
        print(f"  {theme}: {cnt}")
