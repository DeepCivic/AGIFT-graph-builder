"""Stage 4: Link — build semantic similarity edges from embeddings."""

from agift.backend import GraphBackend
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
    backend: GraphBackend,
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
        backend: Graph backend instance.
        threshold: Minimum cosine similarity to create an edge.
        weight: Edge weight for query-time weighting.

    Returns:
        Dict with created, skipped_structural, and below_threshold counts.
    """
    stats = {"created": 0, "skipped_structural": 0, "below_threshold": 0}

    terms = backend.get_all_embedded_terms()

    if len(terms) < 2:
        print("  Not enough embedded terms for semantic edges")
        return stats

    # Group by dimension
    by_dim: dict[int, list[tuple[int, list[float]]]] = {}
    for tid, emb, dim in terms:
        by_dim.setdefault(dim, []).append((tid, emb))

    structural_pairs = backend.get_structural_pairs()

    # Clear existing semantic edges (rebuild fresh each run)
    backend.delete_all_semantic_edges()

    for dim, dim_terms in by_dim.items():
        print(f"  Computing similarities for {len(dim_terms)} terms " f"(dim={dim})...")
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

        for tid_a, tid_b, score in pairs_to_create:
            backend.create_semantic_edge(tid_a, tid_b, score, weight)
            stats["created"] += 1

    return stats
