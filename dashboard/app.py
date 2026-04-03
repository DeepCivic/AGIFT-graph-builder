"""
AGIFT Dashboard — simple Flask app for worker config, run history, and run controls.

Features:
  - Set/view Isaacus API key and embedding provider
  - Set embedding dimension, similarity threshold, semantic edge weight
  - Trigger import runs from the UI (full, graph-only, dry-run)
  - Last 5 runs for AGIFT worker
  - Last 5 runs for enrichment worker
"""

import os
import subprocess
import threading

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from neo4j import GraphDatabase

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "agift-dashboard-dev")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "changeme")

VALID_DIMENSIONS = [256, 384, 512, 768, 1024, 1792]
VALID_PROVIDERS = ["isaacus", "local"]
LOCAL_ONLY_DIMENSIONS = [384, 768]  # dimensions available for local provider


def get_driver():
    """Create Neo4j driver."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def get_config(driver) -> dict:
    """Read config node from Neo4j."""
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Config {name: 'agift'}) "
            "RETURN c.isaacus_api_key AS api_key, "
            "       c.embedding_dimension AS dimension, "
            "       c.embedding_provider AS provider, "
            "       c.similarity_threshold AS sim_thresh, "
            "       c.semantic_edge_weight AS sem_weight"
        )
        record = result.single()
        if record:
            return {
                "api_key": record["api_key"] or "",
                "dimension": record["dimension"] or 512,
                "provider": record["provider"] or "isaacus",
                "similarity_threshold": record["sim_thresh"] or 0.70,
                "semantic_edge_weight": record["sem_weight"] or 0.5,
            }
    return {
        "api_key": "",
        "dimension": 512,
        "provider": "isaacus",
        "similarity_threshold": 0.70,
        "semantic_edge_weight": 0.5,
    }


def save_config(
    driver, api_key: str, dimension: int, provider: str,
    similarity_threshold: float, semantic_edge_weight: float,
) -> None:
    """Write config node to Neo4j."""
    with driver.session() as session:
        session.run(
            """
            MERGE (c:Config {name: 'agift'})
            SET c.isaacus_api_key = $key,
                c.embedding_dimension = $dim,
                c.embedding_provider = $provider,
                c.similarity_threshold = $sim_thresh,
                c.semantic_edge_weight = $sem_weight,
                c.updated_at = datetime()
            """,
            key=api_key,
            dim=dimension,
            provider=provider,
            sim_thresh=similarity_threshold,
            sem_weight=semantic_edge_weight,
        )


def get_run_logs(driver, worker: str, limit: int = 5) -> list[dict]:
    """Fetch recent run logs for a worker.

    Args:
        driver: Neo4j driver.
        worker: Worker name ('agift' or 'enrichment').
        limit: Max logs to return.

    Returns:
        List of run log dicts, newest first.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (r:RunLog {worker: $worker})
            RETURN r
            ORDER BY r.finished_at DESC
            LIMIT $limit
            """,
            worker=worker,
            limit=limit,
        )
        logs = []
        for record in result:
            node = record["r"]
            logs.append(dict(node))
        return logs


def get_graph_stats(driver) -> dict:
    """Get summary stats from the AGIFT graph.

    Args:
        driver: Neo4j driver.

    Returns:
        Dict with total_terms, embedded_terms, structural_edges,
        semantic_edges, by_depth.
    """
    with driver.session() as session:
        r = session.run("MATCH (t:Term) RETURN count(t) AS c").single()
        total = r["c"] if r else 0

        r = session.run(
            "MATCH (t:Term) WHERE t.embedding IS NOT NULL RETURN count(t) AS c"
        ).single()
        embedded = r["c"] if r else 0

        r = session.run(
            "MATCH ()-[e:PARENT_OF]->() RETURN count(e) AS c"
        ).single()
        structural_edges = r["c"] if r else 0

        r = session.run(
            "MATCH ()-[e:SIMILAR_TO]->() RETURN count(e) AS c"
        ).single()
        semantic_edges = r["c"] if r else 0

        result = session.run(
            "MATCH (t:Term) RETURN t.depth AS d, count(t) AS c ORDER BY d"
        )
        by_depth = {str(rec["d"]): rec["c"] for rec in result}

    return {
        "total_terms": total,
        "embedded_terms": embedded,
        "structural_edges": structural_edges,
        "semantic_edges": semantic_edges,
        "by_depth": by_depth,
    }


@app.route("/")
def index():
    """Dashboard home page."""
    driver = get_driver()
    try:
        config = get_config(driver)
        agift_logs = get_run_logs(driver, "agift", 5)
        enrichment_logs = get_run_logs(driver, "enrichment", 5)
        stats = get_graph_stats(driver)
    finally:
        driver.close()

    # Mask API key for display
    api_key = config["api_key"]
    masked_key = ""
    if api_key:
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"

    return render_template(
        "index.html",
        config=config,
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
    dimension = request.form.get("dimension", "512")
    provider = request.form.get("provider", "isaacus").strip()
    sim_thresh = request.form.get("similarity_threshold", "0.70")
    sem_weight = request.form.get("semantic_edge_weight", "0.5")

    try:
        dim = int(dimension)
    except ValueError:
        dim = 512

    if dim not in VALID_DIMENSIONS:
        flash(f"Invalid dimension {dim}. Must be one of {VALID_DIMENSIONS}.", "error")
        return redirect(url_for("index"))

    if provider not in VALID_PROVIDERS:
        flash(f"Invalid provider '{provider}'.", "error")
        return redirect(url_for("index"))

    if provider == "local" and dim not in LOCAL_ONLY_DIMENSIONS:
        flash(f"Local provider only supports dimensions {LOCAL_ONLY_DIMENSIONS}.", "error")
        return redirect(url_for("index"))

    try:
        threshold = max(0.0, min(1.0, float(sim_thresh)))
    except ValueError:
        threshold = 0.70

    try:
        weight = max(0.0, min(1.0, float(sem_weight)))
    except ValueError:
        weight = 0.5

    driver = get_driver()
    try:
        # If api_key field is empty, keep existing key
        if not api_key:
            existing = get_config(driver)
            api_key = existing["api_key"]
        save_config(driver, api_key, dim, provider, threshold, weight)
        flash("Configuration saved.", "success")
    except Exception as e:
        flash(f"Error saving config: {e}", "error")
    finally:
        driver.close()

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
        "desc": "Re-embed all terms + rebuild semantic edges",
        "args": ["--force-embed"],
    },
}


def _exec_worker(args: list[str]) -> None:
    """Run a command on the worker container in a background thread.

    Args:
        args: Arguments to pass to import_agift.py.
    """
    cmd = [DOCKER_BIN, "exec", WORKER_CONTAINER, "python", "-u", "import_agift.py"] + args
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
        return jsonify({
            "running": _run_state["running"],
            "command": _run_state["command"],
            "output": _run_state["output"],
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
