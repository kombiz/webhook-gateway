// Cloudflare Worker: webhook-ingest
// Provider-dispatched HMAC validator + forwarder. Looks up per-provider
// config in the WEBHOOK_ROUTES KV namespace and forwards validated
// requests to the gateway over the Cloudflare tunnel.

interface Env {
  WEBHOOK_ROUTES: KVNamespace;
  GATEWAY_TOKEN: string;
}

interface ProviderConfig {
  secret: string;
  forward_to: string;
  passthrough?: string[]; // header names to forward unchanged
}

interface ProviderSpec {
  signatureHeader?: string;
  eventHeader?: string;
  deliveryHeader?: string;
}

// Provider signatures are validated inside the Worker. The gateway
// re-validates using its own copy of the secret, so the Worker can
// keep a single canonical set of validator functions per provider.
const PROVIDERS: Record<string, ProviderSpec> = {
  github: {
    signatureHeader: "x-hub-signature-256",
    eventHeader: "x-github-event",
    deliveryHeader: "x-github-delivery",
  },
  stripe: { signatureHeader: "stripe-signature" },
  linear: {
    signatureHeader: "linear-signature",
    eventHeader: "linear-event",
    deliveryHeader: "linear-delivery",
  },
  meltwater: { signatureHeader: "x-meltwater-signature" },
  slack: {
    signatureHeader: "x-slack-signature",
    eventHeader: "x-slack-event",
  },
};

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const segments = url.pathname.replace(/^\//, "").split("/");
    const provider = segments[0];
    if (!provider) {
      return new Response("Not Found", { status: 404 });
    }

    const configStr = await env.WEBHOOK_ROUTES.get(provider);
    if (!configStr) {
      return new Response(`Unknown provider: ${provider}`, { status: 404 });
    }

    let config: ProviderConfig;
    try {
      config = JSON.parse(configStr);
    } catch {
      return new Response("Internal Server Error", { status: 500 });
    }

    const body = await request.arrayBuffer();
    const requestId = crypto.randomUUID();

    const valid = await validateSignature(request, body, provider, config.secret);
    if (!valid) {
      console.error(
        `[${requestId}] Signature validation failed for provider=${provider} ip=${request.headers.get("cf-connecting-ip")}`
      );
      return new Response("Unauthorized", { status: 401 });
    }

    const forwardUrl = config.forward_to + (segments.length > 1 ? "/" + segments.slice(1).join("/") : "");
    const forwardHeaders = buildForwardHeaders(request, provider, requestId, config);

    ctx.waitUntil(
      fetch(forwardUrl, { method: "POST", headers: forwardHeaders, body })
        .then((res) => {
          if (!res.ok) {
            console.error(
              `[${requestId}] Forward returned ${res.status} for provider=${provider}`
            );
          }
        })
        .catch((err) =>
          console.error(`[${requestId}] Forward failed for provider=${provider}: ${err.message}`)
        )
    );

    return new Response(JSON.stringify({ ok: true, request_id: requestId }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};

async function validateSignature(
  request: Request,
  body: ArrayBuffer,
  provider: string,
  secret: string
): Promise<boolean> {
  switch (provider) {
    case "github":
      return validateGitHub(request, body, secret);
    case "stripe":
      return validateStripe(request, body, secret);
    case "linear":
      return validateLinear(request, body, secret);
    case "slack":
      return validateSlack(request, body, secret);
    case "meltwater":
      return validateMeltwater(request, body, secret);
    default:
      return validateGenericHmac(request, body, secret);
  }
}

async function validateGitHub(request: Request, body: ArrayBuffer, secret: string): Promise<boolean> {
  const sig = request.headers.get("x-hub-signature-256");
  if (!sig?.startsWith("sha256=")) return false;
  const expected = "sha256=" + (await hmacHex(secret, body));
  return timingSafeEqual(expected, sig);
}

async function validateStripe(request: Request, body: ArrayBuffer, secret: string): Promise<boolean> {
  const header = request.headers.get("stripe-signature");
  if (!header) return false;
  const parts = header.split(",").map((p) => p.split("="));
  const partMap = Object.fromEntries(parts);
  const timestamp = partMap.t;
  const v1sigs = header.split(",").filter((p) => p.startsWith("v1=")).map((p) => p.slice(3));
  if (!timestamp || !v1sigs.length) return false;
  if (Math.abs(Date.now() / 1000 - parseInt(timestamp)) > 300) return false;
  const payload = `${timestamp}.${new TextDecoder().decode(body)}`;
  const expected = await hmacHex(secret, payload);
  return v1sigs.some((sig) => timingSafeEqual(sig, expected));
}

async function validateLinear(request: Request, body: ArrayBuffer, secret: string): Promise<boolean> {
  const sig = request.headers.get("linear-signature");
  if (!sig) return false;
  const expected = await hmacHex(secret, body);
  return timingSafeEqual(expected, sig);
}

async function validateSlack(request: Request, body: ArrayBuffer, secret: string): Promise<boolean> {
  const timestamp = request.headers.get("x-slack-request-timestamp");
  const sig = request.headers.get("x-slack-signature");
  if (!timestamp || !sig?.startsWith("v0=")) return false;
  const base = `v0:${timestamp}:` + new TextDecoder().decode(body);
  const expected = "v0=" + (await hmacHex(secret, base));
  return timingSafeEqual(expected, sig);
}

async function validateMeltwater(request: Request, body: ArrayBuffer, secret: string): Promise<boolean> {
  const sig = request.headers.get("x-meltwater-signature");
  if (!sig) return false;
  const raw = sig.startsWith("sha256=") ? sig.slice(7) : sig;
  const expected = await hmacHex(secret, body);
  return timingSafeEqual(expected, raw);
}

async function validateGenericHmac(request: Request, body: ArrayBuffer, secret: string): Promise<boolean> {
  for (const header of ["x-webhook-secret", "x-signature", "x-hub-signature-256", "x-hub-signature"]) {
    const sig = request.headers.get(header);
    if (!sig) continue;
    const raw = sig.includes("=") ? sig.split("=").slice(1).join("=") : sig;
    const expected = await hmacHex(secret, body);
    return timingSafeEqual(expected, raw);
  }
  return false;
}

async function hmacHex(secret: string, data: ArrayBuffer | Uint8Array | string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const payload =
    typeof data === "string"
      ? new TextEncoder().encode(data)
      : data instanceof Uint8Array
        ? data
        : new Uint8Array(data);
  const sig = await crypto.subtle.sign("HMAC", key, payload as BufferSource);
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const encoder = new TextEncoder();
  const ab = encoder.encode(a.padEnd(b.length));
  const bb = encoder.encode(b.padEnd(a.length));
  if (ab.length !== bb.length) return false;
  let diff = 0;
  for (let i = 0; i < ab.length; i++) diff |= ab[i] ^ bb[i];
  return diff === 0 && a.length === b.length;
}

function buildForwardHeaders(
  request: Request,
  provider: string,
  requestId: string,
  config: ProviderConfig
): Headers {
  const headers = new Headers({
    "Content-Type": request.headers.get("content-type") || "application/json",
    "X-Webhook-Provider": provider,
    "X-Webhook-Request-Id": requestId,
    "X-Forwarded-For": request.headers.get("cf-connecting-ip") || "",
    "X-Forwarded-Host": request.headers.get("host") || "",
  });

  // Per-provider canonical headers (signature, event, delivery).
  const spec = PROVIDERS[provider];
  if (spec) {
    for (const h of Object.values(spec)) {
      if (!h) continue;
      const v = request.headers.get(h);
      if (v) headers.set(h, v);
    }
  }

  // Provider-configured extra passthrough headers.
  if (config.passthrough) {
    for (const h of config.passthrough) {
      const v = request.headers.get(h);
      if (v) headers.set(h, v);
    }
  }

  return headers;
}
