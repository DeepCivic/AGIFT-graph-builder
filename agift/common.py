"""Shared constants, backend factory, and summary output."""

import os

from agift.backend import GraphBackend


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

# Embedding defaults (single source of truth — not backend-specific)
DEFAULT_EMBEDDING_DIMENSION = 512
DEFAULT_EMBEDDING_PROVIDER = PROVIDER_ISAACUS

# Semantic edge defaults
SIMILARITY_THRESHOLD = 0.70
SEMANTIC_EDGE_WEIGHT = 0.5
STRUCTURAL_EDGE_WEIGHT = 1.0

# Valid backend names
VALID_BACKENDS = ("neo4j", "cogdb")


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def create_backend(
    backend_type: str = "neo4j",
    *,
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    cogdb_data_dir: str | None = None,
) -> GraphBackend:
    """Create a graph backend instance.

    Args:
        backend_type: ``"neo4j"`` or ``"cogdb"``.
        neo4j_uri: Neo4j connection URI (neo4j backend only).
        neo4j_user: Neo4j username (neo4j backend only).
        neo4j_password: Neo4j password (neo4j backend only).
        cogdb_data_dir: Data directory (cogdb backend only).

    Returns:
        A :class:`GraphBackend` instance.

    Raises:
        ValueError: If *backend_type* is not recognised.
    """
    if backend_type == "neo4j":
        from agift.neo4j_backend import Neo4jBackend
        return Neo4jBackend(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
    elif backend_type == "cogdb":
        from agift.cogdb_backend import CogDBBackend
        return CogDBBackend(data_dir=cogdb_data_dir)
    else:
        raise ValueError(
            f"Unknown backend {backend_type!r}. "
            f"Choose from: {', '.join(VALID_BACKENDS)}"
        )


# ---------------------------------------------------------------------------
# Legacy helpers (thin wrappers kept for backward compatibility)
# ---------------------------------------------------------------------------

def get_neo4j_driver():
    """Create a Neo4j driver from environment variables.

    Kept for backward compatibility with the dashboard and worker.
    New code should use :func:`create_backend` instead.
    """
    from neo4j import GraphDatabase
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "changeme")
    return GraphDatabase.driver(uri, auth=(user, password))


def get_config_from_neo4j(driver) -> dict:
    """Read dashboard config from Neo4j.

    Kept for backward compatibility with the dashboard.
    Pipeline code should use ``backend.get_config()`` instead.
    """
    from agift.neo4j_backend import Neo4jBackend
    return Neo4jBackend.from_driver(driver).get_config()


def log_run(driver, status: str, details: dict) -> None:
    """Write a run log node to Neo4j.

    Kept for backward compatibility with the dashboard.
    Pipeline code should use ``backend.log_run()`` instead.
    """
    from agift.neo4j_backend import Neo4jBackend
    Neo4jBackend.from_driver(driver).log_run(status, details)


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------

def print_summary(backend: GraphBackend) -> None:
    """Print a summary of the graph state."""
    stats = backend.get_summary_stats()

    print(f"\n=== AGIFT Graph Summary ===")
    print(f"Total terms:       {stats['total']}")
    print(f"Embedded:          {stats['embedded']}")
    print(f"Structural edges:  {stats['structural_edges']} "
          f"(PARENT_OF, weight=1.0)")
    print(f"Semantic edges:    {stats['semantic_edges']} "
          f"(SIMILAR_TO, weight=0.5)")
    print(f"\nBy depth:")
    for depth, cnt in stats["by_depth"]:
        print(f"  L{depth}: {cnt}")
    print(f"\nBy DCAT-AP theme:")
    for theme, cnt in stats["by_theme"]:
        print(f"  {theme}: {cnt}")
