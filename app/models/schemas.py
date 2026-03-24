from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Request / Response ───────────────────────────────────────────────


class ProcessMessageRequest(BaseModel):
    org_id: str
    conversation_id: str
    contact_phone: str
    contact_name: str = ""
    message: str
    inbox_source: str = "whatsapp"


class ProcessMessageResponse(BaseModel):
    action: str  # continue | handoff | schedule | update_crm | blocked | ignored
    message_sent: Optional[str] = None
    skill_used: Optional[str] = None
    agent_type: Optional[str] = None
    error: Optional[str] = None


# ── Health ───────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    org_id: str
    agents_active: list[str] = []
    redis: str = "unknown"
    chroma: str = "unknown"


# ── Agent JSON output ───────────────────────────────────────────────


class CrmUpdates(BaseModel):
    stage: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ScheduleInfo(BaseModel):
    requested_date: Optional[str] = None
    requested_time: Optional[str] = None
    attendee_name: Optional[str] = None
    attendee_email: Optional[str] = None
    participant: Optional[str] = None
    whatsapp_for_reminders: Optional[str] = None
    interest: Optional[str] = None


class AgentOutput(BaseModel):
    text: str
    action: str = "continue"  # continue | handoff | schedule | update_crm
    skill_used: str = "qualify"
    lead_temperature: str = "cold"  # cold | warm | hot
    summary: Optional[str] = None
    crm_updates: Optional[CrmUpdates] = None
    schedule: Optional[ScheduleInfo] = None


# ── Knowledge ────────────────────────────────────────────────────────


class KnowledgeUploadResponse(BaseModel):
    status: str
    chunks: int
    document_name: str


class KnowledgeSearchResult(BaseModel):
    text: str
    score: float
    metadata: dict = Field(default_factory=dict)


# ── Agents status ────────────────────────────────────────────────────


class AgentStatusItem(BaseModel):
    type: str
    name: str
    is_active: bool
    messages_today: int = 0
    handoffs_today: int = 0


class AgentsStatusResponse(BaseModel):
    agents: list[AgentStatusItem]


# ── Logs / Metrics ───────────────────────────────────────────────────


class LogEntry(BaseModel):
    id: str
    conversation_id: str
    contact_phone: Optional[str] = None
    contact_name: Optional[str] = None
    agent_type: str
    message_role: str
    message_text: str
    skill_used: Optional[str] = None
    action_taken: Optional[str] = None
    validation_result: Optional[str] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None
    response_time_ms: Optional[int] = None
    created_at: str


class LogsResponse(BaseModel):
    logs: list[LogEntry]
    total: int
    page: int


class MetricsResponse(BaseModel):
    messages_processed: int
    handoffs: int
    blocked: int
    avg_response_time_ms: float
    cost_estimate_usd: float
