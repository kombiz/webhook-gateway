#!/usr/bin/env bash
# Force a redeploy of the webhook-gateway Dokploy compose service.
#
# This is the working deploy trigger. Push-to-deploy is NOT wired: Dokploy
# (dokploy.onlyarag.com) resolves only to a Tailscale IP, so GitHub webhooks
# can't reach it. Run this after merging to `main` (Dokploy clones latest main
# and rebuilds), or to force a rebuild after editing env vars in the UI.
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
