"""Neo4j implementation of the AGIFT graph backend."""

import os
from datetime import datetime, timezone

from neo4j import GraphDatabase

from agift.backend import GraphBackend
from agift.common import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_PROVIDER,
    PROVIDER_ISAACUS,
    SEMANTIC_EDGE_WEIGHT,
    SIMILARITY_THRESHOLD,
)


class Neo4jBackend(GraphBackend):
    """Graph backend backed by a Neo4j server."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self._uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self._user = user or os.environ.get("NEO4J_USER", "neo4j")
        self._password = password or os.environ.get("NEO4J_PASSWORD", "changeme")
        self._driver = GraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )

    @classmethod
    def from_driver(cls, driver) -> "Neo4jBackend":
        """Wrap an existing Neo4j driver in a backend instance.

        Used by legacy compatibility wrappers in common.py.
        """
        instance = cls.__new__(cls)
        instance._driver = driver
        instance._uri = ""
        instance._user = ""
        instance._password = ""
        return instance

    @property
    def driver(self):
        """Expose the raw driver for legacy callers."""
        return self._driver

    # -- Schema ---------------------------------------------------------------

    def ensure_schema(self) -> None:
        with self._driver.session() as session:
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

    # -- Nodes ----------------------------------------------------------------

    def upsert_term(self, term_id, label, label_norm, depth, dcat_theme,
                    top_level_id, alt_labels):
        with self._driver.session() as session:
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
                term_id=term_id,
                label=label,
                label_norm=label_norm,
                depth=depth,
                dcat_theme=dcat_theme,
                top_level_id=top_level_id,
                alt_labels=alt_labels,
            )
            record = result.single()
            return record["changed"], record["no_embed"]

    def create_parent_edge(self, parent_id, child_id):
        with self._driver.session() as session:
            session.run(
                """
                MATCH (parent:Term {term_id: $parent_id})
                MATCH (child:Term {term_id: $child_id})
                MERGE (parent)-[:PARENT_OF]->(child)
                """,
                parent_id=parent_id,
                child_id=child_id,
            )

    def cleanup_changed_flags(self):
        with self._driver.session() as session:
            session.run("MATCH (t:Term) REMOVE t._changed")

    # -- Embeddings -----------------------------------------------------------

    def get_hierarchy_path(self, term_id):
        with self._driver.session() as session:
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
                return [], []
            return record["chain"], record["alts"] or []

    def get_term_label_and_alts(self, term_id):
        with self._driver.session() as session:
            result = session.run(
                "MATCH (t:Term {term_id: $tid}) "
                "RETURN t.label AS label, t.alt_labels AS alts",
                tid=term_id,
            )
            record = result.single()
            if not record:
                return "", []
            return record["label"], record["alts"] or []

    def store_embedding(self, term_id, embedding, dimension, provider):
        with self._driver.session() as session:
            session.run(
                """
                MATCH (t:Term {term_id: $tid})
                SET t.embedding = $embedding,
                    t.embedding_dimension = $dim,
                    t.embedding_provider = $provider,
                    t.embedded_at = datetime()
                """,
                tid=term_id,
                embedding=embedding,
                dim=dimension,
                provider=provider,
            )

    # -- Semantic edges -------------------------------------------------------

    def get_all_embedded_terms(self):
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (t:Term)
                WHERE t.embedding IS NOT NULL
                RETURN t.term_id AS tid, t.embedding AS emb,
                       t.embedding_dimension AS dim
                ORDER BY t.term_id
                """
            )
            return [(r["tid"], r["emb"], r["dim"]) for r in result]

    def get_structural_pairs(self):
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a:Term)-[:PARENT_OF]->(b:Term)
                RETURN a.term_id AS a_id, b.term_id AS b_id
                """
            )
            return {
                (min(r["a_id"], r["b_id"]), max(r["a_id"], r["b_id"]))
                for r in result
            }

    def delete_all_semantic_edges(self):
        with self._driver.session() as session:
            session.run("MATCH ()-[r:SIMILAR_TO]->() DELETE r")

    def create_semantic_edge(self, a_id, b_id, score, weight):
        with self._driver.session() as session:
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
                a_id=a_id,
                b_id=b_id,
                score=round(score, 4),
                weight=weight,
            )

    # -- Config & logging -----------------------------------------------------

    def get_config(self):
        with self._driver.session() as session:
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
                    "embedding_dimension": record["dim"] or DEFAULT_EMBEDDING_DIMENSION,
                    "embedding_provider": record["provider"] or DEFAULT_EMBEDDING_PROVIDER,
                    "similarity_threshold": (
                        record["sim_thresh"] or SIMILARITY_THRESHOLD
                    ),
                    "semantic_edge_weight": (
                        record["sem_weight"] or SEMANTIC_EDGE_WEIGHT
                    ),
                }
        return {
            "isaacus_api_key": None,
            "embedding_dimension": DEFAULT_EMBEDDING_DIMENSION,
            "embedding_provider": DEFAULT_EMBEDDING_PROVIDER,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "semantic_edge_weight": SEMANTIC_EDGE_WEIGHT,
        }

    def log_run(self, status, details):
        with self._driver.session() as session:
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
                started=details.get(
                    "started_at", datetime.now(timezone.utc).isoformat()
                ),
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
            session.run(
                """
                MATCH (r:RunLog {worker: 'agift'})
                WITH r ORDER BY r.finished_at DESC
                SKIP 20
                DELETE r
                """
            )

    def get_all_term_ids(self):
        with self._driver.session() as session:
            result = session.run("MATCH (t:Term) RETURN t.term_id AS tid")
            return [r["tid"] for r in result]

    # -- Summary --------------------------------------------------------------

    def get_summary_stats(self):
        with self._driver.session() as session:
            total = session.run(
                "MATCH (t:Term) RETURN count(t) AS total"
            ).single()["total"]

            embedded = session.run(
                "MATCH (t:Term) WHERE t.embedding IS NOT NULL "
                "RETURN count(t) AS embedded"
            ).single()["embedded"]

            result = session.run(
                "MATCH (t:Term) RETURN t.depth AS depth, count(t) AS cnt "
                "ORDER BY depth"
            )
            by_depth = [(r["depth"], r["cnt"]) for r in result]

            result = session.run(
                "MATCH (t:Term) RETURN t.dcat_theme AS theme, count(t) AS cnt "
                "ORDER BY cnt DESC"
            )
            by_theme = [(r["theme"], r["cnt"]) for r in result]

            structural = session.run(
                "MATCH ()-[r:PARENT_OF]->() RETURN count(r) AS edges"
            ).single()["edges"]

            semantic = session.run(
                "MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) AS edges"
            ).single()["edges"]

        return {
            "total": total,
            "embedded": embedded,
            "structural_edges": structural,
            "semantic_edges": semantic,
            "by_depth": by_depth,
            "by_theme": by_theme,
        }

    # -- Lifecycle ------------------------------------------------------------

    def close(self):
        self._driver.close()
