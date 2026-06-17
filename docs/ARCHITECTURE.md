# Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  External webhook sources                                               │
│  (GitHub, Meltwater, Slack, Stripe, Linear, generic)                    │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │ POST /<provider>
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Cloudflare Worker: webhook-ingest (hooks.onlyarag.com)                 │
│                                                                         │
│  1. Read `provider` from URL path                                       │
│  2. Look up `env.WEBHOOK_ROUTES.get(provider)` → JSON config            │
│     { secret, forward_to, passthrough? }                                │
│  3. Validate HMAC signature (provider-specific)                         │
│  4. Forward POST → config.forward_to (fire-and-forget via waitUntil)    │
│  5. Return 200 {ok: true, request_id}                                   │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │ over Cloudflare Tunnel
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  webhook-tunnel.onlyarag.com (and webhook-gw.onlyarag.com)              │
│  → http://localhost:4100 on control.ts via cloudflared                  │
└─────────────────────┬───────────────────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FastAPI: webhook-gateway (control.ts:4100)                             │
│                                                                         │
│  • Re-validates signature (defense in depth)                            │
│  • Normalizes payload per source type                                   │
│  • Persists to SQLite (webhook_log)                                     │
│  • Forwards to Alerta (per source severity)                             │
│  • Forwards to Mattermost (human-readable message)                      │
│  • Persists Meltwater payloads to meltwater_inbox table                 │
│  • Serves web UI at /, /endpoints, /api/webhooks                       │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐
   │ Alerta  │  │Mattermost│  │  SQLite  │
   │ :4000   │  │ incoming │  │ inbox +  │
   │         │  │ webhook  │  │ webhook_ │
   │         │  │          │  │   log    │
   └─────────┘  └──────────┘  └──────────┘
```

## Why two layers of validation

The Worker validates signatures at the edge so we can short-circuit spoofed
requests without spending a tunnel roundtrip or FastAPI processing time. The
gateway re-validates because the request still has to authenticate against its
own secret store — and the gateway needs to know the signature was valid
before it logs or forwards anything. This is defense in depth, not duplication.

## Why KV-driven dispatch

The Worker used to hardcode path-to-source routing. That made every new
provider a deploy. KV-driven dispatch lets us add a new provider by writing
one JSON entry — no Worker redeploy needed. The Worker code is stable; the
provider catalog lives in `WEBHOOK_ROUTES` and is editable via
`scripts/populate-kv.sh`.

## Provider config schema

```json
{
  "secret": "<shared-secret-with-the-source>",
  "forward_to": "https://webhook-tunnel.onlyarag.com/webhook/<source>",
  "passthrough": ["<header-1>", "<header-2>"]
}
```

- `secret` — used by the Worker's HMAC validator. **Do not** put the same
  value in two providers.
- `forward_to` — the URL the Worker POSTs to after validation. Defaults to
  the tunneled gateway, but a provider can point anywhere.
- `passthrough` — optional list of header names the Worker should copy from
  the inbound request onto the forwarded request (signature, event id,
  delivery id, etc.).

## Why a tunnel (and not direct DNS)

`webhook-tunnel.onlyarag.com` and `webhook-gw.onlyarag.com` resolve to
Cloudflare's edge, which forwards to `cloudflared` running on `control.ts`.
This means the gateway never exposes a public port — only outbound 7844
to `cfargotunnel.com`. The tunnel UUID is `d7981d70-1f73-4930-b7f5-f6aede20e12e`
and its config lives at `/etc/cloudflared/config.yml` on `control.ts`.

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Provider has no KV entry | Worker returns `404 "Unknown provider"` immediately | `scripts/populate-kv.sh <provider>` |
| Bad signature | Worker returns `401 Unauthorized`, logs to console | Rotate secret; the source needs the new value too |
| Gateway down | Worker gets 502 from forward, logs to console; the inbound POST still returns 200 (forward is `waitUntil`) | Restart gateway; tunnel will reconnect on its own |
| Alerta down | Gateway logs `forward_status: 502` to `webhook_log` | Restart Alerta; webhooks that hit during the outage stay in `webhook_log` for replay |
| Mattermost down | Same as Alerta | Same |
| Tunnel down | All `*.onlyarag.com` requests get 502 from Cloudflare edge | Restart `cloudflared` on control.ts; tunnel will reconnect |
| Meltwater inbox overflow | Disk fills up | Add a periodic cleanup job (not implemented yet) |

## Why "fire-and-forget" on forward

The Worker returns 200 to the source the moment signature validation passes
and `ctx.waitUntil(fetch(...))` is enqueued. This means:
- Sources see consistent low latency (50-80ms typical).
- If the gateway is slow but reachable, webhooks still complete from the
  source's perspective.
- If the gateway is dead, we discover it via the `webhook_log` table and
  the Worker's `console.error` lines, not via the source's retry storm.

The tradeoff: the source never knows forwarding failed. We accept that
because the gateway persists every received webhook, so replay is a
one-liner against `webhook_log`.
