"""Stage 3: Embed — generate vector embeddings for AGIFT terms."""

import os

from agift.common import LOCAL_MODELS


def build_hierarchical_text(driver, term_id: int) -> str:
    """Build embedding input text using the term's full hierarchy path.

    For a L3 term like "Water quality monitoring", produces:
    "Environment > Water resources management > Water quality monitoring"

    Also appends alt labels for richer semantic coverage.

    Args:
        driver: Neo4j driver.
        term_id: The term to build text for.

    Returns:
        Hierarchical context string for embedding.
    """
    with driver.session() as session:
        # Walk up the tree to build the path
        result = session.run(
            """
            MATCH path = (root:Term)-[:PARENT_OF*0..2]->(t:Term {term_id: $tid})
            WHERE NOT ()-[:PARENT_OF]->(root)
            RETURN [n IN nodes(path) | n.label] AS chain,
                   t.alt_labels AS alts
            """,
            tid=term_id,
        )
        record = result.single()
        if not record:
            # Fallback: just the term itself (shouldn't happen)
            result2 = session.run(
                "MATCH (t:Term {term_id: $tid}) RETURN t.label AS label, t.alt_labels AS alts",
                tid=term_id,
            )
            r2 = result2.single()
            return r2["label"] if r2 else ""

        chain = record["chain"]
        alts = record["alts"] or []

        text = " > ".join(chain)
        if alts:
            text += f" (also known as: {', '.join(alts)})"
        return text


def embed_terms(driver, term_ids: list[int], api_key: str, dimension: int) -> dict:
    """Generate and store Isaacus embeddings for AGIFT terms.

    Only embeds terms in the provided list (new or changed terms).
    Batches API calls for efficiency.

    Args:
        driver: Neo4j driver.
        term_ids: List of term_ids to embed.
        api_key: Isaacus API key.
        dimension: Embedding dimension.

    Returns:
        Dict with embedded and failed counts.
    """
    from isaacus import Isaacus

    client = Isaacus(api_key=api_key)
    stats = {"embedded": 0, "failed": 0}
    batch_size = 50

    for i in range(0, len(term_ids), batch_size):
        batch_ids = term_ids[i:i + batch_size]
        texts = []
        valid_ids = []

        for tid in batch_ids:
            text = build_hierarchical_text(driver, tid)
            if text:
                texts.append(text)
                valid_ids.append(tid)

        if not texts:
            continue

        try:
            response = client.embeddings.create(
                model="kanon-2-embedder",
                texts=texts,
                dimensions=dimension,
            )

            with driver.session() as session:
                for j, embedding_data in enumerate(response.embeddings):
                    session.run(
                        """
                        MATCH (t:Term {term_id: $tid})
                        SET t.embedding = $embedding,
                            t.embedding_dimension = $dim,
                            t.embedding_provider = 'isaacus',
                            t.embedded_at = datetime()
                        """,
                        tid=valid_ids[j],
                        embedding=embedding_data.embedding,
                        dim=dimension,
                    )
                    stats["embedded"] += 1

            print(f"  Embedded batch {i // batch_size + 1}: {len(texts)} terms")

        except Exception as e:
            print(f"  Embedding batch failed: {e}")
            stats["failed"] += len(texts)

    return stats


def embed_terms_local(driver, term_ids: list[int], dimension: int) -> dict:
    """Generate and store embeddings using local sentence-transformers.

    Uses CPU-only inference. Model is selected based on dimension:
      384 → all-MiniLM-L6-v2
      768 → all-mpnet-base-v2

    Models are cached in /app/models (Docker) or ~/.cache/huggingface.

    Args:
        driver: Neo4j driver.
        term_ids: List of term_ids to embed.
        dimension: Embedding dimension (384 or 768).

    Returns:
        Dict with embedded and failed counts.
    """
    from sentence_transformers import SentenceTransformer

    model_name = LOCAL_MODELS.get(dimension)
    if not model_name:
        print(f"  ERROR: No local model for dimension {dimension}. "
              f"Use one of: {list(LOCAL_MODELS.keys())}")
        return {"embedded": 0, "failed": len(term_ids)}

    cache_dir = os.environ.get("TRANSFORMERS_CACHE", None)
    print(f"  Loading model: {model_name} (dimension={dimension})...")
    model = SentenceTransformer(model_name, cache_folder=cache_dir)

    stats = {"embedded": 0, "failed": 0}
    batch_size = 64

    for i in range(0, len(term_ids), batch_size):
        batch_ids = term_ids[i:i + batch_size]
        texts = []
        valid_ids = []

        for tid in batch_ids:
            text = build_hierarchical_text(driver, tid)
            if text:
                texts.append(text)
                valid_ids.append(tid)

        if not texts:
            continue

        try:
            embeddings = model.encode(texts, show_progress_bar=False)

            with driver.session() as session:
                for j, vec in enumerate(embeddings):
                    session.run(
                        """
                        MATCH (t:Term {term_id: $tid})
                        SET t.embedding = $embedding,
                            t.embedding_dimension = $dim,
                            t.embedding_provider = 'local',
                            t.embedded_at = datetime()
                        """,
                        tid=valid_ids[j],
                        embedding=vec.tolist(),
                        dim=dimension,
                    )
                    stats["embedded"] += 1

            print(f"  Embedded batch {i // batch_size + 1}: {len(texts)} terms")

        except Exception as e:
            print(f"  Local embedding batch failed: {e}")
            stats["failed"] += len(texts)

    return stats
