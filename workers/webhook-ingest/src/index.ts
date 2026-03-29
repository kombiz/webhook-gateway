interface Env {
  WEBHOOK_GATEWAY_URL: string;
  GATEWAY_TOKEN: string;
  GITHUB_WEBHOOK_SECRET?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // Health check
    if (path === "/health") {
      return Response.json({ status: "ok", service: "webhook-ingest-worker" });
    }

    // Only accept POST for webhooks
    if (request.method !== "POST") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    // Route to appropriate source
    let source: string;
    if (path === "/github" || path === "/webhook/github") {
      source = "github";
    } else if (path === "/slack" || path === "/webhook/slack") {
      source = "slack";
    } else if (path === "/monitoring" || path === "/webhook/prometheus") {
      source = "prometheus";
    } else if (path === "/webhook" || path === "/webhook/generic") {
      source = "generic";
    } else {
      return Response.json({ error: "Unknown webhook path" }, { status: 404 });
    }

    // Read body
    const body = await request.text();

    // Forward headers that the gateway needs for validation
    const forwardHeaders: Record<string, string> = {
      "Content-Type": request.headers.get("Content-Type") || "application/json",
    };

    // Pass through GitHub signature header
    const ghSig = request.headers.get("X-Hub-Signature-256");
    if (ghSig) forwardHeaders["X-Hub-Signature-256"] = ghSig;

    const ghEvent = request.headers.get("X-GitHub-Event");
    if (ghEvent) forwardHeaders["X-GitHub-Event"] = ghEvent;

    const ghDelivery = request.headers.get("X-GitHub-Delivery");
    if (ghDelivery) forwardHeaders["X-GitHub-Delivery"] = ghDelivery;

    // Forward to gateway
    const gatewayUrl = `${env.WEBHOOK_GATEWAY_URL}/webhook/${source}`;

    try {
      const resp = await fetch(gatewayUrl, {
        method: "POST",
        headers: forwardHeaders,
        body,
      });

      const respBody = await resp.text();
      return new Response(respBody, {
        status: resp.status,
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return Response.json(
        { error: "Failed to forward to gateway", detail: String(err) },
        { status: 502 }
      );
    }
  },
};
