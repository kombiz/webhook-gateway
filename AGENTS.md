# AGENTS.md

## Where this lives

`~/Documents/coding/development/edge/webhook-gateway/` — first entry in the
new `edge/` category dir. Future edge services (other Cloudflare workers,
R2-backed APIs, additional tunnels) should sit alongside it as siblings,
not nested deeper.

## What this is

A two-layer webhook receiver:

1. **Cloudflare Worker** (`workers/webhook-ingest/`) at `hooks.onlyarag.com` —
   edge validator, dispatches on path, forwards over the tunnel.
2. **FastAPI gateway** (`services/webhook_gateway/`) on `control.ts:4100` —
   re-validates, normalizes, persists, forwards to Alerta + Mattermost,
   serves a web UI.

The bridge between them is a Cloudflare tunnel
(`d7981d70-1f73-4930-b7f5-f6aede20e12e`) on `control.ts`. The
`webhook-tunnel.onlyarag.com` and `webhook-gw.onlyarag.com` hostnames
already point to it; the cloudflared config on control.ts is the source of
truth for ingress.

## Conventions

- The Worker source-of-truth is in this repo. The deployed Worker is
  `webhook-ingest` on the `Kombiz@gmail.com's Account` (id
  `619c16b6a2979f9d4769fbd522dd0315`).
- The KV namespace `WEBHOOK_ROUTES` (`0acf841b1f5f46a581dfd241a7e3b3a2`)
  holds per-provider config. **Edit via `scripts/populate-kv.sh`, not by
  hand in the dashboard.**
- Add a new source by:
  1. Adding a `case '<provider>':` in the Worker's `validateSignature`
  2. Adding a normalizer in `services/webhook_gateway/forwarder.py`
  3. Adding a validator in `services/webhook_gateway/signatures.py`
  4. Writing a KV entry
- Test: `pip install -e '.[dev]' && pytest -q` (CI runs ruff + pytest — see
  `.github/workflows/ci.yml`)
- Deploy:
  - Worker: `scripts/deploy-worker.sh`
  - Gateway: **autoDeploy** — pushing to `main` makes Dokploy rebuild on
    control.ts (webhook exemption added to the jtully edge 2026-06-17). Force a
    redeploy with `scripts/redeploy.sh` (needs DOKPLOY_API_KEY). Full topology in
    `docs/DEPLOYMENT.md`.
  - KV: `scripts/populate-kv.sh`

## Where secrets live

- `GATEWAY_TOKEN`, `ALERTA_TOKEN`, `MATTERMOST_WEBHOOK_URL`,
  `MELTWATER_WEBHOOK_SECRET`, `GITHUB_WEBHOOK_SECRET` — populate KV
  (for the per-provider secret) and Dokploy env (for the gateway-side
  secret). The values MUST match per provider.
- `CLOUDFLARE_API_TOKEN` — for `cloudflare-pp-cli`. Already in env.
- `DOKPLOY_API_KEY` — Dokploy. Source from `greymatter/.env` on control.ts.
- Cloudflare Worker `GATEWAY_TOKEN` secret — set via
  `cloudflare-pp-cli accounts workers ...` or wrangler `secret put`.

## What NOT to do

- Do not hand-edit the deployed Worker's source from the Cloudflare
  dashboard. The repo is the source of truth; the dashboard shows the
  deployed version, not the editable one.
- Do not put the Alerta token or Mattermost URL in KV. KV is for the
  Worker's per-provider HMAC secret + forward_to URL only. The gateway's
  downstream credentials live in its env.
- Do not add a 6th compose service to the dev area without first
  checking `.greymatter-dev-area.toml` limits (4 compose / 6 active).
  This repo is exempt from compose limits but the Worker + KV +
  Dokploy footprint still counts.

## Smoke tests

```bash
# Worker is up
curl -i https://hooks.onlyarag.com/        # 405 Method Not Allowed
curl -i https://hooks.onlyarag.com/github  # 404 (no KV entry) or 401/200

# Gateway is up (via tunnel)
curl -i https://webhook-tunnel.onlyarag.com/health  # {"status":"ok",...}
ssh laddy@control.ts 'curl -s http://localhost:4100/health'  # same

# Full chain
curl -i -X POST https://hooks.onlyarag.com/webhook/generic \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"smoke","body":"hello","severity":"info"}'
# Expected: 200 {"ok":true,"request_id":"..."} from Worker
# Then: 200 from gateway persisted to webhook_log
```
