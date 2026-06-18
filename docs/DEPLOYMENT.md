# Deployment

The FastAPI gateway is deployed and managed by **Dokploy** (build-from-GitHub)
on `control.ts`. The Cloudflare Worker + tunnel layer is deployed separately
(`scripts/deploy-worker.sh`, `scripts/populate-kv.sh`).

## Topology

```
push to main ──► GitHub Actions CI: lint + tests          [GitHub-hosted runner]
                   └─(green)─► deploy job                  [self-hosted tailnet runner]
                                 └─► Dokploy API compose.deploy
                                       └─► clone latest main + docker compose up --build on control.ts

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
| autoDeploy | `true` (set) but inert — CD is driven by the Actions deploy job, not Dokploy's webhook |
| Host port | `4100` (the Cloudflare tunnel targets `localhost:4100`) |
| Volume | `webhook-gateway-pdd8eo_gateway-data` → `/data` (SQLite) |

## CI/CD

- **CI** — `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`,
  and `pytest` on every push to `main` and every PR (GitHub-hosted runner, no
  secrets needed).
- **CD** — automated on push to `main`. The `deploy` job in `ci.yml` runs on a
  **self-hosted tailnet runner** (`webhook-gateway-tailnet` on `development.ts`,
  systemd `actions.runner.kombiz-webhook-gateway.webhook-gateway-tailnet`) after
  `lint-test` passes, and POSTs `compose.deploy` to the Dokploy API
  (`gpu-vm-1.ts:3000`, reachable over Tailscale) using the `DOKPLOY_API_KEY` repo
  secret. Dokploy then clones latest `main` and rebuilds on control.ts; the job
  waits for `webhook-gw.onlyarag.com/health` → 200.

  > **Why a runner (not Dokploy's native autoDeploy):** `dokploy.onlyarag.com`
  > resolves only to jtully's Tailscale IP (`100.67.230.119`), so GitHub webhooks
  > can't reach it (`502`). The tailnet runner reaches the Dokploy API directly.
  > (An Authentik SSO exemption for `/api/deploy/*` was trialed on the jtully edge
  > but isn't needed for this path and was reverted.)

  `scripts/redeploy.sh` (same `compose.deploy` API) remains for manual / forced
  redeploys from any tailnet host (e.g. after editing env vars in the Dokploy UI).

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
