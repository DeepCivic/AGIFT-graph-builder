"""
Import AGIFT vocabulary into Neo4j graph with embeddings and semantic edges.

Four-stage pipeline:
  1. Fetch  — pull full 3-level hierarchy from TemaTres API
  2. Graph  — upsert nodes and PARENT_OF (structural) edges into Neo4j
  3. Embed  — generate embeddings (Isaacus API or local sentence-transformers)
  4. Link   — build SIMILAR_TO (semantic) edges from embedding cosine similarity

Nodes: (:Term {term_id, label, label_norm, depth, dcat_theme, embedding})
Edges: (:Term)-[:PARENT_OF]->(:Term)          — structural (weight 1.0)
       (:Term)-[:SIMILAR_TO {score, weight}]->(:Term) — semantic (weight 0.5)

Embedding providers:
  - isaacus: Isaacus kanon-2-embedder API (requires API key)
  - local:   sentence-transformers running on CPU (free, no API key)
             Models: all-MiniLM-L6-v2 (384d), all-mpnet-base-v2 (768d)

Usage:
    python scripts/import_agift.py
    python scripts/import_agift.py --dry-run
    python scripts/import_agift.py --skip-embed
    python scripts/import_agift.py --force-embed
    python scripts/import_agift.py --skip-semantic

Source: https://vocabularyserver.com/agift/services.php
"""

import argparse
import os
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

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
# TemaTres API helpers
# ---------------------------------------------------------------------------

@dataclass
class AgiftTerm:
    """A single AGIFT vocabulary term."""
    term_id: int
    label: str
    parent_id: int | None
    top_level_id: int | None
    depth: int
    dcat_theme: str
    alt_labels: list[str] = field(default_factory=list)


def _fetch_xml(task: str, arg: str = "") -> ET.Element:
    """Fetch XML from TemaTres API with retry."""
    url = f"{TEMATRES_BASE}?task={task}"
    if arg:
        url += f"&arg={arg}"
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "AGIFT-Graph-Import/1.0"})
            with urlopen(req, timeout=120) as resp:
                data = resp.read().decode("utf-8")
                return ET.fromstring(data)
        except (URLError, TimeoutError, ET.ParseError) as e:
            if attempt == 2:
                raise
            wait = 5 * (attempt + 1)
            print(f"  Retry {attempt + 1} for {task} {arg}: {e}")
            time.sleep(wait)


def _parse_terms(root: ET.Element) -> list[tuple[int, str]]:
    """Extract (term_id, label) pairs from a TemaTres XML response."""
    results = []
    for term in root.findall(".//term"):
        tid_el = term.find("term_id")
        str_el = term.find("string")
        if tid_el is not None and str_el is not None and tid_el.text and str_el.text:
            results.append((int(tid_el.text), str_el.text.strip()))
    return results


def _fetch_alt_labels(term_id: int) -> list[str]:
    """Fetch non-preferred (alternative) labels for a term."""
    try:
        root = _fetch_xml("fetchAlt", str(term_id))
        return [label for _, label in _parse_terms(root)]
    except Exception:
        return []


def fetch_full_hierarchy(include_alts: bool = True) -> list[AgiftTerm]:
    """Walk the full AGIFT hierarchy from TemaTres and return all terms.

    Args:
        include_alts: If True, fetch alt labels for each term (slower).

    Returns:
        List of AgiftTerm objects for the full 3-level hierarchy.
    """
    print("Fetching AGIFT top-level terms...")
    top_root = _fetch_xml("fetchTopTerms")
    top_terms = _parse_terms(top_root)
    print(f"  Found {len(top_terms)} top-level functions")
    if not include_alts:
        print("  (skipping alt labels)")

    all_terms: list[AgiftTerm] = []

    for top_id, top_label in top_terms:
        dcat = AGIFT_TOP_TO_DCAT.get(top_label.lower())
        if not dcat:
            print(f"  WARNING: No DCAT mapping for top-level '{top_label}', using GOVE")
            dcat = "GOVE"

        alt_labels = _fetch_alt_labels(top_id) if include_alts else []
        all_terms.append(AgiftTerm(
            term_id=top_id, label=top_label, parent_id=None,
            top_level_id=top_id, depth=1, dcat_theme=dcat,
            alt_labels=alt_labels,
        ))

        # Level 2
        l2_root = _fetch_xml("fetchDown", str(top_id))
        l2_terms = _parse_terms(l2_root)
        print(f"  {top_label} ({dcat}): {len(l2_terms)} L2 terms")

        for l2_id, l2_label in l2_terms:
            alt_labels = _fetch_alt_labels(l2_id) if include_alts else []
            all_terms.append(AgiftTerm(
                term_id=l2_id, label=l2_label, parent_id=top_id,
                top_level_id=top_id, depth=2, dcat_theme=dcat,
                alt_labels=alt_labels,
            ))

            # Level 3
            l3_root = _fetch_xml("fetchDown", str(l2_id))
            l3_terms = _parse_terms(l3_root)

            for l3_id, l3_label in l3_terms:
                alt_labels = _fetch_alt_labels(l3_id) if include_alts else []
                all_terms.append(AgiftTerm(
                    term_id=l3_id, label=l3_label, parent_id=l2_id,
                    top_level_id=top_id, depth=3, dcat_theme=dcat,
                    alt_labels=alt_labels,
                ))

        # Be polite to the API
        time.sleep(2)

    return all_terms


