"""Forward normalized webhook events to Alerta."""
import httpx

# Map gateway source types to Alerta's supported sources
ALERTA_SOURCE_MAP = {
    "github": "github",
    "slack": "slack",
    "prometheus": "monitoring",
    "generic": "generic_webhook",
}


class AlertaForwarder:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def normalize(self, source_type: str, headers: dict, payload: dict) -> dict:
        """Normalize a webhook payload into an Alerta event."""
        if source_type == "github":
            event = self._normalize_github(headers, payload)
        elif source_type == "prometheus":
            event = self._normalize_prometheus(payload)
        else:
            event = self._normalize_generic(payload)
        # Map source to Alerta's supported sources
        event["source"] = ALERTA_SOURCE_MAP.get(event.get("source", ""), "generic_webhook")
        return event

    async def forward(self, event: dict) -> tuple[int, str]:
        """POST event to Alerta. Returns (status_code, response_text).

        Handles redirects manually to preserve Authorization header,
        which httpx strips on redirect per HTTP spec.
        """
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/api/events"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=event, headers=headers)
            # Follow one redirect if needed, re-attaching auth
            if resp.status_code in (301, 302, 307, 308) and "location" in resp.headers:
                resp = await client.post(
                    resp.headers["location"], json=event, headers=headers,
                )
            return resp.status_code, resp.text

    def _normalize_github(self, headers: dict, payload: dict) -> dict:
        event_type = headers.get("x-github-event", "unknown")
        repo = payload.get("repository", {}).get("full_name", "unknown")
        if event_type == "push":
            pusher = payload.get("pusher", {}).get("name", "unknown")
            msg = payload.get("head_commit", {}).get("message", "")
            return {"title": f"Push to {repo}", "body": f"{pusher} pushed: {msg}",
                    "severity": "info", "source": "github", "tags": ["github", "push", repo]}
        if event_type == "issues":
            action = payload.get("action", "")
            issue = payload.get("issue", {})
            return {"title": f"Issue {action}: {issue.get('title', '')} #{issue.get('number', '')}",
                    "body": issue.get("html_url", ""), "severity": "warning",
                    "source": "github", "tags": ["github", "issue", repo]}
        if event_type == "pull_request":
            action = payload.get("action", "")
            pr = payload.get("pull_request", {})
            return {"title": f"PR {action}: {pr.get('title', '')} #{pr.get('number', '')}",
                    "body": pr.get("html_url", ""), "severity": "info",
                    "source": "github", "tags": ["github", "pr", repo]}
        if event_type == "workflow_run":
            wf = payload.get("workflow_run", {})
            conclusion = wf.get("conclusion", "unknown")
            severity = "critical" if conclusion == "failure" else "info"
            return {"title": f"Workflow {wf.get('name', '')}: {conclusion}",
                    "body": wf.get("html_url", ""), "severity": severity,
                    "source": "github", "tags": ["github", "ci", repo]}
        return {"title": f"GitHub {event_type} on {repo}",
                "body": str(payload.get("action", "")), "severity": "info",
                "source": "github", "tags": ["github", event_type, repo]}

    def _normalize_prometheus(self, payload: dict) -> dict:
        alerts = payload.get("alerts", [])
        if not alerts:
            return {"title": "Prometheus alert (empty)", "body": "",
                    "severity": "info", "source": "prometheus", "tags": ["prometheus"]}
        alert = alerts[0]
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        return {"title": f"Alert: {labels.get('alertname', 'unknown')}",
                "body": annotations.get("summary", annotations.get("description", "")),
                "severity": "warning" if alert.get("status") == "firing" else "info",
                "source": "prometheus",
                "tags": ["prometheus", labels.get("alertname", ""), labels.get("instance", "")]}

    def _normalize_generic(self, payload: dict) -> dict:
        return {"title": payload.get("title", "Webhook event"),
                "body": payload.get("body", ""),
                "severity": payload.get("severity", "info"),
                "source": payload.get("source", "generic"),
                "tags": payload.get("tags", ["generic"])}
