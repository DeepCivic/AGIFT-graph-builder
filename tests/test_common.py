"""Tests for common module (constants, factory, summary)."""

import pytest

from agift.common import (
    VALID_BACKENDS,
    VALID_PROVIDERS,
    VALID_DIMENSIONS,
    create_backend,
    print_summary,
)
from agift.backend import GraphBackend
from agift.cogdb_backend import CogDBBackend


class TestCreateBackend:
    def test_cogdb_backend(self, tmp_path):
        backend = create_backend("cogdb", cogdb_data_dir=str(tmp_path))
        assert isinstance(backend, CogDBBackend)
        assert isinstance(backend, GraphBackend)
        backend.close()

    def test_invalid_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            create_backend("sqlite")

    def test_neo4j_backend_requires_driver(self):
        """Neo4j backend needs the neo4j package installed."""
        try:
            import neo4j  # noqa: F401
        except ImportError:
            with pytest.raises(ModuleNotFoundError):
                create_backend("neo4j")
            return
        # If neo4j is installed, just check instantiation works
        backend = create_backend(
            "neo4j",
            neo4j_uri="bolt://localhost:17687",
            neo4j_user="test",
            neo4j_password="test",
        )
        assert isinstance(backend, GraphBackend)
        backend.close()


class TestConstants:
    def test_valid_backends(self):
        assert "neo4j" in VALID_BACKENDS
        assert "cogdb" in VALID_BACKENDS

    def test_valid_providers(self):
        assert "isaacus" in VALID_PROVIDERS
        assert "local" in VALID_PROVIDERS

    def test_valid_dimensions(self):
        assert 384 in VALID_DIMENSIONS
        assert 768 in VALID_DIMENSIONS


class TestPrintSummary:
    def test_prints_stats(self, seeded_backend, capsys):
        seeded_backend.store_embedding(1, [0.1], 1, "test")
        print_summary(seeded_backend)
        out = capsys.readouterr().out
        assert "AGIFT Graph Summary" in out
        assert "Total terms:" in out
        assert "6" in out
        assert "Embedded:" in out
        assert "ENVI" in out
        assert "HEAL" in out
