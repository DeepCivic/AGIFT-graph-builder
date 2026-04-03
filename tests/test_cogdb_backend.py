"""Tests for the CogDB backend implementation."""

import json

from agift.cogdb_backend import CogDBBackend


class TestUpsertTerm:
    def test_new_term_returns_changed_and_no_embed(self, cogdb_backend):
        changed, no_embed = cogdb_backend.upsert_term(
            1, "Environment", "environment", 1, "ENVI", 1, []
        )
        assert changed is True
        assert no_embed is True

    def test_unchanged_term_returns_no_change(self, cogdb_backend):
        cogdb_backend.upsert_term(1, "Env", "env", 1, "ENVI", 1, ["E"])
        cogdb_backend.store_embedding(1, [0.1], 1, "test")
        changed, no_embed = cogdb_backend.upsert_term(
            1, "Env", "env", 1, "ENVI", 1, ["E"]
        )
        assert changed is False
        assert no_embed is False

    def test_changed_label_detected(self, cogdb_backend):
        cogdb_backend.upsert_term(1, "Env", "env", 1, "ENVI", 1, [])
        cogdb_backend.store_embedding(1, [0.1], 1, "test")
        changed, no_embed = cogdb_backend.upsert_term(
            1, "Environment", "environment", 1, "ENVI", 1, []
        )
        assert changed is True
        assert no_embed is False

    def test_changed_alt_labels_detected(self, cogdb_backend):
        cogdb_backend.upsert_term(1, "Env", "env", 1, "ENVI", 1, [])
        cogdb_backend.store_embedding(1, [0.1], 1, "test")
        changed, _ = cogdb_backend.upsert_term(
            1, "Env", "env", 1, "ENVI", 1, ["Nature"]
        )
        assert changed is True

    def test_upsert_preserves_embedding(self, cogdb_backend):
        cogdb_backend.upsert_term(1, "Env", "env", 1, "ENVI", 1, [])
        cogdb_backend.store_embedding(1, [0.1, 0.2], 2, "test")
        cogdb_backend.upsert_term(1, "Env updated", "env updated", 1, "ENVI", 1, [])
        props = cogdb_backend._get_props(1)
        assert props["embedding"] == [0.1, 0.2]
        assert props["label"] == "Env updated"

    def test_term_registered(self, cogdb_backend):
        cogdb_backend.upsert_term(5, "Test", "test", 1, "GOVE", 5, [])
        assert 5 in cogdb_backend.get_all_term_ids()


class TestParentEdges:
    def test_create_parent_edge(self, seeded_backend):
        pairs = seeded_backend.get_structural_pairs()
        assert (1, 2) in pairs
        assert (1, 4) in pairs
        assert (2, 3) in pairs
        assert (10, 11) in pairs

    def test_structural_pair_ordering(self, seeded_backend):
        """Pairs should always be (min, max) regardless of direction."""
        pairs = seeded_backend.get_structural_pairs()
        for a, b in pairs:
            assert a < b


class TestHierarchyPath:
    def test_l1_term_has_single_label(self, seeded_backend):
        chain, alts = seeded_backend.get_hierarchy_path(1)
        assert chain == ["Environment"]
        assert alts == []

    def test_l2_term_has_two_labels(self, seeded_backend):
        chain, alts = seeded_backend.get_hierarchy_path(2)
        assert chain == ["Environment", "Water resources"]
        assert alts == ["Water"]

    def test_l3_term_has_three_labels(self, seeded_backend):
        chain, alts = seeded_backend.get_hierarchy_path(3)
        assert chain == ["Environment", "Water resources",
                         "Water quality monitoring"]

    def test_nonexistent_term(self, cogdb_backend):
        chain, alts = cogdb_backend.get_hierarchy_path(999)
        assert chain == []
        assert alts == []


class TestGetTermLabelAndAlts:
    def test_existing_term(self, seeded_backend):
        label, alts = seeded_backend.get_term_label_and_alts(2)
        assert label == "Water resources"
        assert alts == ["Water"]

    def test_nonexistent_term(self, cogdb_backend):
        label, alts = cogdb_backend.get_term_label_and_alts(999)
        assert label == ""
        assert alts == []


