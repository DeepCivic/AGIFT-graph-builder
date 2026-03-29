#!/bin/bash
# Container entrypoint: set up cron and keep the container alive.
set -e

echo "=== AGIFT Refresh Worker ==="
echo "Started: $(date)"

# Dump runtime env vars into a file cron jobs can source.
# Values are quoted so connection strings with special chars survive sourcing.
env | grep -E '^(NEO4J_|ISAACUS_|PYTHONPATH|PATH|HOME|LANG)' | sed 's/=\(.*\)/="\1"/' > /app/.env.cron
echo 'PYTHONPATH="/app"' >> /app/.env.cron

# Install the cron schedule
cat > /etc/cron.d/weekly-agift <<'CRON'
# Weekly AGIFT refresh: Wednesday 4:00 AM UTC
0 4 * * 3 root /app/run_agift_refresh.sh >> /proc/1/fd/1 2>&1
CRON
chmod 0644 /etc/cron.d/weekly-agift

# Create the wrapper script that sources env before running Python
cat > /app/run_agift_refresh.sh <<'SCRIPT'
#!/bin/bash
set -e
set -a
source /app/.env.cron
set +a
cd /app
echo "=== AGIFT refresh started: $(date) ==="
python import_agift.py
echo "=== AGIFT refresh finished: $(date) ==="
SCRIPT
chmod +x /app/run_agift_refresh.sh

echo "Cron schedule installed (Wednesday 4:00 AM UTC)"
echo "Container will stay alive. Logs go to stdout."
echo ""
echo "To trigger a manual run:"
echo "  docker exec agift-worker /app/run_agift_refresh.sh"
echo ""
echo "To dry-run:"
echo "  docker exec agift-worker python import_agift.py --dry-run"
echo ""

# Start cron in foreground (keeps container alive)
exec cron -f
