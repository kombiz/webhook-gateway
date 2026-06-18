# Deployment

The FastAPI gateway is deployed and managed by **Dokploy** (build-from-GitHub)
on `control.ts`. The Cloudflare Worker + tunnel layer is deployed separately
(`scripts/deploy-worker.sh`, `scripts/populate-kv.sh`).

## Topology

```
merge to main ──► GitHub Actions CI (lint + tests)   [GitHub-hosted]
              └─► scripts/redeploy.sh  →  Dokploy API compose.deploy
                     └─► Dokploy clones latest main + docker compose up --build on control.ts

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
| autoDeploy | `true` (set) — but **non-functional**, see CD note below |
| Host port | `4100` (the Cloudflare tunnel targets `localhost:4100`) |
| Volume | `webhook-gateway-pdd8eo_gateway-data` → `/data` (SQLite) |

## CI/CD

- **CI** — `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`,
  and `pytest` on every push to `main` and every PR (GitHub-hosted runner, no
  secrets needed).
- **CD** — `scripts/redeploy.sh` POSTs `compose.deploy` to the Dokploy API,
  which makes Dokploy clone the latest `main` and rebuild on control.ts. Run it
  after merging to `main`.

  > **Verified 2026-06-17:** Dokploy's *native* push-to-deploy (GitHub App
  > webhook / `autoDeploy`) does **not** fire here — the inbound webhook can't
  > reach Dokploy through the Authentik-gated `dokploy.onlyarag.com` edge (the
  > same gate that forces API calls onto the `gpu-vm-1.ts:3000` host path).
  > Pushing to `main` runs CI but does **not** redeploy on its own.

  Fully-automated CD (no manual step) would need either the Dokploy webhook
  ingress exempted from Authentik (benefits every Dokploy app), or a self-hosted
  tailnet runner invoking `scripts/redeploy.sh` from a CI job after tests pass.

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
