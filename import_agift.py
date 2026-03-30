"""
Import AGIFT vocabulary into Neo4j graph with embeddings and semantic edges.

Thin CLI entry point — pipeline logic lives in the agift/ package.

Usage:
    python import_agift.py
    python import_agift.py --dry-run
    python import_agift.py --skip-embed
    python import_agift.py --force-embed
    python import_agift.py --skip-semantic

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
    VALID_DIMENSIONS,
    VALID_PROVIDERS,
    get_config_from_neo4j,
    get_neo4j_driver,
    log_run,
    print_summary,
)
from agift.fetch import fetch_full_hierarchy
from agift.graph import ensure_schema, upsert_graph
from agift.embed import embed_terms, embed_terms_local
from agift.link import build_semantic_edges


def main():
    """CLI entry point for AGIFT import pipeline."""
    parser = argparse.ArgumentParser(
        description="Import AGIFT vocabulary into Neo4j graph with embeddings"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch from API but don't write to Neo4j")
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

    started_at = datetime.now(timezone.utc).isoformat()
    run_details = {"started_at": started_at}

    print("=" * 60)
    print("AGIFT Vocabulary Import (Neo4j + Embeddings + Semantic Edges)")
    print("=" * 60)
    print(f"Source: {TEMATRES_BASE}")
    print()

    # Stage 1: Fetch from TemaTres
    start = time.time()
    terms = fetch_full_hierarchy(include_alts=not args.skip_alt)
    elapsed = time.time() - start
    print(f"\nFetched {len(terms)} terms in {elapsed:.1f}s")
    run_details["fetched"] = len(terms)

    total_alts = sum(len(t.alt_labels) for t in terms)
    print(f"Total alt labels: {total_alts}")

    if args.dry_run:
        print("\n[DRY RUN] Skipping Neo4j write and embedding.")
        for t in terms[:10]:
            alts = f" (alts: {', '.join(t.alt_labels)})" if t.alt_labels else ""
            print(f"  L{t.depth} [{t.dcat_theme}] {t.label}{alts}")
        print(f"  ... and {len(terms) - 10} more")
        return

    # Connect to Neo4j
    print("\nConnecting to Neo4j...")
    try:
        driver = get_neo4j_driver()
        driver.verify_connectivity()
    except Exception as e:
        print(f"ERROR: Cannot connect to Neo4j: {e}")
        sys.exit(1)

    try:
        # Stage 2: Build graph (structural edges)
        print("\nStage 2: Building graph (structural edges)...")
        ensure_schema(driver)
        graph_stats = upsert_graph(driver, terms)
        print(f"  Created: {graph_stats['created']}")
        print(f"  Updated: {graph_stats['updated']}")
        print(f"  Unchanged: {graph_stats['unchanged']}")
        run_details.update({
            "created": graph_stats["created"],
            "updated": graph_stats["updated"],
            "unchanged": graph_stats["unchanged"],
        })

        # Stage 3: Embed
        if args.skip_embed:
            print("\nStage 3: Skipped (--skip-embed)")
            run_details["embedded"] = 0
            run_details["embed_failed"] = 0
            run_details["embedding_provider"] = ""
        else:
            config = get_config_from_neo4j(driver)
            provider = args.provider or config["embedding_provider"]
            dimension = args.dimension or config["embedding_dimension"]
            run_details["embedding_provider"] = provider

            # Determine which term IDs to embed
            if args.force_embed:
                with driver.session() as session:
                    result = session.run(
                        "MATCH (t:Term) RETURN t.term_id AS tid"
                    )
                    embed_ids = [r["tid"] for r in result]
            else:
                embed_ids = graph_stats["changed_ids"]

            if not embed_ids:
                print("\nStage 3: No terms need embedding")
                run_details["embedded"] = 0
                run_details["embed_failed"] = 0
            elif provider == PROVIDER_LOCAL:
                print(f"\nStage 3: Local embedding {len(embed_ids)} terms "
                      f"(dimension={dimension})...")
                embed_stats = embed_terms_local(driver, embed_ids, dimension)
                print(f"  Embedded: {embed_stats['embedded']}")
                print(f"  Failed:   {embed_stats['failed']}")
                run_details["embedded"] = embed_stats["embedded"]
                run_details["embed_failed"] = embed_stats["failed"]
            else:
                # Isaacus provider
                api_key = config["isaacus_api_key"] or os.environ.get("ISAACUS_API_KEY")
                if not api_key:
                    print("\nStage 3: Skipped (no Isaacus API key configured)")
                    print("  Set via dashboard, or use --provider local")
                    run_details["embedded"] = 0
                    run_details["embed_failed"] = 0
                else:
                    print(f"\nStage 3: Isaacus embedding {len(embed_ids)} terms "
                          f"(dimension={dimension})...")
                    embed_stats = embed_terms(driver, embed_ids, api_key, dimension)
                    print(f"  Embedded: {embed_stats['embedded']}")
                    print(f"  Failed:   {embed_stats['failed']}")
                    run_details["embedded"] = embed_stats["embedded"]
                    run_details["embed_failed"] = embed_stats["failed"]

        # Stage 4: Semantic edges
        if args.skip_semantic:
            print("\nStage 4: Skipped (--skip-semantic)")
            run_details["semantic_edges_created"] = 0
        else:
            config = get_config_from_neo4j(driver)
            threshold = args.threshold or config["similarity_threshold"]
            sem_weight = config["semantic_edge_weight"]

            print(f"\nStage 4: Building semantic edges "
                  f"(threshold={threshold}, weight={sem_weight})...")
            sem_stats = build_semantic_edges(driver, threshold, sem_weight)
            print(f"  Created:            {sem_stats['created']}")
            print(f"  Skipped (structural): {sem_stats['skipped_structural']}")
            print(f"  Below threshold:    {sem_stats['below_threshold']}")
            run_details["semantic_edges_created"] = sem_stats["created"]

        print_summary(driver)
        log_run(driver, "success", run_details)

    except Exception as e:
        print(f"\nERROR: {e}")
        run_details["error"] = str(e)
        try:
            log_run(driver, "error", run_details)
        except Exception:
            pass
        sys.exit(1)
    finally:
        driver.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
