"""Pydantic models for webhook gateway."""
from enum import StrEnum
from pydantic import BaseModel

class SourceType(StrEnum):
    GITHUB = "github"
    SLACK = "slack"
    PROMETHEUS = "prometheus"
    GENERIC = "generic"

class EndpointCreate(BaseModel):
    name: str
    source_type: SourceType
    secret: str | None = None
    forward_url: str = "http://localhost:4000/api/events"
    enabled: bool = True

class EndpointUpdate(BaseModel):
    name: str | None = None
    secret: str | None = None
    forward_url: str | None = None
    enabled: bool | None = None

class EndpointResponse(BaseModel):
    id: str
    name: str
    source_type: SourceType | str
    secret: str | None = None
    forward_url: str
    enabled: bool
    created_at: str
    updated_at: str

class WebhookLogEntry(BaseModel):
    id: str
    endpoint_id: str | None = None
    source_type: str
    received_at: str
    headers: dict | None = None
    payload: dict | None = None
    forward_status: int | None = None
    forward_response: str | None = None
    processing_ms: int | None = None
