# Deployment

The FastAPI gateway is deployed and managed by **Dokploy** (build-from-GitHub)
on `control.ts`. The Cloudflare Worker + tunnel layer is deployed separately
(`scripts/deploy-worker.sh`, `scripts/populate-kv.sh`).

## Topology

```
push to main ─┬─► GitHub Actions CI (lint + tests)                 [GitHub-hosted]
              └─► Dokploy GitHub App webhook (autoDeploy)
                     └─► Dokploy clones latest main + docker compose up --build on control.ts
                 (manual / forced: scripts/redeploy.sh → compose.deploy API)

Cloudflare Worker (hooks.onlyarag.com)
   └─► tunnel d7981d70… ─► control.ts:4100 ─► webhook-gateway container
                            (also webhook-gw / webhook-tunnel .onlyarag.com)
```

## Dokploy service

| Field | Value |
|---|---|
| Project / env | `Monitoring` / `AFWukzA2jlQ-KaWRFLILT` |
| composeId | `I5_Ypxvm1r9AnMGt1D_RY` |
| appName | `webhook-gateway-pdd8eo` |
| Server | `control.ts` (`xDIyvfN5hlf847sTohuXD`) |
| Source | GitHub App `nUH-lwgQy…` → `kombiz/webhook-gateway` `main`, `./docker-compose.yml` |
| autoDeploy | `true` — push to `main` redeploys (enabled 2026-06-17, see CD note) |
| Host port | `4100` (the Cloudflare tunnel targets `localhost:4100`) |
| Volume | `webhook-gateway-pdd8eo_gateway-data` → `/data` (SQLite) |

## CI/CD

- **CI** — `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`,
  and `pytest` on every push to `main` and every PR (GitHub-hosted runner, no
  secrets needed).
- **CD** — Dokploy's GitHub App redeploys on push to `main` (`autoDeploy`):
  clone latest `main` + `docker compose up --build` on control.ts.

  > **Enabled 2026-06-17:** Dokploy's webhook receiver (`/api/deploy/*`) was
  > exempted from Authentik SSO on the jtully edge
  > (`/opt/stacks/caddy/sites/dokploy.Caddyfile`) so GitHub's signed webhook can
  > reach Dokploy. Before that, push-to-deploy 302'd at the Authentik gate. The
  > exemption is scoped to `/api/deploy/*` only (Dokploy verifies each webhook by
  > GitHub HMAC / refreshToken); the admin UI + tRPC API stay SSO-gated.

  `scripts/redeploy.sh` (`compose.deploy` API on the `gpu-vm-1.ts:3000` host
  path) remains for manual / forced redeploys (e.g. after editing env vars).

## Secrets

Runtime env lives in the Dokploy compose service (control.ts Dokploy DB), not in
git. The 7 vars (`GATEWAY_TOKEN`, `ALERTA_URL`, `ALERTA_TOKEN`,
`MATTERMOST_WEBHOOK_URL`, `MATTERMOST_CHANNEL`, `WEBHOOK_DB_PATH`,
`PYTHONUNBUFFERED`) were seeded from the original `/opt/stacks/webhook-gateway/.env`
(now archived at `control.ts:/opt/stacks/.backups/webhook-gateway.predokploy/`).
Edit them in the Dokploy UI, then `scripts/redeploy.sh`.

## Manual operations

```bash
# Force a redeploy (no code change) — run from a tailnet host
DOKPLOY_API_KEY=… scripts/redeploy.sh

# Health
ssh control.ts 'curl -s http://localhost:4100/health'
curl -s https://webhook-gw.onlyarag.com/health
```

## Rollback

- **UI**: Dokploy → Monitoring → webhook-gateway → Deployments → redeploy a prior
  entry (Dokploy keeps per-deployment history).
- **Git**: revert the offending commit on `main`; autoDeploy ships the revert.
