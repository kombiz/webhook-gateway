#!/usr/bin/env bash
# Deploy the FastAPI gateway to Dokploy.
#
# Requires:
#   - DOKPLOY_API_KEY in the environment (source greymatter .env on control.ts)
#   - DOKPLOY_PROJECT_ID and DOKPLOY_SERVER_ID for the homelab project on control.ts
#   - secrets.sh sourced with: GATEWAY_TOKEN, ALERTA_TOKEN, MATTERMOST_WEBHOOK_URL
#
# Usage:
#   scripts/deploy-dokploy.sh

set -euo pipefail

DOKPLOY_URL="${DOKPLOY_URL:-https://dokploy.onlyarag.com}"
DOKPLOY_API_KEY="${DOKPLOY_API_KEY:?DOKPLOY_API_KEY required}"
PROJECT_ID="${DOKPLOY_PROJECT_ID:?DOKPLOY_PROJECT_ID required (e.g. main homelab project)}"
SERVER_ID="${DOKPLOY_SERVER_ID:?DOKPLOY_SERVER_ID required (e.g. control.ts)}"

ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT

cat > "$ENV_FILE" <<EOF
PYTHONUNBUFFERED=1
WEBHOOK_DB_PATH=/data/webhook-gateway.db
GATEWAY_TOKEN=${GATEWAY_TOKEN:?required}
ALERTA_URL=${ALERTA_URL:-http://alerta:4000}
ALERTA_TOKEN=${ALERTA_TOKEN:-}
MATTERMOST_WEBHOOK_URL=${MATTERMOST_WEBHOOK_URL:-}
MATTERMOST_CHANNEL=${MATTERMOST_CHANNEL:-}
EOF

echo "→ Creating compose on Dokploy (project=$PROJECT_ID, server=$SERVER_ID)..."
CREATE_RESP=$(curl -sf -X POST "$DOKPLOY_URL/api/compose.create" \
  -H "x-api-key: $DOKPLOY_API_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<JSON
{
  "projectId": "$PROJECT_ID",
  "serverId": "$SERVER_ID",
  "name": "webhook-gateway",
  "appName": "webhook-gateway",
  "dockerCompose": "$(jq -Rs . < docker-compose.yml)",
  "env": $(jq -Rs . < "$ENV_FILE")
}
JSON
)
COMPOSE_ID=$(echo "$CREATE_RESP" | jq -r '.composeId')
echo "  composeId=$COMPOSE_ID"

echo "→ Deploying..."
curl -sf -X POST "$DOKPLOY_URL/api/compose.deploy" \
  -H "x-api-key: $DOKPLOY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"composeId\": \"$COMPOSE_ID\"}" | jq .

echo
echo "Smoke test (wait ~15s for container to come up):"
echo "  sleep 15 && ssh laddy@control.ts 'curl -s http://localhost:4100/health'"
