"""Shared fixtures for AGIFT tests."""

import shutil
import tempfile

import pytest

from agift.cogdb_backend import CogDBBackend


@pytest.fixture
def cogdb_backend():
    """Create a CogDB backend in a temporary directory, cleaned up after test."""
    tmpdir = tempfile.mkdtemp()
    backend = CogDBBackend(data_dir=tmpdir)
    yield backend
    backend.close()
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def seeded_backend(cogdb_backend):
    """CogDB backend pre-loaded with a small AGIFT-like hierarchy.

    Structure:
        Environment (L1, ENVI)
        ├── Water resources (L2, ENVI)  [alt: Water]
        │   └── Water quality monitoring (L3, ENVI)
        └── Air quality (L2, ENVI)
        Health care (L1, HEAL)
        └── Hospital services (L2, HEAL)
    """
    b = cogdb_backend
    terms = [
        (1, "Environment", 1, "ENVI", 1, None, []),
        (2, "Water resources", 2, "ENVI", 1, 1, ["Water"]),
        (3, "Water quality monitoring", 3, "ENVI", 1, 2, []),
        (4, "Air quality", 2, "ENVI", 1, 1, []),
        (10, "Health care", 1, "HEAL", 10, None, []),
        (11, "Hospital services", 2, "HEAL", 10, 10, []),
    ]
    for tid, label, depth, dcat, top, parent, alts in terms:
        b.upsert_term(tid, label, label.lower(), depth, dcat, top, alts)
        if parent is not None:
            b.create_parent_edge(parent, tid)
    return b
