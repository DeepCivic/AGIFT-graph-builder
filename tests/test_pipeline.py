"""Tests for pipeline stages using the CogDB backend.

These tests exercise graph.py, embed.py, and link.py against a real
(temporary) CogDB instance — no mocking required.
"""

from agift.fetch import AgiftTerm
from agift.graph import ensure_schema, upsert_graph
from agift.embed import build_hierarchical_text
from agift.link import _cosine_similarity, build_semantic_edges


def _make_terms():
    """Build a small hierarchy for testing."""
    return [
        AgiftTerm(1, "Environment", None, 1, 1, "ENVI", []),
        AgiftTerm(2, "Water resources", 1, 1, 2, "ENVI", ["Water"]),
        AgiftTerm(3, "Water quality monitoring", 2, 1, 3, "ENVI", []),
        AgiftTerm(4, "Air quality", 1, 1, 2, "ENVI", ["Air"]),
        AgiftTerm(10, "Health care", None, 10, 1, "HEAL", []),
        AgiftTerm(11, "Hospital services", 10, 10, 2, "HEAL", []),
    ]


class TestEnsureSchema:
    def test_cogdb_schema_is_noop(self, cogdb_backend, capsys):
        ensure_schema(cogdb_backend)
        out = capsys.readouterr().out
        assert "CogDB backend ready" in out


class TestUpsertGraph:
    def test_initial_import(self, cogdb_backend):
        terms = _make_terms()
        stats = upsert_graph(cogdb_backend, terms)
        assert stats["created"] == 6
        assert stats["updated"] == 0
        assert stats["unchanged"] == 0
        assert len(stats["changed_ids"]) == 6

    def test_idempotent_reimport(self, cogdb_backend):
        terms = _make_terms()
        upsert_graph(cogdb_backend, terms)
        # Add embeddings so re-import sees them as unchanged
        for t in terms:
            cogdb_backend.store_embedding(t.term_id, [0.1], 1, "test")
        stats = upsert_graph(cogdb_backend, terms)
        assert stats["unchanged"] == 6
        assert stats["created"] == 0
        assert stats["updated"] == 0

    def test_changed_label_triggers_update(self, cogdb_backend):
        terms = _make_terms()
        upsert_graph(cogdb_backend, terms)
        for t in terms:
            cogdb_backend.store_embedding(t.term_id, [0.1], 1, "test")
        # Change one label
        terms[0] = AgiftTerm(1, "Natural environment", None, 1, 1, "ENVI", [])
        stats = upsert_graph(cogdb_backend, terms)
        assert stats["updated"] == 1
        assert 1 in stats["changed_ids"]

    def test_structural_edges_created(self, cogdb_backend):
        terms = _make_terms()
        upsert_graph(cogdb_backend, terms)
        pairs = cogdb_backend.get_structural_pairs()
        assert (1, 2) in pairs
        assert (2, 3) in pairs
        assert (1, 4) in pairs
        assert (10, 11) in pairs
        assert len(pairs) == 4


class TestBuildHierarchicalText:
    def test_l1_term(self, seeded_backend):
        text = build_hierarchical_text(seeded_backend, 1)
        assert text == "Environment"

    def test_l2_term_with_alts(self, seeded_backend):
        text = build_hierarchical_text(seeded_backend, 2)
        assert "Environment > Water resources" in text
        assert "also known as: Water" in text

    def test_l3_term(self, seeded_backend):
        text = build_hierarchical_text(seeded_backend, 3)
        assert text == ("Environment > Water resources > "
                        "Water quality monitoring")

    def test_nonexistent_term_returns_empty(self, cogdb_backend):
        text = build_hierarchical_text(cogdb_backend, 999)
        assert text == ""


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_opposite_vectors(self):
        assert _cosine_similarity([1, 0], [-1, 0]) == -1.0

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 1]) == 0.0

    def test_similar_vectors(self):
        score = _cosine_similarity([1, 1], [1, 0.9])
        assert 0.99 < score < 1.0


class TestBuildSemanticEdges:
    def test_creates_edges_above_threshold(self, seeded_backend):
        # Use identical embeddings so similarity = 1.0
        seeded_backend.store_embedding(1, [1.0, 0.0, 0.0], 3, "test")
        seeded_backend.store_embedding(10, [1.0, 0.0, 0.0], 3, "test")
        stats = build_semantic_edges(seeded_backend, threshold=0.5, weight=0.5)
        assert stats["created"] == 1

    def test_skips_structural_pairs(self, seeded_backend):
        # Terms 1 and 2 have a PARENT_OF edge
        seeded_backend.store_embedding(1, [1.0, 0.0], 2, "test")
        seeded_backend.store_embedding(2, [1.0, 0.0], 2, "test")
        stats = build_semantic_edges(seeded_backend, threshold=0.5, weight=0.5)
        assert stats["skipped_structural"] >= 1
        assert stats["created"] == 0

    def test_below_threshold_not_created(self, seeded_backend):
        # Orthogonal vectors → similarity = 0
        seeded_backend.store_embedding(1, [1.0, 0.0], 2, "test")
        seeded_backend.store_embedding(10, [0.0, 1.0], 2, "test")
        stats = build_semantic_edges(seeded_backend, threshold=0.5, weight=0.5)
        assert stats["created"] == 0
        assert stats["below_threshold"] == 1

    def test_cross_dimension_not_compared(self, seeded_backend):
        seeded_backend.store_embedding(1, [1.0, 0.0], 2, "test")
        seeded_backend.store_embedding(10, [1.0, 0.0, 0.0], 3, "test")
        stats = build_semantic_edges(seeded_backend, threshold=0.5, weight=0.5)
        assert stats["created"] == 0

    def test_rebuilds_from_scratch(self, seeded_backend):
        seeded_backend.store_embedding(1, [1.0, 0.0], 2, "test")
        seeded_backend.store_embedding(10, [0.9, 0.1], 2, "test")
        build_semantic_edges(seeded_backend, threshold=0.5, weight=0.5)
        # Run again — should delete old and recreate
        stats = build_semantic_edges(seeded_backend, threshold=0.5, weight=0.5)
        assert stats["created"] == 1
        summary = seeded_backend.get_summary_stats()
        assert summary["semantic_edges"] == 1

    def test_not_enough_terms(self, seeded_backend, capsys):
        seeded_backend.store_embedding(1, [1.0], 1, "test")
        stats = build_semantic_edges(seeded_backend, threshold=0.5)
        assert stats["created"] == 0
        out = capsys.readouterr().out
        assert "Not enough" in out