class TestEmbeddings:
    def test_store_and_retrieve(self, seeded_backend):
        vec = [0.1, 0.2, 0.3]
        seeded_backend.store_embedding(1, vec, 3, "local")
        terms = seeded_backend.get_all_embedded_terms()
        assert len(terms) == 1
        tid, emb, dim = terms[0]
        assert tid == 1
        assert emb == vec
        assert dim == 3

    def test_multiple_embeddings(self, seeded_backend):
        seeded_backend.store_embedding(1, [0.1], 1, "local")
        seeded_backend.store_embedding(2, [0.2], 1, "local")
        seeded_backend.store_embedding(4, [0.4], 1, "local")
        terms = seeded_backend.get_all_embedded_terms()
        assert len(terms) == 3
        # Should be sorted by term_id
        assert [t[0] for t in terms] == [1, 2, 4]

    def test_no_embedded_terms(self, seeded_backend):
        terms = seeded_backend.get_all_embedded_terms()
        assert terms == []

    def test_embedding_persists_through_upsert(self, cogdb_backend):
        cogdb_backend.upsert_term(1, "Env", "env", 1, "ENVI", 1, [])
        cogdb_backend.store_embedding(1, [0.5, 0.6], 2, "local")
        cogdb_backend.upsert_term(1, "Env", "env", 1, "ENVI", 1, [])
        terms = cogdb_backend.get_all_embedded_terms()
        assert len(terms) == 1
        assert terms[0][1] == [0.5, 0.6]


class TestSemanticEdges:
    def test_create_and_count(self, seeded_backend):
        seeded_backend.create_semantic_edge(1, 10, 0.85, 0.5)
        stats = seeded_backend.get_summary_stats()
        assert stats["semantic_edges"] == 1

    def test_delete_all(self, seeded_backend):
        seeded_backend.create_semantic_edge(1, 10, 0.85, 0.5)
        seeded_backend.create_semantic_edge(2, 11, 0.75, 0.5)
        seeded_backend.delete_all_semantic_edges()
        stats = seeded_backend.get_summary_stats()
        assert stats["semantic_edges"] == 0

    def test_delete_preserves_structural(self, seeded_backend):
        seeded_backend.create_semantic_edge(1, 10, 0.85, 0.5)
        seeded_backend.delete_all_semantic_edges()
        pairs = seeded_backend.get_structural_pairs()
        assert (1, 2) in pairs  # structural edges intact


class TestConfig:
    def test_default_config(self, cogdb_backend):
        cfg = cogdb_backend.get_config()
        assert cfg["isaacus_api_key"] is None
        assert cfg["embedding_dimension"] == 512
        assert cfg["similarity_threshold"] == 0.70
        assert cfg["semantic_edge_weight"] == 0.5


class TestLogRun:
    def test_log_run_does_not_raise(self, cogdb_backend):
        cogdb_backend.log_run("success", {
            "started_at": "2025-01-01T00:00:00",
            "fetched": 10,
            "created": 5,
        })


class TestSummaryStats:
    def test_empty_backend(self, cogdb_backend):
        stats = cogdb_backend.get_summary_stats()
        assert stats["total"] == 0
        assert stats["embedded"] == 0
        assert stats["structural_edges"] == 0
        assert stats["semantic_edges"] == 0

    def test_seeded_backend(self, seeded_backend):
        stats = seeded_backend.get_summary_stats()
        assert stats["total"] == 6
        assert stats["embedded"] == 0
        assert stats["structural_edges"] == 4
        assert stats["semantic_edges"] == 0
        # Depth distribution
        depth_dict = dict(stats["by_depth"])
        assert depth_dict[1] == 2  # Environment, Health care
        assert depth_dict[2] == 3  # Water resources, Air quality, Hospital services
        assert depth_dict[3] == 1  # Water quality monitoring
        # Theme distribution
        theme_dict = dict(stats["by_theme"])
        assert theme_dict["ENVI"] == 4
        assert theme_dict["HEAL"] == 2

    def test_with_embeddings(self, seeded_backend):
        seeded_backend.store_embedding(1, [0.1], 1, "local")
        seeded_backend.store_embedding(2, [0.2], 1, "local")
        stats = seeded_backend.get_summary_stats()
        assert stats["embedded"] == 2


class TestGetAllTermIds:
    def test_empty(self, cogdb_backend):
        assert cogdb_backend.get_all_term_ids() == []

    def test_seeded(self, seeded_backend):
        ids = sorted(seeded_backend.get_all_term_ids())
        assert ids == [1, 2, 3, 4, 10, 11]