# ---------------------------------------------------------------------------
# Stage 2: Graph — upsert into Neo4j
# ---------------------------------------------------------------------------

def ensure_schema(driver) -> None:
    """Create Neo4j constraints and indexes.

    Args:
        driver: Neo4j driver.
    """
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT term_id_unique IF NOT EXISTS "
            "FOR (t:Term) REQUIRE t.term_id IS UNIQUE"
        )
        session.run(
            "CREATE INDEX term_dcat IF NOT EXISTS "
            "FOR (t:Term) ON (t.dcat_theme)"
        )
        session.run(
            "CREATE INDEX term_depth IF NOT EXISTS "
            "FOR (t:Term) ON (t.depth)"
        )
    print("Neo4j schema ensured.")


def upsert_graph(driver, terms: list[AgiftTerm]) -> dict:
    """Upsert AGIFT terms as Neo4j nodes with PARENT_OF edges.

    Uses MERGE to avoid duplicates. Detects changed labels to flag
    terms that need re-embedding.

    Args:
        driver: Neo4j driver.
        terms: List of AgiftTerm objects.

    Returns:
        Dict with created, updated, unchanged counts and
        changed_ids list of term_ids that need re-embedding.
    """
    # Sort so parents come before children
    terms_sorted = sorted(terms, key=lambda t: t.depth)

    stats = {"created": 0, "updated": 0, "unchanged": 0, "changed_ids": []}

    with driver.session() as session:
        for t in terms_sorted:
            result = session.run(
                """
                MERGE (t:Term {term_id: $term_id})
                ON CREATE SET
                    t.label = $label,
                    t.label_norm = $label_norm,
                    t.depth = $depth,
                    t.dcat_theme = $dcat_theme,
                    t.top_level_id = $top_level_id,
                    t.alt_labels = $alt_labels,
                    t.created_at = datetime(),
                    t._changed = true
                ON MATCH SET
                    t._changed = (t.label <> $label OR t.alt_labels <> $alt_labels),
                    t.label = $label,
                    t.label_norm = $label_norm,
                    t.depth = $depth,
                    t.dcat_theme = $dcat_theme,
                    t.top_level_id = $top_level_id,
                    t.alt_labels = $alt_labels
                RETURN t._changed AS changed, t.embedding IS NULL AS no_embed
                """,
                term_id=t.term_id,
                label=t.label,
                label_norm=t.label.lower().strip(),
                depth=t.depth,
                dcat_theme=t.dcat_theme,
                top_level_id=t.top_level_id,
                alt_labels=t.alt_labels,
            )
            record = result.single()
            if record["changed"] or record["no_embed"]:
                stats["changed_ids"].append(t.term_id)
                if record["no_embed"]:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
            else:
                stats["unchanged"] += 1

            # Create PARENT_OF edge
            if t.parent_id is not None:
                session.run(
                    """
                    MATCH (parent:Term {term_id: $parent_id})
                    MATCH (child:Term {term_id: $child_id})
                    MERGE (parent)-[:PARENT_OF]->(child)
                    """,
                    parent_id=t.parent_id,
                    child_id=t.term_id,
                )

    # Clean up _changed flag
    with driver.session() as session:
        session.run("MATCH (t:Term) REMOVE t._changed")

    return stats


# ---------------------------------------------------------------------------
# Stage 3: Embed — generate Isaacus embeddings for terms
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Stage 4: Semantic edges — cosine similarity between embedded terms
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
