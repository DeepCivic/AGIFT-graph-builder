"""Abstract graph backend interface for the AGIFT pipeline."""

from abc import ABC, abstractmethod


class GraphBackend(ABC):
    """Interface that all graph backends (Neo4j, CogDB, etc.) must implement."""

    # -- Schema ---------------------------------------------------------------

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create any constraints or indexes required by the backend."""

    # -- Nodes ----------------------------------------------------------------

    @abstractmethod
    def upsert_term(
        self,
        term_id: int,
        label: str,
        label_norm: str,
        depth: int,
        dcat_theme: str,
        top_level_id: int,
        alt_labels: list[str],
    ) -> tuple[bool, bool]:
        """Create or update a Term node.

        Returns:
            (changed, no_embed) — *changed* is True when the label or
            alt_labels differ from the stored value; *no_embed* is True
            when the node has no embedding yet.
        """

    @abstractmethod
    def create_parent_edge(self, parent_id: int, child_id: int) -> None:
        """Create a PARENT_OF edge between two terms."""

    @abstractmethod
    def cleanup_changed_flags(self) -> None:
        """Remove any temporary flags set during upsert."""

    # -- Embeddings -----------------------------------------------------------

    @abstractmethod
    def get_hierarchy_path(self, term_id: int) -> tuple[list[str], list[str]]:
        """Return the label chain from root to *term_id* and its alt labels.

        Returns:
            (chain, alt_labels) where *chain* is e.g.
            ``["Environment", "Water resources", "Water quality monitoring"]``.
        """

    @abstractmethod
    def get_term_label_and_alts(self, term_id: int) -> tuple[str, list[str]]:
        """Fallback: return just the label and alt labels for a term."""

    @abstractmethod
    def store_embedding(
        self,
        term_id: int,
        embedding: list[float],
        dimension: int,
        provider: str,
    ) -> None:
        """Persist an embedding vector on a term node."""

    # -- Semantic edges -------------------------------------------------------

    @abstractmethod
    def get_all_embedded_terms(self) -> list[tuple[int, list[float], int]]:
        """Return ``[(term_id, embedding, dimension), ...]`` for all embedded terms."""

    @abstractmethod
    def get_structural_pairs(self) -> set[tuple[int, int]]:
        """Return ``{(min_id, max_id), ...}`` for every PARENT_OF edge."""

    @abstractmethod
    def delete_all_semantic_edges(self) -> None:
        """Remove every SIMILAR_TO edge (rebuilt each run)."""

    @abstractmethod
    def create_semantic_edge(
        self, a_id: int, b_id: int, score: float, weight: float
    ) -> None:
        """Create a single SIMILAR_TO edge."""

    # -- Config & logging -----------------------------------------------------

    @abstractmethod
    def get_config(self) -> dict:
        """Read pipeline configuration.

        Returns:
            Dict with keys ``isaacus_api_key``, ``embedding_dimension``,
            ``embedding_provider``, ``similarity_threshold``,
            ``semantic_edge_weight``.
        """

    @abstractmethod
    def save_config(
        self,
        api_key: str,
        embedding_dimension: int,
        embedding_provider: str,
        similarity_threshold: float,
        semantic_edge_weight: float,
    ) -> None:
        """Persist pipeline configuration."""

    @abstractmethod
    def log_run(self, status: str, details: dict) -> None:
        """Write a run-log entry."""

    @abstractmethod
    def get_run_logs(self, worker: str, limit: int = 5) -> list[dict]:
        """Return recent run logs for *worker*, newest first."""

    @abstractmethod
    def get_term_properties(self, term_id: int) -> dict | None:
        """Return the stored properties for a term as a plain dict.

        Keys typically include ``term_id``, ``label``, ``label_norm``,
        ``depth``, ``dcat_theme``, ``top_level_id``, and ``alt_labels``.
        Returns ``None`` when the term does not exist.
        """

    @abstractmethod
    def get_all_term_ids(self) -> list[int]:
        """Return every term_id in the graph."""

    # -- Summary --------------------------------------------------------------

    @abstractmethod
    def get_summary_stats(self) -> dict:
        """Return graph statistics for the CLI summary.

        Expected keys: ``total``, ``embedded``, ``structural_edges``,
        ``semantic_edges``, ``by_depth`` (list of (depth, count)),
        ``by_theme`` (list of (theme, count)).
        """

    # -- Lifecycle ------------------------------------------------------------

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the backend."""
