"""
CLI entry point for AGIFT import pipeline.

Usage (via pip install):
    agift
    agift --dry-run
    agift --skip-embed
    agift --force-embed
    agift --skip-semantic
    agift --backend cogdb

Usage (direct):
    python -m agift
    python import_agift.py

Source: https://vocabularyserver.com/agift/services.php
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

from agift.common import (
    PROVIDER_ISAACUS,
    PROVIDER_LOCAL,
    TEMATRES_BASE,
    VALID_BACKENDS,
    VALID_DIMENSIONS,
    VALID_PROVIDERS,
    create_backend,
    print_summary,
)
from agift.fetch import fetch_full_hierarchy
from agift.graph import ensure_schema, upsert_graph
from agift.embed import embed_terms, embed_terms_local
from agift.link import build_semantic_edges


def run_pipeline(
    provider=None,
    dimension=None,
    skip_embed=False,
    skip_semantic=False,
    force_embed=False,
    skip_alt=False,
    dry_run=False,
    threshold=None,
    backend_type="neo4j",
    neo4j_uri=None,
    neo4j_user=None,
    neo4j_password=None,
    cogdb_data_dir=None,
):
    """Run the AGIFT import pipeline programmatically.

    Args:
        provider: Embedding provider ("isaacus" or "local"). None uses config.
        dimension: Embedding dimension. None uses config.
        skip_embed: Skip embedding generation.
        skip_semantic: Skip semantic edge generation.
        force_embed: Re-embed all terms, not just new/changed.
        skip_alt: Skip fetching alt labels.
        dry_run: Fetch only, don't write to the graph.
        threshold: Cosine similarity threshold for semantic edges.
        backend_type: Graph backend — "neo4j" (default) or "cogdb".
        neo4j_uri: Neo4j connection URI. None uses env/default.
        neo4j_user: Neo4j username. None uses env/default.
        neo4j_password: Neo4j password. None uses env/default.
        cogdb_data_dir: CogDB data directory. None uses env/default.

    Returns:
        Dict with run details and stats.

    Raises:
        RuntimeError: If backend connection fails.
    """
    # Allow env-var overrides for Neo4j (backward compat)
    if neo4j_uri is not None:
        os.environ["NEO4J_URI"] = neo4j_uri
    if neo4j_user is not None:
        os.environ["NEO4J_USER"] = neo4j_user
    if neo4j_password is not None:
        os.environ["NEO4J_PASSWORD"] = neo4j_password

    started_at = datetime.now(timezone.utc).isoformat()
    run_details = {"started_at": started_at}

    backend_label = "Neo4j" if backend_type == "neo4j" else "CogDB"
    print("=" * 60)
    print(f"AGIFT Vocabulary Import ({backend_label} + Embeddings + Semantic Edges)")
    print("=" * 60)
    print(f"Source: {TEMATRES_BASE}")
    print()

    # Stage 1: Fetch from TemaTres
    start = time.time()
    terms = fetch_full_hierarchy(include_alts=not skip_alt)
    elapsed = time.time() - start
    print(f"\nFetched {len(terms)} terms in {elapsed:.1f}s")
    run_details["fetched"] = len(terms)

    total_alts = sum(len(t.alt_labels) for t in terms)
    print(f"Total alt labels: {total_alts}")

    if dry_run:
        print("\n[DRY RUN] Skipping graph write and embedding.")
        for t in terms[:10]:
            alts = f" (alts: {', '.join(t.alt_labels)})" if t.alt_labels else ""
            print(f"  L{t.depth} [{t.dcat_theme}] {t.label}{alts}")
        print(f"  ... and {len(terms) - 10} more")
        return run_details

    # Connect to backend
    print(f"\nConnecting to {backend_label}...")
    backend = create_backend(
        backend_type,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        cogdb_data_dir=cogdb_data_dir,
    )

    # For Neo4j, verify connectivity
    if backend_type == "neo4j":
        from agift.neo4j_backend import Neo4jBackend
        if isinstance(backend, Neo4jBackend):
            backend.driver.verify_connectivity()

    try:
        # Stage 2: Build graph (structural edges)
        print("\nStage 2: Building graph (structural edges)...")
        ensure_schema(backend)
        graph_stats = upsert_graph(backend, terms)
        print(f"  Created: {graph_stats['created']}")
        print(f"  Updated: {graph_stats['updated']}")
        print(f"  Unchanged: {graph_stats['unchanged']}")
        run_details.update({
            "created": graph_stats["created"],
            "updated": graph_stats["updated"],
            "unchanged": graph_stats["unchanged"],
        })

        # Stage 3: Embed
        if skip_embed:
            print("\nStage 3: Skipped (--skip-embed)")
            run_details["embedded"] = 0
            run_details["embed_failed"] = 0
            run_details["embedding_provider"] = ""
        else:
            config = backend.get_config()
            eff_provider = provider or config["embedding_provider"]
            eff_dimension = dimension or config["embedding_dimension"]
            run_details["embedding_provider"] = eff_provider

            # Determine which term IDs to embed
            if force_embed:
                embed_ids = backend.get_all_term_ids()
            else:
                embed_ids = graph_stats["changed_ids"]

            if not embed_ids:
                print("\nStage 3: No terms need embedding")
                run_details["embedded"] = 0
                run_details["embed_failed"] = 0
            elif eff_provider == PROVIDER_LOCAL:
                print(f"\nStage 3: Local embedding {len(embed_ids)} terms "
                      f"(dimension={eff_dimension})...")
                embed_stats = embed_terms_local(backend, embed_ids, eff_dimension)
                print(f"  Embedded: {embed_stats['embedded']}")
                print(f"  Failed:   {embed_stats['failed']}")
                run_details["embedded"] = embed_stats["embedded"]
                run_details["embed_failed"] = embed_stats["failed"]
            else:
                # Isaacus provider
                api_key = (config["isaacus_api_key"]
                           or os.environ.get("ISAACUS_API_KEY"))
                if not api_key:
                    print("\nStage 3: Skipped (no Isaacus API key configured)")
                    print("  Set via dashboard, or use --provider local")
                    run_details["embedded"] = 0
                    run_details["embed_failed"] = 0
                else:
                    print(f"\nStage 3: Isaacus embedding {len(embed_ids)} terms "
                          f"(dimension={eff_dimension})...")
                    embed_stats = embed_terms(
                        backend, embed_ids, api_key, eff_dimension
                    )
                    print(f"  Embedded: {embed_stats['embedded']}")
                    print(f"  Failed:   {embed_stats['failed']}")
                    run_details["embedded"] = embed_stats["embedded"]
                    run_details["embed_failed"] = embed_stats["failed"]

        # Stage 4: Semantic edges
        if skip_semantic:
            print("\nStage 4: Skipped (--skip-semantic)")
            run_details["semantic_edges_created"] = 0
        else:
            config = backend.get_config()
            eff_threshold = threshold or config["similarity_threshold"]
            sem_weight = config["semantic_edge_weight"]

            print(f"\nStage 4: Building semantic edges "
                  f"(threshold={eff_threshold}, weight={sem_weight})...")
            sem_stats = build_semantic_edges(backend, eff_threshold, sem_weight)
            print(f"  Created:            {sem_stats['created']}")
            print(f"  Skipped (structural): {sem_stats['skipped_structural']}")
            print(f"  Below threshold:    {sem_stats['below_threshold']}")
            run_details["semantic_edges_created"] = sem_stats["created"]

        print_summary(backend)
        backend.log_run("success", run_details)

    except Exception as e:
        print(f"\nERROR: {e}")
        run_details["error"] = str(e)
        try:
            backend.log_run("error", run_details)
        except Exception:
            pass
        raise
    finally:
        backend.close()

    print("\nDone.")
    return run_details


def main():
    """CLI entry point for AGIFT import pipeline."""
    parser = argparse.ArgumentParser(
        description="Import AGIFT vocabulary into a graph with embeddings"
    )
    parser.add_argument("--backend", choices=list(VALID_BACKENDS),
                        default="neo4j",
                        help="Graph backend: neo4j (default) or cogdb")
    parser.add_argument("--cogdb-dir", default=None,
                        help="CogDB data directory (default: agift_cogdb_data)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch from API but don't write to graph")
    parser.add_argument("--skip-alt", action="store_true",
                        help="Skip fetching alt labels (faster)")
    parser.add_argument("--skip-embed", action="store_true",
                        help="Skip embedding generation")
    parser.add_argument("--force-embed", action="store_true",
                        help="Re-embed all terms, not just new/changed")
    parser.add_argument("--skip-semantic", action="store_true",
                        help="Skip semantic edge generation")
    parser.add_argument("--provider", choices=list(VALID_PROVIDERS),
                        help="Override embedding provider (isaacus or local)")
    parser.add_argument("--dimension", type=int, choices=list(VALID_DIMENSIONS),
                        help="Override embedding dimension")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Cosine similarity threshold for semantic edges")
    args = parser.parse_args()

    try:
        run_pipeline(
            provider=args.provider,
            dimension=args.dimension,
            skip_embed=args.skip_embed,
            skip_semantic=args.skip_semantic,
            force_embed=args.force_embed,
            skip_alt=args.skip_alt,
            dry_run=args.dry_run,
            threshold=args.threshold,
            backend_type=args.backend,
            cogdb_data_dir=args.cogdb_dir,
        )
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
