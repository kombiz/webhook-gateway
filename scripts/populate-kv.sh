#!/usr/bin/env bash
# Populate the WEBHOOK_ROUTES KV namespace with per-provider config.
#
# Each KV entry is a JSON document of the form:
#   { "secret": "...", "forward_to": "https://...", "passthrough": ["..."] }
#
# Required env vars (or pass via flags):
#   CF_ACCOUNT_ID       — Cloudflare account id
#   KV_NAMESPACE_ID     — KV namespace id (default: 0acf841b1f5f46a581dfd241a7e3b3a2)
#   GITHUB_WEBHOOK_SECRET
#   MELTWATER_WEBHOOK_SECRET
#   GATEWAY_FORWARD_URL — base URL the worker forwards to
#                          (default: https://webhook-tunnel.onlyarag.com)
#   GATEWAY_TOKEN        — used as the secret for the "generic" provider
#
# Usage:
#   scripts/populate-kv.sh --dry-run   # print commands, don't write
#   scripts/populate-kv.sh             # write to KV

set -euo pipefail

ACCOUNT_ID="${CF_ACCOUNT_ID:-619c16b6a2979f9d4769fbd522dd0315}"
NAMESPACE_ID="${KV_NAMESPACE_ID:-0acf841b1f5f46a581dfd241a7e3b3a2}"
GATEWAY_BASE="${GATEWAY_FORWARD_URL:-https://webhook-tunnel.onlyarag.com}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

write_kv() {
  local key="$1" value="$2"
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "DRY: cloudflare-pp-cli accounts storage workers-kv-namespace-write-key-value-pair-with-metadata %q %q %q --value %q\n" \
      "$key" "$NAMESPACE_ID" "$ACCOUNT_ID" "$value"
    return
  fi
  cloudflare-pp-cli accounts storage workers-kv-namespace-write-key-value-pair-with-metadata \
    "$key" "$NAMESPACE_ID" "$ACCOUNT_ID" \
    --metadata "{\"key\":\"$key\",\"source\":\"webhook-gateway\"}" \
    --value "$value" 2>&1 | tail -2
  echo "  ✓ $key"
}

# ── GitHub ─────────────────────────────────────────────
if [[ -n "${GITHUB_WEBHOOK_SECRET:-}" ]]; then
  write_kv "github" "$(cat <<EOF
{"secret":"$GITHUB_WEBHOOK_SECRET","forward_to":"$GATEWAY_BASE/webhook/github","passthrough":["x-github-event","x-github-delivery","x-hub-signature-256"]}
EOF
)"
fi

# ── Meltwater ──────────────────────────────────────────
if [[ -n "${MELTWATER_WEBHOOK_SECRET:-}" ]]; then
  write_kv "meltwater" "$(cat <<EOF
{"secret":"$MELTWATER_WEBHOOK_SECRET","forward_to":"$GATEWAY_BASE/webhook/meltwater","passthrough":["x-meltwater-signature","x-meltwater-event"]}
EOF
)"
fi

# ── Slack ──────────────────────────────────────────────
if [[ -n "${SLACK_WEBHOOK_SECRET:-}" ]]; then
  write_kv "slack" "$(cat <<EOF
{"secret":"$SLACK_WEBHOOK_SECRET","forward_to":"$GATEWAY_BASE/webhook/slack","passthrough":["x-slack-signature","x-slack-request-timestamp"]}
EOF
)"
fi

# ── Generic ────────────────────────────────────────────
if [[ -n "${GATEWAY_TOKEN:-}" ]]; then
  write_kv "generic" "$(cat <<EOF
{"secret":"$GATEWAY_TOKEN","forward_to":"$GATEWAY_BASE/webhook/generic"}
EOF
)"
fi

echo
echo "Done. Verify with:"
echo "  cloudflare-pp-cli accounts storage workers-kv-namespace-list-a-namespace-s-keys $NAMESPACE_ID $ACCOUNT_ID"
