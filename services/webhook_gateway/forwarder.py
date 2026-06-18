"""Forward normalized webhook events to Alerta and Mattermost.

The gateway emits to *both* destinations when configured:
- Alerta receives a normalized event via the source's `_normalize_*` method.
- Mattermost receives a human-readable message built from the same event.
- Meltwater payloads are additionally persisted to a dedicated ``meltwater_inbox``
  table so the Meltwater repo can pick them up asynchronously.
"""

import json
from dataclasses import dataclass

import httpx

# Map gateway source types to Alerta's supported source identifiers.
ALERTA_SOURCE_MAP = {
    "github": "github",
    "slack": "slack",
    "prometheus": "monitoring",
    "generic": "generic_webhook",
    "meltwater": "meltwater",
}


@dataclass
class ForwardResult:
    alerta_status: int | None
    alerta_body: str | None
    mattermost_status: int | None
    mattermost_body: str | None
    meltwater_persisted: bool

    @property
    def ok(self) -> bool:
        if self.alerta_status is not None and self.alerta_status >= 400:
            return False
        if self.mattermost_status is not None and self.mattermost_status >= 400:
            return False
        return True


class Forwarder:
    def __init__(
        self,
        alerta_url: str,
        alerta_token: str,
        mattermost_webhook_url: str = "",
        mattermost_channel: str = "",
    ):
        self.alerta_url = alerta_url.rstrip("/")
        self.alerta_token = alerta_token
        self.mattermost_webhook_url = mattermost_webhook_url
        self.mattermost_channel = mattermost_channel

    def normalize(self, source_type: str, headers: dict, payload: dict) -> dict:
        """Normalize a webhook payload into an Alerta-shaped event."""
        if source_type == "github":
            event = self._normalize_github(headers, payload)
        elif source_type == "prometheus":
            event = self._normalize_prometheus(payload)
        elif source_type == "slack":
            event = self._normalize_slack(payload)
        elif source_type == "meltwater":
            event = self._normalize_meltwater(payload)
        else:
            event = self._normalize_generic(payload)
        event["source"] = ALERTA_SOURCE_MAP.get(
            event.get("source", ""), "generic_webhook"
        )
        return event

    async def forward(
        self,
        source_type: str,
        headers: dict,
        payload: dict,
        db=None,
    ) -> ForwardResult:
        """Dispatch a webhook to its destinations.

        Alerta is always attempted when ``alerta_token`` is set.
        Mattermost is attempted when ``mattermost_webhook_url`` is set.
        Meltwater payloads are persisted to the inbox table when ``db`` is
        provided (and a separate flag is set when the destination is enabled).
        """
        event = self.normalize(source_type, headers, payload)
        alerta_status, alerta_body = await self._forward_alerta(event)
        mattermost_status, mattermost_body = None, None
        if self.mattermost_webhook_url:
            message = self._build_mattermost_message(source_type, event, payload)
            mattermost_status, mattermost_body = await self._forward_mattermost(message)
        meltwater_persisted = False
        if source_type == "meltwater" and db is not None:
            meltwater_persisted = await db.persist_meltwater_inbox(headers, payload)
        return ForwardResult(
            alerta_status=alerta_status,
            alerta_body=alerta_body,
            mattermost_status=mattermost_status,
            mattermost_body=mattermost_body,
            meltwater_persisted=meltwater_persisted,
        )

    # ── Alerta ───────────────────────────────────────────

    async def _forward_alerta(self, event: dict) -> tuple[int | None, str | None]:
        if not self.alerta_token:
            return None, None
        headers = {
            "Authorization": f"Bearer {self.alerta_token}",
            "Content-Type": "application/json",
        }
        url = f"{self.alerta_url}/api/events"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=event, headers=headers)
                if (
                    resp.status_code in (301, 302, 307, 308)
                    and "location" in resp.headers
                ):
                    resp = await client.post(
                        resp.headers["location"],
                        json=event,
                        headers=headers,
                    )
                return resp.status_code, resp.text
        except Exception as e:
            return 502, str(e)

    # ── Mattermost ───────────────────────────────────────

    async def _forward_mattermost(self, message: dict) -> tuple[int | None, str | None]:
        if self.mattermost_channel:
            message.setdefault("channel", self.mattermost_channel)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.mattermost_webhook_url, json=message)
                return resp.status_code, resp.text
        except Exception as e:
            return 502, str(e)

    def _build_mattermost_message(
        self,
        source_type: str,
        event: dict,
        payload: dict,
    ) -> dict:
        title = event.get("title", "Webhook event")
        body = event.get("body", "")
        severity = event.get("severity", "info")
        icon = {
            "critical": ":rotating_light:",
            "warning": ":warning:",
            "info": ":information_source:",
        }.get(severity, ":information_source:")
        text = f"{icon} **{title}**\n{body}\n\n_Source: {source_type} • Severity: {severity}_"
        return {"text": text}

    # ── Source normalizers ───────────────────────────────

    def _normalize_github(self, headers: dict, payload: dict) -> dict:
        event_type = headers.get("x-github-event", "unknown")
        repo = payload.get("repository", {}).get("full_name", "unknown")
        if event_type == "push":
            pusher = payload.get("pusher", {}).get("name", "unknown")
            msg = payload.get("head_commit", {}).get("message", "")
            return {
                "title": f"Push to {repo}",
                "body": f"{pusher} pushed: {msg}",
                "severity": "info",
                "source": "github",
                "tags": ["github", "push", repo],
            }
        if event_type == "issues":
            action = payload.get("action", "")
            issue = payload.get("issue", {})
            return {
                "title": f"Issue {action}: {issue.get('title', '')} #{issue.get('number', '')}",
                "body": issue.get("html_url", ""),
                "severity": "warning",
                "source": "github",
                "tags": ["github", "issue", repo],
            }
        if event_type == "pull_request":
            action = payload.get("action", "")
            pr = payload.get("pull_request", {})
            return {
                "title": f"PR {action}: {pr.get('title', '')} #{pr.get('number', '')}",
                "body": pr.get("html_url", ""),
                "severity": "info",
                "source": "github",
                "tags": ["github", "pr", repo],
            }
        if event_type == "workflow_run":
            wf = payload.get("workflow_run", {})
            conclusion = wf.get("conclusion", "unknown")
            severity = "critical" if conclusion == "failure" else "info"
            return {
                "title": f"Workflow {wf.get('name', '')}: {conclusion}",
                "body": wf.get("html_url", ""),
                "severity": severity,
                "source": "github",
                "tags": ["github", "ci", repo],
            }
        return {
            "title": f"GitHub {event_type} on {repo}",
            "body": str(payload.get("action", "")),
            "severity": "info",
            "source": "github",
            "tags": ["github", event_type, repo],
        }

    def _normalize_prometheus(self, payload: dict) -> dict:
        alerts = payload.get("alerts", [])
        if not alerts:
            return {
                "title": "Prometheus alert (empty)",
                "body": "",
                "severity": "info",
                "source": "prometheus",
                "tags": ["prometheus"],
            }
        alert = alerts[0]
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        return {
            "title": f"Alert: {labels.get('alertname', 'unknown')}",
            "body": annotations.get("summary", annotations.get("description", "")),
            "severity": "warning" if alert.get("status") == "firing" else "info",
            "source": "prometheus",
            "tags": [
                "prometheus",
                labels.get("alertname", ""),
                labels.get("instance", ""),
            ],
        }

    def _normalize_slack(self, payload: dict) -> dict:
        text = (
            payload.get("text") or payload.get("message") or json.dumps(payload)[:200]
        )
        return {
            "title": "Slack event",
            "body": text,
            "severity": "info",
            "source": "slack",
            "tags": ["slack"],
        }

    def _normalize_meltwater(self, payload: dict) -> dict:
        # Meltwater doesn't map naturally to an alerting event — we forward
        # the raw payload to the inbox and emit a low-severity Alerta event
        # for visibility. The real processing happens in the meltwater repo.
        count = payload.get("count") or (
            len(payload.get("documents", []))
            if isinstance(payload.get("documents"), list)
            else 0
        )
        return {
            "title": f"Meltwater mention batch ({count} hits)",
            "body": json.dumps(payload)[:512],
            "severity": "info",
            "source": "meltwater",
            "tags": ["meltwater"],
        }

    def _normalize_generic(self, payload: dict) -> dict:
        return {
            "title": payload.get("title", "Webhook event"),
            "body": payload.get("body", ""),
            "severity": payload.get("severity", "info"),
            "source": payload.get("source", "generic"),
            "tags": payload.get("tags", ["generic"]),
        }


# Backward-compat alias so existing imports keep working.
AlertaForwarder = Forwarder
