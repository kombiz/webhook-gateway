# Deployment

The FastAPI gateway is deployed and managed by **Dokploy** (build-from-GitHub)
on `control.ts`. The Cloudflare Worker + tunnel layer is deployed separately
(`scripts/deploy-worker.sh`, `scripts/populate-kv.sh`).

## Topology

```
push to main ──► GitHub Actions CI (lint + tests)            [GitHub-hosted]
merge, then  ──► scripts/redeploy.sh  →  Dokploy API compose.deploy
                     └─► Dokploy clones latest main + docker compose up --build on control.ts
                 (push-to-deploy webhook is NOT wired — Dokploy is Tailscale-only; see CD note)

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
| autoDeploy | `true` (set) — but inert; the webhook can't reach Tailscale-only Dokploy (see CD note) |
| Host port | `4100` (the Cloudflare tunnel targets `localhost:4100`) |
| Volume | `webhook-gateway-pdd8eo_gateway-data` → `/data` (SQLite) |

## CI/CD

- **CI** — `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`,
  and `pytest` on every push to `main` and every PR (GitHub-hosted runner, no
  secrets needed).
- **CD** — `scripts/redeploy.sh` POSTs `compose.deploy` to the Dokploy API
  (`gpu-vm-1.ts:3000` host path), which makes Dokploy clone latest `main` and
  rebuild on control.ts. Run after merging to `main`. This is the working path.

  > **Push-to-deploy is NOT wired (2026-06-17).** Two blockers were found:
  > 1. Authentik SSO gated `dokploy.onlyarag.com` → **fixed** by exempting
  >    `/api/deploy/*` on the jtully edge (`sites/dokploy.Caddyfile`). The
  >    compose webhook is `POST /api/deploy/compose/<refreshToken>` with an
  >    `X-GitHub-Event: push` header; verified it deploys.
  > 2. **`dokploy.onlyarag.com` resolves only to jtully's Tailscale IP
  >    (`100.67.230.119`)** — not routable from the public internet — so a
  >    GitHub repo webhook gets `502 failed to connect`. Dokploy has no public
  >    ingress. Enabling push-to-deploy needs one (Cloudflare tunnel / Pangolin
  >    edge) **or** a self-hosted tailnet runner triggering `redeploy.sh`.

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
