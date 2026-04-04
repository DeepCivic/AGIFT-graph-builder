"""
AGIFT Dashboard — simple Flask app for worker config, run history, and run controls.

Features:
  - Set/view Isaacus API key and embedding provider
  - Set embedding dimension, similarity threshold, semantic edge weight
  - Trigger import runs from the UI (full, graph-only, dry-run)
  - Last 5 runs for AGIFT worker
  - Last 5 runs for enrichment worker

Backend-agnostic: reads BACKEND_TYPE env var ("neo4j" or "cogdb") and
delegates all data access through the GraphBackend interface.
"""

import os
import subprocess
import threading

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from agift.common import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_PROVIDER,
    LOCAL_MODELS,
    SEMANTIC_EDGE_WEIGHT,
    SIMILARITY_THRESHOLD,
    VALID_DIMENSIONS as _VALID_DIMS,
    VALID_PROVIDERS as _VALID_PROVS,
    create_backend,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "agift-dashboard-dev")

BACKEND_TYPE = os.environ.get("BACKEND_TYPE", "neo4j")
VALID_DIMENSIONS = list(_VALID_DIMS)
VALID_PROVIDERS = list(_VALID_PROVS)
LOCAL_ONLY_DIMENSIONS = list(LOCAL_MODELS.keys())


def _get_backend():
    """Create a backend instance from environment variables."""
    return create_backend(BACKEND_TYPE)


@app.route("/")
def index():
    """Dashboard home page."""
    backend = _get_backend()
    try:
        config = backend.get_config()
        agift_logs = backend.get_run_logs("agift", 5)
        enrichment_logs = backend.get_run_logs("enrichment", 5)
        raw_stats = backend.get_summary_stats()
    finally:
        backend.close()

    # Adapt backend stats shape to what the template expects
    stats = {
        "total_terms": raw_stats["total"],
        "embedded_terms": raw_stats["embedded"],
        "structural_edges": raw_stats["structural_edges"],
        "semantic_edges": raw_stats["semantic_edges"],
        "by_depth": {str(d): c for d, c in raw_stats["by_depth"]},
    }

    # Adapt config keys for the template
    tpl_config = {
        "api_key": config.get("isaacus_api_key") or "",
        "dimension": config["embedding_dimension"],
        "provider": config["embedding_provider"],
        "similarity_threshold": config["similarity_threshold"],
        "semantic_edge_weight": config["semantic_edge_weight"],
    }

    # Mask API key for display
    api_key = tpl_config["api_key"]
    masked_key = ""
    if api_key:
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"

    return render_template(
        "index.html",
        config=tpl_config,
        masked_key=masked_key,
        agift_logs=agift_logs,
        enrichment_logs=enrichment_logs,
        stats=stats,
        valid_dimensions=VALID_DIMENSIONS,
        valid_providers=VALID_PROVIDERS,
        local_only_dimensions=LOCAL_ONLY_DIMENSIONS,
    )


@app.route("/config", methods=["POST"])
def update_config():
    """Save config from form."""
    api_key = request.form.get("api_key", "").strip()
    dimension = request.form.get("dimension", str(DEFAULT_EMBEDDING_DIMENSION))
    provider = request.form.get("provider", DEFAULT_EMBEDDING_PROVIDER).strip()
    sim_thresh = request.form.get("similarity_threshold", str(SIMILARITY_THRESHOLD))
    sem_weight = request.form.get("semantic_edge_weight", str(SEMANTIC_EDGE_WEIGHT))

    try:
        dim = int(dimension)
    except ValueError:
        dim = DEFAULT_EMBEDDING_DIMENSION

    if dim not in VALID_DIMENSIONS:
        flash(f"Invalid dimension {dim}. Must be one of {VALID_DIMENSIONS}.", "error")
        return redirect(url_for("index"))

    if provider not in VALID_PROVIDERS:
        flash(f"Invalid provider '{provider}'.", "error")
        return redirect(url_for("index"))

    if provider == "local" and dim not in LOCAL_ONLY_DIMENSIONS:
        flash(
            f"Local provider only supports dimensions {LOCAL_ONLY_DIMENSIONS}.", "error"
        )
        return redirect(url_for("index"))

    try:
        threshold = max(0.0, min(1.0, float(sim_thresh)))
    except ValueError:
        threshold = SIMILARITY_THRESHOLD

    try:
        weight = max(0.0, min(1.0, float(sem_weight)))
    except ValueError:
        weight = SEMANTIC_EDGE_WEIGHT

    backend = _get_backend()
    try:
        # If api_key field is empty, keep existing key
        if not api_key:
            existing = backend.get_config()
            api_key = existing.get("isaacus_api_key") or ""
        backend.save_config(api_key, dim, provider, threshold, weight)
        flash("Configuration saved.", "success")
    except Exception as e:
        flash(f"Error saving config: {e}", "error")
    finally:
        backend.close()

    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Run controls — trigger import_agift.py on the worker container
