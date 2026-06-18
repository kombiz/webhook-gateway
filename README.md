# Webhook Gateway

[![CI](https://github.com/kombiz/webhook-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/kombiz/webhook-gateway/actions/workflows/ci.yml)

A self-hosted webhook gateway that receives webhooks from external services (GitHub, Slack, Prometheus, etc.), logs them, provides a web UI for management, and forwards normalized events to [Alerta](https://github.com/kombiz/alerta).

## Architecture

```
External Services (GitHub, Slack, etc.)
         |
         v
  hooks.onlyarag.com          Cloudflare Worker
  (public endpoint)            validates, routes, forwards
         |
         v
  webhook-tunnel.onlyarag.com  Cloudflare Tunnel
  (CNAME -> cfargotunnel.com)  outbound connection, no inbound ports
         |
         v
  localhost:4100               Webhook Gateway (this service)
  (FastAPI + SQLite)           logs, normalizes, forwards
         |
         v
  localhost:4000               Alerta (Phoenix)
  (alert dashboard)            receives normalized events
```

## Features

- **Webhook reception** — receives webhooks via `POST /webhook/{source}` with source-specific normalization
- **Signature validation** — GitHub HMAC-SHA256, generic Bearer token auth
- **Source adapters** — GitHub (push, PR, issues, workflow_run), Prometheus/Alertmanager, Slack, generic
- **Web UI** — dark-themed dashboard showing webhook log + endpoint management page
- **REST API** — full CRUD for endpoints, webhook log query with pagination
- **Alerta forwarding** — normalizes events and POSTs to Alerta's ingest API
- **Cloudflare Worker** — public-facing proxy at `hooks.onlyarag.com` that routes to the gateway via tunnel

## Quick Start

### 1. Run the gateway

```bash
# With Docker
docker compose up -d

# Or directly
pip install -e .
ALERTA_URL=http://localhost:4000 ALERTA_TOKEN=your_token \
  uvicorn services.webhook_gateway.main:app --host 0.0.0.0 --port 4100
```

### 2. Open the UI

- Dashboard: `http://localhost:4100/`
- Endpoints: `http://localhost:4100/endpoints`

### 3. Create an endpoint

Via UI or API:

```bash
curl -X POST http://localhost:4100/api/endpoints \
  -H "Content-Type: application/json" \
  -d '{"name": "GitHub CI", "source_type": "github"}'
```

### 4. Send a test webhook

```bash
curl -X POST http://localhost:4100/webhook/generic \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Event", "body": "Hello from webhook gateway", "severity": "info"}'
```

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/health` | No | Health check |
| `GET` | `/` | No | Dashboard (HTML) |
| `GET` | `/endpoints` | No | Endpoint management (HTML) |
| `POST` | `/webhook/{source}` | No* | Receive webhook (github, slack, prometheus, generic) |
| `GET` | `/api/endpoints` | Bearer | List endpoints |
| `POST` | `/api/endpoints` | Bearer | Create endpoint |
| `PUT` | `/api/endpoints/{id}` | Bearer | Update endpoint |
| `DELETE` | `/api/endpoints/{id}` | Bearer | Delete endpoint |
| `GET` | `/api/webhooks` | Bearer | List webhook log (`?limit=50&offset=0`) |

\* Signature validation per endpoint config (GitHub HMAC-SHA256 or Bearer token).

Auth is optional — set `GATEWAY_TOKEN` env var to enable Bearer token auth on API endpoints.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBHOOK_DB_PATH` | `/data/webhook-gateway.db` | SQLite database path |
| `ALERTA_URL` | `http://localhost:4000` | Alerta backend URL |
| `ALERTA_TOKEN` | (empty) | Bearer token for Alerta API |
| `GATEWAY_TOKEN` | (empty) | Bearer token for gateway API (optional) |

## Cloudflare Integration

### Tunnel Setup (on the gateway host)

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create webhook-gateway

# Route DNS
cloudflared tunnel route dns <TUNNEL_ID> webhook-tunnel.yourdomain.com

# Write config (/etc/cloudflared/config.yml)
# tunnel: <TUNNEL_ID>
# credentials-file: ~/.cloudflared/<TUNNEL_ID>.json
# ingress:
#   - hostname: webhook-tunnel.yourdomain.com
#     service: http://localhost:4100
#   - hostname: webhook-gw.yourdomain.com
#     service: http://localhost:4100
#   - service: http_status:404

# Start as service
cloudflared service install
systemctl enable --now cloudflared
```

### Worker Deployment

```bash
cd workers/webhook-ingest
npm install
npx wrangler deploy

# Set secrets
npx wrangler secret put GATEWAY_TOKEN
```

### GitHub Webhook Setup

Per-repo:
```bash
gh api repos/OWNER/REPO/hooks -X POST \
  -f "name=web" \
  -f "config[url]=https://hooks.yourdomain.com/github" \
  -f "config[content_type]=json" \
  -f "events[]=push" -f "events[]=pull_request" \
  -f "events[]=issues" -f "events[]=workflow_run" \
  -F "active=true"
```

Org-wide:
```bash
gh api orgs/YOUR_ORG/hooks -X POST \
  -f "name=web" \
  -f "config[url]=https://hooks.yourdomain.com/github" \
  -f "config[content_type]=json" \
  -f "events[]=push" -f "events[]=pull_request" \
  -f "events[]=issues" -f "events[]=workflow_run" \
  -F "active=true"
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/webhook_gateway/ -v
```

30 tests across 5 files covering models, database, signatures, forwarder, and API.

## Project Structure

```
services/webhook_gateway/
  main.py          FastAPI app, routes, lifespan
  models.py        Pydantic models (Endpoint, WebhookLog, SourceType)
  db.py            SQLite database layer (aiosqlite)
  forwarder.py     Alerta event normalizer and forwarder
  signatures.py    HMAC-SHA256 and Bearer token validation
  templates/       Jinja2 templates (dashboard, endpoints)
  static/          CSS

workers/webhook-ingest/
  src/index.ts     Cloudflare Worker (routes webhooks to tunnel)
  wrangler.toml    Worker config with custom domain

tests/webhook_gateway/
  test_models.py, test_db.py, test_signatures.py,
  test_forwarder.py, test_api.py
```

## License

MIT
