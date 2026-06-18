# Deployment

The FastAPI gateway is deployed and managed by **Dokploy** (build-from-GitHub)
on `control.ts`. The Cloudflare Worker + tunnel layer is deployed separately
(`scripts/deploy-worker.sh`, `scripts/populate-kv.sh`).

## Topology

```
push to main ──► Dokploy GitHub App (autoDeploy) ──► clone + docker compose up --build on control.ts
                                                       │
GitHub Actions CI (lint + tests) runs in parallel ◄────┘ (advisory signal)

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
| autoDeploy | `true` (push to `main` redeploys) |
| Host port | `4100` (the Cloudflare tunnel targets `localhost:4100`) |
| Volume | `webhook-gateway-pdd8eo_gateway-data` → `/data` (SQLite) |

## CI/CD

- **CI** — `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`,
  and `pytest` on every push to `main` and every PR (GitHub-hosted runner, no
  secrets needed).
- **CD** — Dokploy's GitHub App redeploys on push to `main`. CI and CD run
  independently; to make deploys *gated* on green CI, either:
  1. enable branch protection on `main` requiring the `Lint & test` check and
     develop via PRs, or
  2. disable Dokploy autoDeploy and trigger `compose.deploy` from a CI job on a
     tailnet-reachable self-hosted runner.

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