# ---------------------------------------------------------------------------

# In-memory state for the current run (only one at a time)
_run_state = {
    "running": False,
    "output": "",
    "command": "",
}
_run_lock = threading.Lock()

DOCKER_BIN = os.environ.get("DOCKER_BIN", "docker")
WORKER_CONTAINER = os.environ.get("WORKER_CONTAINER", "agift-worker")

# Available run presets
RUN_PRESETS = {
    "full": {
        "label": "Full Pipeline",
        "desc": "Fetch + graph + embed + semantic edges",
        "args": [],
    },
    "graph_only": {
        "label": "Graph Only",
        "desc": "Fetch + graph, skip embeddings and semantic edges",
        "args": ["--skip-embed", "--skip-semantic"],
    },
    "local_384": {
        "label": "Local Embed (384d)",
        "desc": "Full pipeline with local sentence-transformers, 384 dim",
        "args": ["--provider", "local", "--dimension", "384"],
    },
    "local_768": {
        "label": "Local Embed (768d)",
        "desc": "Full pipeline with local sentence-transformers, 768 dim",
        "args": ["--provider", "local", "--dimension", "768"],
    },
    "dry_run": {
        "label": "Dry Run",
        "desc": "Fetch from API only, no writes",
        "args": ["--dry-run"],
    },
    "force_embed": {
        "label": "Force Re-embed",
        "desc": "Re-embed all + rebuild semantic edges",
        "args": ["--force-embed"],
    },
}


def _exec_worker(args: list[str]) -> None:
    """Run a command on the worker container in a background thread.

    Args:
        args: Arguments to pass to import_agift.py.
    """
    backend_args = ["--backend", BACKEND_TYPE] if BACKEND_TYPE != "neo4j" else []
    cmd = (
        [DOCKER_BIN, "exec", WORKER_CONTAINER, "python", "-u", "import_agift.py"]
        + backend_args
        + args
    )
    _run_state["command"] = " ".join(cmd)
    _run_state["output"] = ""
    _run_state["running"] = True

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            with _run_lock:
                _run_state["output"] += line
        proc.wait()
        with _run_lock:
            if proc.returncode != 0:
                _run_state["output"] += f"\n[exit code {proc.returncode}]"
    except Exception as e:
        with _run_lock:
            _run_state["output"] += f"\nERROR: {e}"
    finally:
        with _run_lock:
            _run_state["running"] = False


@app.route("/run", methods=["POST"])
def trigger_run():
    """Trigger an import run on the worker container."""
    if _run_state["running"]:
        flash("A run is already in progress.", "error")
        return redirect(url_for("index"))

    preset_key = request.form.get("preset", "full")
    preset = RUN_PRESETS.get(preset_key)
    if not preset:
        flash(f"Unknown preset '{preset_key}'.", "error")
        return redirect(url_for("index"))

    thread = threading.Thread(
        target=_exec_worker,
        args=(preset["args"],),
        daemon=True,
    )
    thread.start()
    flash(f"Started: {preset['label']}", "success")
    return redirect(url_for("index"))


@app.route("/run/status")
def run_status():
    """Return current run status as JSON (polled by the UI)."""
    with _run_lock:
        return jsonify(
            {
                "running": _run_state["running"],
                "command": _run_state["command"],
                "output": _run_state["output"],
            }
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
