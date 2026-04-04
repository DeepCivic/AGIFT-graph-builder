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
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_PROVIDER,
    SEMANTIC_EDGE_WEIGHT,
    SIMILARITY_THRESHOLD,
)

_PARENT_OF = "PARENT_OF"
_SIMILAR_TO = "SIMILAR_TO"
_HAS_PROP = "HAS_PROP"


def _term_key(term_id: int) -> str:
    return f"term:{term_id}"


class CogDBBackend(GraphBackend):
    """Graph backend using CogDB for local, serverless storage.

    Data layout
    -----------
    * Each AGIFT term is a vertex ``term:<id>``.
    * Term properties are stored as a JSON string linked by a
      ``HAS_PROP`` edge from the term vertex.
    * ``PARENT_OF`` and ``SIMILAR_TO`` edges connect term vertices.
    * Pipeline config is stored as a JSON edge from ``config:agift``.
    * Run logs are stored as JSON edges from ``registry:runlogs``.
    * A registry vertex ``registry:terms`` tracks all known term IDs.
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

    def _out(self, vertex: str, predicate: str) -> list[str]:
        """Return outgoing edge targets as a list of ID strings."""
        try:
            res = self._graph.v(vertex).out(predicate).all()
            return [item["id"] for item in res.get("result", [])]
        except Exception:
            return []

    def _inc(self, vertex: str, predicate: str) -> list[str]:
        """Return incoming edge sources as a list of ID strings."""
        try:
            res = self._graph.v(vertex).inc(predicate).all()
            return [item["id"] for item in res.get("result", [])]
        except Exception:
            return []

    def _put_props(self, term_id: int, props: dict) -> None:
        """Store a JSON property blob for a term, replacing any old value."""
        tk = _term_key(term_id)
        blob = json.dumps(props, default=str)
        # Remove old property blob(s) first
        for old in self._out(tk, _HAS_PROP):
            self._graph.delete(tk, _HAS_PROP, old)
        self._graph.put(tk, _HAS_PROP, blob)

    def _get_props(self, term_id: int) -> dict | None:
        """Retrieve the property blob for a term."""
        results = self._out(_term_key(term_id), _HAS_PROP)
        if results:
            try:
                return json.loads(results[0])
            except (json.JSONDecodeError, IndexError):
                pass
        return None

    def _all_term_ids(self) -> list[int]:
        """Return all registered term IDs."""
        ids = self._out("registry:terms", "contains")
        return [int(tid) for tid in ids]

    def _register_term(self, term_id: int) -> None:
        """Add a term ID to the registry (idempotent)."""
        existing = self._out("registry:terms", "contains")
        if str(term_id) not in existing:
            self._graph.put("registry:terms", "contains", str(term_id))

    # -- Schema ---------------------------------------------------------------

    def ensure_schema(self) -> None:
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
        pass

    # -- Embeddings -----------------------------------------------------------

    def get_hierarchy_path(self, term_id):
        props = self._get_props(term_id)
        if not props:
            return [], []

        chain = [props["label"]]
        alt_labels = props.get("alt_labels", [])

        # Walk up parents using incoming PARENT_OF edges
        current_id = term_id
        for _ in range(2):
            parents = self._inc(_term_key(current_id), _PARENT_OF)
            if not parents:
                break
            parent_key = parents[0]  # "term:<id>"
            if not parent_key.startswith("term:"):
                break
            parent_id = int(parent_key.split(":")[1])
            parent_props = self._get_props(parent_id)
            if parent_props:
                chain.insert(0, parent_props["label"])
            current_id = parent_id

        return chain, alt_labels

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
            children = self._out(_term_key(tid), _PARENT_OF)
            for child_key in children:
                if child_key.startswith("term:"):
                    child_id = int(child_key.split(":")[1])
                    pairs.add((min(tid, child_id), max(tid, child_id)))
        return pairs

    def delete_all_semantic_edges(self):
        for tid in self._all_term_ids():
            targets = self._out(_term_key(tid), _SIMILAR_TO)
            for target in targets:
                self._graph.delete(_term_key(tid), _SIMILAR_TO, target)
        # Clean up edge metadata
        meta_keys = self._out("registry:sim_edges", "contains")
        for key in meta_keys:
            self._graph.delete("registry:sim_edges", "contains", key)
            for blob in self._out(key, "json"):
                self._graph.delete(key, "json", blob)

    def create_semantic_edge(self, a_id, b_id, score, weight):
        self._graph.put(_term_key(a_id), _SIMILAR_TO, _term_key(b_id))
        edge_key = f"sim:{a_id}:{b_id}"
        meta = json.dumps({
            "score": round(score, 4),
            "weight": weight,
            "edge_type": "semantic",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._graph.put(edge_key, "json", meta)
        self._graph.put("registry:sim_edges", "contains", edge_key)

    # -- Config & logging -----------------------------------------------------

    def get_config(self):
        results = self._out("config:agift", "json")
        if results:
            try:
                return json.loads(results[0])
            except (json.JSONDecodeError, IndexError):
                pass
        return {
            "isaacus_api_key": None,
            "embedding_dimension": DEFAULT_EMBEDDING_DIMENSION,
            "embedding_provider": DEFAULT_EMBEDDING_PROVIDER,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "semantic_edge_weight": SEMANTIC_EDGE_WEIGHT,
        }

    def log_run(self, status, details):
        ts = datetime.now(timezone.utc).isoformat()
        entry = json.dumps({
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
        }, default=str)
        log_key = f"runlog:{ts}"
        self._graph.put(log_key, "json", entry)
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
            targets = self._out(_term_key(tid), _SIMILAR_TO)
            semantic += len(targets)

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
