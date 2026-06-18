#!/usr/bin/env bash
# Force a redeploy of the webhook-gateway Dokploy compose service.
#
# Normal deploys are automatic: Dokploy's GitHub App redeploys on every push to
# `main` (autoDeploy). Use this only to force a rebuild without a code change
# (e.g. after editing env vars in the Dokploy UI, or to retry a failed deploy).
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
