#!/bin/bash
# Unified container entrypoint.
#
# Modes (set via AGIFT_MODE env var):
#   "dashboard"  — start gunicorn + optional cron  (default)
#   "worker"     — cron only, no web server
#   "cli"        — run the pipeline once and exit
#
# When AGIFT_CRON_ENABLED=1 (default in dashboard mode), a weekly cron
# job is installed alongside the web server.
set -e

MODE="${AGIFT_MODE:-dashboard}"
CRON_ENABLED="${AGIFT_CRON_ENABLED:-1}"

echo "=== AGIFT Container ==="
echo "Mode: ${MODE}"
echo "Started: $(date)"
echo ""

# ── Cron setup (shared by dashboard and worker modes) ────────────────
setup_cron() {
    # Dump runtime env vars so cron jobs can source them
    env | grep -E '^(NEO4J_|ISAACUS_|COGDB_|BACKEND_TYPE|PYTHONPATH|PATH|HOME|LANG|TRANSFORMERS_CACHE)' \
        | sed 's/=\(.*\)/="\1"/' > /app/.env.cron
    echo 'PYTHONPATH="/app"' >> /app/.env.cron

    cat > /etc/cron.d/weekly-agift <<'CRON'
# Weekly AGIFT refresh: Wednesday 4:00 AM UTC
0 4 * * 3 root /app/run_agift_refresh.sh >> /proc/1/fd/1 2>&1
CRON
    chmod 0644 /etc/cron.d/weekly-agift

    cat > /app/run_agift_refresh.sh <<'SCRIPT'
#!/bin/bash
set -e
set -a
source /app/.env.cron
set +a
cd /app
BACKEND_ARGS=""
if [ -n "$BACKEND_TYPE" ] && [ "$BACKEND_TYPE" != "neo4j" ]; then
  BACKEND_ARGS="--backend $BACKEND_TYPE"
fi
echo "=== AGIFT refresh started: $(date) ==="
python import_agift.py $BACKEND_ARGS
echo "=== AGIFT refresh finished: $(date) ==="
SCRIPT
    chmod +x /app/run_agift_refresh.sh

    # Start cron daemon in background
    cron
    echo "Cron installed (Wednesday 4:00 AM UTC)"
}

# ── Mode dispatch ────────────────────────────────────────────────────
case "$MODE" in
    dashboard)
        if [ "$CRON_ENABLED" = "1" ]; then
            setup_cron
        fi
        echo "Starting gunicorn on :5050 ..."
        exec gunicorn \
            --bind 0.0.0.0:5050 \
            --workers 2 \
            --timeout 300 \
            --access-logfile - \
            "dashboard.app:app"
        ;;

    worker)
        setup_cron
        echo "Worker mode — cron only, no web server."
        echo ""
        echo "Manual run:  docker exec <container> python import_agift.py"
        echo "Dry run:     docker exec <container> python import_agift.py --dry-run"
        echo ""
        # Keep container alive (cron is already running in background via setup_cron)
        exec tail -f /dev/null
        ;;

    cli)
        echo "Running pipeline once ..."
        exec python import_agift.py "$@"
        ;;

    *)
        echo "Unknown AGIFT_MODE: ${MODE}"
        echo "Valid modes: dashboard, worker, cli"
        exit 1
        ;;
esac
