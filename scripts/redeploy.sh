#!/usr/bin/env bash
# Force a redeploy of the webhook-gateway Dokploy compose service.
#
# This is the PRIMARY deploy trigger. Dokploy's native push-to-deploy (GitHub
# App webhook / autoDeploy) does NOT fire in this homelab — its inbound webhook
# can't reach Dokploy through the Authentik-gated edge — so deploys are kicked
# off via the API instead. Run after merging to `main` (it makes Dokploy clone
# the latest main and rebuild), or to retry / force a rebuild after env edits.
#
# Requires:
#   DOKPLOY_API_KEY  — Dokploy API key (control.ts:/opt/stacks/greymatter/.env)
# Optional:
#   DOKPLOY_URL      — default http://gpu-vm-1.ts:3000 (host path, no Authentik)
#   COMPOSE_ID       — default is the live Monitoring/webhook-gateway compose
#
# Usage (run from a host on the tailnet, e.g. control.ts):
#   DOKPLOY_API_KEY=... scripts/redeploy.sh
set -euo pipefail

DOKPLOY_URL="${DOKPLOY_URL:-http://gpu-vm-1.ts:3000}"
DOKPLOY_API_KEY="${DOKPLOY_API_KEY:?DOKPLOY_API_KEY required}"
COMPOSE_ID="${COMPOSE_ID:-I5_Ypxvm1r9AnMGt1D_RY}"

echo "→ Triggering Dokploy redeploy (composeId=$COMPOSE_ID)..."
curl -sf -X POST "$DOKPLOY_URL/api/compose.deploy" \
  -H "x-api-key: $DOKPLOY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"composeId\": \"$COMPOSE_ID\"}"
echo

echo "Smoke test (wait ~20s for the build):"
echo "  ssh control.ts 'curl -s http://localhost:4100/health'"
echo "  curl -s https://webhook-gw.onlyarag.com/health"
