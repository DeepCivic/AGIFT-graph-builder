"""AGIFT Graph Builder — modular ETL pipeline with pluggable graph backends."""

from agift.backend import GraphBackend
from agift.common import (
    AGIFT_TOP_TO_DCAT,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_PROVIDER,
    LOCAL_MODELS,
    PROVIDER_ISAACUS,
    PROVIDER_LOCAL,
    SEMANTIC_EDGE_WEIGHT,
    SIMILARITY_THRESHOLD,
    STRUCTURAL_EDGE_WEIGHT,
    TEMATRES_BASE,
    VALID_BACKENDS,
    VALID_DIMENSIONS,
    VALID_PROVIDERS,
    create_backend,
    get_config_from_neo4j,
    get_neo4j_driver,
    log_run,
    print_summary,
)
from agift.fetch import AgiftTerm, fetch_full_hierarchy
from agift.graph import ensure_schema, upsert_graph
from agift.embed import build_hierarchical_text, embed_terms, embed_terms_local
from agift.link import build_semantic_edges
from agift.cli import run_pipeline

__all__ = [
    "AGIFT_TOP_TO_DCAT",
    "AgiftTerm",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_PROVIDER",
    "GraphBackend",
    "LOCAL_MODELS",
    "PROVIDER_ISAACUS",
    "PROVIDER_LOCAL",
    "SEMANTIC_EDGE_WEIGHT",
    "SIMILARITY_THRESHOLD",
    "STRUCTURAL_EDGE_WEIGHT",
    "TEMATRES_BASE",
    "VALID_BACKENDS",
    "VALID_DIMENSIONS",
    "VALID_PROVIDERS",
    "build_hierarchical_text",
    "build_semantic_edges",
    "create_backend",
    "embed_terms",
    "embed_terms_local",
    "ensure_schema",
    "fetch_full_hierarchy",
    "get_config_from_neo4j",
    "get_neo4j_driver",
    "log_run",
    "print_summary",
    "run_pipeline",
    "upsert_graph",
]
