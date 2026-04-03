"""CogDB (embedded graph database) implementation of the AGIFT graph backend.

CogDB is a pure-Python persistent graph database that stores triples
(subject, predicate, object) to local files. No server process required.

Install:  pip install cogdb
Docs:     https://github.com/arun1729/cog
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agift.backend import GraphBackend
from agift.common import (
    PROVIDER_ISAACUS,
    SEMANTIC_EDGE_WEIGHT,
    SIMILARITY_THRESHOLD,
)


# CogDB edge types used as predicates
_PARENT_OF = "PARENT_OF"
_SIMILAR_TO = "SIMILAR_TO"
_HAS_PROPERTY = "HAS_PROPERTY"


def _term_key(term_id: int) -> str:
    """Canonical vertex name for a term."""
    return f"term:{term_id}"


def _prop_key(term_id: int) -> str:
    """Vertex name for the JSON property blob of a term."""
    return f"props:{term_id}"


class CogDBBackend(GraphBackend):
    """Graph backend using CogDB for local, serverless storage.

    Data layout
    -----------
    * Each AGIFT term becomes a vertex ``term:<id>``.
    * Term properties (label, depth, embedding, etc.) are stored as a
      JSON blob on a companion vertex ``props:<id>`` linked by a
      ``HAS_PROPERTY`` edge.
    * ``PARENT_OF`` and ``SIMILAR_TO`` edges connect term vertices
      directly.
    * Pipeline config is stored as a JSON blob on vertex ``config:agift``.
    * Run logs are stored as JSON on vertices ``runlog:<timestamp>``.
    """

    def __init__(self, data_dir: str | None = None):
        try:
            from cog.torque import Graph
        except ImportError:
            raise ImportError(
                "CogDB is required for the cogdb backend.\n"
                "Install it with: pip install cogdb"
            )

        self._data_dir = data_dir or os.environ.get(
            "COGDB_DATA_DIR", "agift_cogdb_data"
        )
        Path(self._data_dir).mkdir(parents=True, exist_ok=True)
        self._graph = Graph(graph_name="agift", cog_path_prefix=self._data_dir)

    # -- helpers --------------------------------------------------------------

    def _put_props(self, term_id: int, props: dict) -> None:
        """Store a JSON property blob for a term."""
        tk = _term_key(term_id)
        pk = _prop_key(term_id)
        self._graph.put(tk, _HAS_PROPERTY, pk)
        # Store the JSON as an edge from the prop vertex to a data literal
        self._graph.put(pk, "json", json.dumps(props, default=str))

    def _get_props(self, term_id: int) -> dict | None:
        """Retrieve the property blob for a term."""
        pk = _prop_key(term_id)
        try:
            results = list(self._graph.get(pk, "json"))
            if results:
                return json.loads(results[0])
        except Exception:
            pass
        return None

    def _all_term_ids(self) -> list[int]:
        """Scan for all known term IDs by checking stored property blobs."""
        # We maintain a registry vertex to track all term IDs
        try:
            results = list(self._graph.get("registry:terms", "contains"))
            return [int(tid) for tid in results]
        except Exception:
            return []

    def _register_term(self, term_id: int) -> None:
        """Add a term ID to the registry."""
        self._graph.put("registry:terms", "contains", str(term_id))

    # -- Schema ---------------------------------------------------------------

    def ensure_schema(self) -> None:
        # CogDB is schema-free; nothing to do
        print("CogDB backend ready (schema-free).")

    # -- Nodes ----------------------------------------------------------------

    def upsert_term(self, term_id, label, label_norm, depth, dcat_theme,
                    top_level_id, alt_labels):
        existing = self._get_props(term_id)
        no_embed = True
        changed = True

        if existing:
            no_embed = existing.get("embedding") is None
            changed = (
                existing.get("label") != label
                or existing.get("alt_labels") != alt_labels
            )
            # Preserve existing embedding fields on update
            props = existing.copy()
            props.update({
                "term_id": term_id,
                "label": label,
                "label_norm": label_norm,
                "depth": depth,
                "dcat_theme": dcat_theme,
                "top_level_id": top_level_id,
                "alt_labels": alt_labels,
            })
        else:
            props = {
                "term_id": term_id,
                "label": label,
                "label_norm": label_norm,
                "depth": depth,
                "dcat_theme": dcat_theme,
                "top_level_id": top_level_id,
                "alt_labels": alt_labels,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        self._put_props(term_id, props)
        self._register_term(term_id)
        return changed, no_embed

    def create_parent_edge(self, parent_id, child_id):
        self._graph.put(_term_key(parent_id), _PARENT_OF, _term_key(child_id))

    def cleanup_changed_flags(self):
        # No temporary flags in CogDB implementation
        pass

    # -- Embeddings -----------------------------------------------------------

    def get_hierarchy_path(self, term_id):
        """Walk PARENT_OF edges upward to build the label chain."""
        props = self._get_props(term_id)
        if not props:
            return [], []

        chain = [props["label"]]
        alt_labels = props.get("alt_labels", [])

        # Walk up parents (max 2 levels for AGIFT's 3-level hierarchy)
        current_id = term_id
        for _ in range(2):
            parent_id = self._find_parent(current_id)
            if parent_id is None:
                break
            parent_props = self._get_props(parent_id)
            if parent_props:
                chain.insert(0, parent_props["label"])
            current_id = parent_id

        return chain, alt_labels

    def _find_parent(self, child_id: int) -> int | None:
        """Find the parent term_id of a child by scanning PARENT_OF edges."""
        all_ids = self._all_term_ids()
        child_key = _term_key(child_id)
        for tid in all_ids:
            try:
                children = list(
                    self._graph.get(_term_key(tid), _PARENT_OF)
                )
                if child_key in children:
                    return tid
            except Exception:
                continue
        return None

    def get_term_label_and_alts(self, term_id):
        props = self._get_props(term_id)
        if not props:
            return "", []
        return props.get("label", ""), props.get("alt_labels", [])

    def store_embedding(self, term_id, embedding, dimension, provider):
        props = self._get_props(term_id) or {}
        props["embedding"] = embedding
        props["embedding_dimension"] = dimension
        props["embedding_provider"] = provider
        props["embedded_at"] = datetime.now(timezone.utc).isoformat()
        self._put_props(term_id, props)

    # -- Semantic edges -------------------------------------------------------

    def get_all_embedded_terms(self):
        results = []
        for tid in self._all_term_ids():
            props = self._get_props(tid)
            if props and props.get("embedding") is not None:
                results.append((
                    tid,
                    props["embedding"],
                    props.get("embedding_dimension", 0),
                ))
        results.sort(key=lambda x: x[0])
        return results

    def get_structural_pairs(self):
        pairs = set()
        for tid in self._all_term_ids():
            try:
                children = list(
                    self._graph.get(_term_key(tid), _PARENT_OF)
                )
                for child_key in children:
                    # Parse "term:<id>" back to int
                    if child_key.startswith("term:"):
                        child_id = int(child_key.split(":")[1])
                        pairs.add((min(tid, child_id), max(tid, child_id)))
            except Exception:
                continue
        return pairs

    def delete_all_semantic_edges(self):
        for tid in self._all_term_ids():
            try:
                targets = list(
                    self._graph.get(_term_key(tid), _SIMILAR_TO)
                )
                for target in targets:
                    self._graph.remove(_term_key(tid), _SIMILAR_TO, target)
            except Exception:
                continue
        # Also clear the similarity metadata store
        try:
            keys = list(self._graph.get("registry:sim_edges", "contains"))
            for key in keys:
                self._graph.remove("registry:sim_edges", "contains", key)
                try:
                    self._graph.remove(key, "json", list(
                        self._graph.get(key, "json")
                    )[0])
                except Exception:
                    pass
        except Exception:
            pass

    def create_semantic_edge(self, a_id, b_id, score, weight):
        self._graph.put(_term_key(a_id), _SIMILAR_TO, _term_key(b_id))
        # Store edge metadata as a JSON blob
        edge_key = f"sim:{a_id}:{b_id}"
        meta = {
            "score": round(score, 4),
            "weight": weight,
            "edge_type": "semantic",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._graph.put(edge_key, "json", json.dumps(meta))
        self._graph.put("registry:sim_edges", "contains", edge_key)

    # -- Config & logging -----------------------------------------------------

    def get_config(self):
        try:
            results = list(self._graph.get("config:agift", "json"))
            if results:
                return json.loads(results[0])
        except Exception:
            pass
        return {
            "isaacus_api_key": None,
            "embedding_dimension": 512,
            "embedding_provider": PROVIDER_ISAACUS,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "semantic_edge_weight": SEMANTIC_EDGE_WEIGHT,
        }

    def log_run(self, status, details):
        ts = datetime.now(timezone.utc).isoformat()
        log_key = f"runlog:{ts}"
        entry = {
            "worker": "agift",
            "status": status,
            "started_at": details.get("started_at", ts),
            "finished_at": ts,
            **{k: details.get(k, 0) for k in [
                "fetched", "created", "updated", "unchanged",
                "embedded", "embed_failed", "semantic_edges_created",
            ]},
            "embedding_provider": details.get("embedding_provider", ""),
            "error_message": details.get("error", ""),
        }
        self._graph.put(log_key, "json", json.dumps(entry, default=str))
        self._graph.put("registry:runlogs", "contains", log_key)

    def get_all_term_ids(self):
        return self._all_term_ids()

    # -- Summary --------------------------------------------------------------

    def get_summary_stats(self):
        all_ids = self._all_term_ids()
        total = len(all_ids)

        embedded = 0
        by_depth_map: dict[int, int] = {}
        by_theme_map: dict[str, int] = {}

        for tid in all_ids:
            props = self._get_props(tid)
            if not props:
                continue
            if props.get("embedding") is not None:
                embedded += 1
            d = props.get("depth", 0)
            by_depth_map[d] = by_depth_map.get(d, 0) + 1
            th = props.get("dcat_theme", "")
            by_theme_map[th] = by_theme_map.get(th, 0) + 1

        structural = len(self.get_structural_pairs())

        semantic = 0
        for tid in all_ids:
            try:
                targets = list(
                    self._graph.get(_term_key(tid), _SIMILAR_TO)
                )
                semantic += len(targets)
            except Exception:
                continue

        by_depth = sorted(by_depth_map.items())
        by_theme = sorted(by_theme_map.items(), key=lambda x: -x[1])

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
        try:
            self._graph.close()
        except Exception:
            pass
