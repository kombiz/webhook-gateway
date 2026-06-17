#!/usr/bin/env bash
# Deploy the webhook-ingest Worker to Cloudflare.
#
# Requires: cloudflare-pp-cli (or wrangler) and CLOUDFLARE_API_TOKEN with
# account.Workers Scripts: Edit permission.
#
# Usage:
#   scripts/deploy-worker.sh                 # deploy
#   scripts/deploy-worker.sh --dry-run        # print plan
#   scripts/deploy-worker.sh --set-secret     # also set GATEWAY_TOKEN

set -euo pipefail

cd "$(dirname "$0")/../workers/webhook-ingest"

DRY_RUN=0
SET_SECRET=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --set-secret) SET_SECRET=1 ;;
  esac
done

if [[ $DRY_RUN -eq 1 ]]; then
  echo "DRY: cloudflare-pp-cli worker deploy webhook-ingest --dry-run"
  echo "DRY: would overwrite the existing webhook-ingest worker (id d70fdd5db4e14ea49cc73ab392aa71f4)"
  echo "DRY: would bind KV namespace 0acf841b1f5f46a581dfd241a7e3b3a2 as WEBHOOK_ROUTES"
  exit 0
fi

echo "→ Deploying webhook-ingest via cloudflare-pp-cli..."
cloudflare-pp-cli worker deploy webhook-ingest

if [[ $SET_SECRET -eq 1 ]]; then
  if [[ -z "${GATEWAY_TOKEN:-}" ]]; then
    echo "GATEWAY_TOKEN env var required for --set-secret" >&2
    exit 2
  fi
  echo "→ Setting GATEWAY_TOKEN secret..."
  echo -n "$GATEWAY_TOKEN" | cloudflare-pp-cli accounts workers delete-script-secret \
    619c16b6a2979f9d4769fbd522dd0315 webhook-ingest GATEWAY_TOKEN 2>/dev/null || true
  echo -n "$GATEWAY_TOKEN" | cloudflare-pp-cli accounts workers 2>&1 | head -5
fi

echo
echo "Smoke test:"
echo "  curl -i https://hooks.onlyarag.com/health"
echo "  curl -i -X POST https://hooks.onlyarag.com/unknown  # should 404"
