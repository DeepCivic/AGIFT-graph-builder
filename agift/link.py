"""Stage 4: Link — build semantic similarity edges from embeddings."""

from agift.common import SEMANTIC_EDGE_WEIGHT, SIMILARITY_THRESHOLD


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Cosine similarity score between -1 and 1.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_semantic_edges(
    driver,
    threshold: float = SIMILARITY_THRESHOLD,
    weight: float = SEMANTIC_EDGE_WEIGHT,
) -> dict:
    """Build SIMILAR_TO edges between terms with similar embeddings.

    Computes pairwise cosine similarity for all embedded terms and
    creates edges where similarity exceeds the threshold. Skips pairs
    that already have a PARENT_OF edge (structural edges take priority).

    Only compares terms with the same embedding_dimension to avoid
    cross-dimension comparisons.

    Args:
        driver: Neo4j driver.
        threshold: Minimum cosine similarity to create an edge.
        weight: Edge weight for query-time weighting.

    Returns:
        Dict with created, skipped_structural, and below_threshold counts.
    """
    stats = {"created": 0, "skipped_structural": 0, "below_threshold": 0}

    # Fetch all embedded terms grouped by dimension
    with driver.session() as session:
        result = session.run(
            """
            MATCH (t:Term)
            WHERE t.embedding IS NOT NULL
            RETURN t.term_id AS tid, t.embedding AS emb,
                   t.embedding_dimension AS dim
            ORDER BY t.term_id
            """
        )
        terms = [(r["tid"], r["emb"], r["dim"]) for r in result]

    if len(terms) < 2:
        print("  Not enough embedded terms for semantic edges")
        return stats

    # Group by dimension
    by_dim: dict[int, list[tuple[int, list[float]]]] = {}
    for tid, emb, dim in terms:
        by_dim.setdefault(dim, []).append((tid, emb))

    # Fetch existing structural edges for skip-check
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Term)-[:PARENT_OF]-(b:Term)
            RETURN a.term_id AS a_id, b.term_id AS b_id
            """
        )
        structural_pairs = {
            (min(r["a_id"], r["b_id"]), max(r["a_id"], r["b_id"]))
            for r in result
        }

    # Clear existing semantic edges (rebuild fresh each run)
    with driver.session() as session:
        session.run("MATCH ()-[r:SIMILAR_TO]->() DELETE r")

    for dim, dim_terms in by_dim.items():
        print(f"  Computing similarities for {len(dim_terms)} terms "
              f"(dim={dim})...")
        pairs_to_create = []

        for i in range(len(dim_terms)):
            tid_a, emb_a = dim_terms[i]
            for j in range(i + 1, len(dim_terms)):
                tid_b, emb_b = dim_terms[j]

                # Skip if structural edge exists
                pair_key = (min(tid_a, tid_b), max(tid_a, tid_b))
                if pair_key in structural_pairs:
                    stats["skipped_structural"] += 1
                    continue

                score = _cosine_similarity(emb_a, emb_b)
                if score >= threshold:
                    pairs_to_create.append((tid_a, tid_b, score))
                else:
                    stats["below_threshold"] += 1

        # Batch-create edges
        with driver.session() as session:
            for tid_a, tid_b, score in pairs_to_create:
                session.run(
                    """
                    MATCH (a:Term {term_id: $a_id})
                    MATCH (b:Term {term_id: $b_id})
                    CREATE (a)-[:SIMILAR_TO {
                        score: $score,
                        weight: $weight,
                        edge_type: 'semantic',
                        created_at: datetime()
                    }]->(b)
                    """,
                    a_id=tid_a,
                    b_id=tid_b,
                    score=round(score, 4),
                    weight=weight,
                )
                stats["created"] += 1

    return stats
