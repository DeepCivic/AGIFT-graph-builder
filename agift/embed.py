"""Stage 3: Embed — generate vector embeddings for AGIFT terms."""

import os

from agift.backend import GraphBackend
from agift.common import LOCAL_MODELS


def build_hierarchical_text(backend: GraphBackend, term_id: int) -> str:
    """Build embedding input text using the term's full hierarchy path.

    For a L3 term like "Water quality monitoring", produces:
    "Environment > Water resources management > Water quality monitoring"

    Also appends alt labels for richer semantic coverage.

    Args:
        backend: Graph backend instance.
        term_id: The term to build text for.

    Returns:
        Hierarchical context string for embedding.
    """
    chain, alts = backend.get_hierarchy_path(term_id)
    if not chain:
        # Fallback: just the term itself
        label, alts = backend.get_term_label_and_alts(term_id)
        return label

    text = " > ".join(chain)
    if alts:
        text += f" (also known as: {', '.join(alts)})"
    return text


def embed_terms(
    backend: GraphBackend,
    term_ids: list[int],
    api_key: str,
    dimension: int,
) -> dict:
    """Generate and store Isaacus embeddings for AGIFT terms.

    Only embeds terms in the provided list (new or changed terms).
    Batches API calls for efficiency.

    Args:
        backend: Graph backend instance.
        term_ids: List of term_ids to embed.
        api_key: Isaacus API key.
        dimension: Embedding dimension.

    Returns:
        Dict with embedded and failed counts.
    """
    try:
        from isaacus import Isaacus
    except ImportError:
        raise ImportError(
            "The isaacus package is required for Isaacus embeddings.\n"
            "Install it with: pip install agift-graph[isaacus]"
        )

    client = Isaacus(api_key=api_key)
    stats = {"embedded": 0, "failed": 0}
    batch_size = 50

    for i in range(0, len(term_ids), batch_size):
        batch_ids = term_ids[i:i + batch_size]
        texts = []
        valid_ids = []

        for tid in batch_ids:
            text = build_hierarchical_text(backend, tid)
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

            for j, embedding_data in enumerate(response.embeddings):
                backend.store_embedding(
                    valid_ids[j], embedding_data.embedding, dimension, "isaacus"
                )
                stats["embedded"] += 1

            print(f"  Embedded batch {i // batch_size + 1}: {len(texts)} terms")

        except Exception as e:
            print(f"  Embedding batch failed: {e}")
            stats["failed"] += len(texts)

    return stats


def embed_terms_local(
    backend: GraphBackend,
    term_ids: list[int],
    dimension: int,
) -> dict:
    """Generate and store embeddings using local sentence-transformers.

    Uses CPU-only inference. Model is selected based on dimension:
      384 -> all-MiniLM-L6-v2
      768 -> all-mpnet-base-v2

    Models are cached in /app/models (Docker) or ~/.cache/huggingface.

    Args:
        backend: Graph backend instance.
        term_ids: List of term_ids to embed.
        dimension: Embedding dimension (384 or 768).

    Returns:
        Dict with embedded and failed counts.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "The sentence-transformers package is required for local embeddings.\n"
            "Install it with: pip install agift-graph[local]"
        )

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
            text = build_hierarchical_text(backend, tid)
            if text:
                texts.append(text)
                valid_ids.append(tid)

        if not texts:
            continue

        try:
            embeddings = model.encode(texts, show_progress_bar=False)

            for j, vec in enumerate(embeddings):
                backend.store_embedding(
                    valid_ids[j], vec.tolist(), dimension, "local"
                )
                stats["embedded"] += 1

            print(f"  Embedded batch {i // batch_size + 1}: {len(texts)} terms")

        except Exception as e:
            print(f"  Local embedding batch failed: {e}")
            stats["failed"] += len(texts)

    return stats
