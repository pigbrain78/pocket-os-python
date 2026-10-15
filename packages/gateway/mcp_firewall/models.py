from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class ToolExecutionLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    MUTATING_REVERSIBLE = "MUTATING_REVERSIBLE"
    MUTATING_IRREVERSIBLE = "MUTATING_IRREVERSIBLE"


class CapabilityLease(BaseModel):
    lease_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    allowed_tool: str = Field(min_length=1)
    execution_level: ToolExecutionLevel
    resource_whitelist: list[str] = Field(default_factory=list)
    max_invocations: int = Field(default=1, ge=1)
    invocations_used: int = Field(default=0, ge=0)
    issued_at: datetime
    expires_at: datetime
    signature_ed25519: str = Field(min_length=1)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lease timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "CapabilityLease":
        if self.expires_at <= self.issued_at:
            raise ValueError("lease expiry must be later than issue time")
        return self

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(timezone.utc)) >= self.expires_at


class FirewallVerdict(str, Enum):
    SANCTIONED = "SANCTIONED"
    BLOCKED_EXPIRED_LEASE = "BLOCKED_EXPIRED_LEASE"
    BLOCKED_CONSTITUTIONAL_VIOLATION = "BLOCKED_CONSTITUTIONAL_VIOLATION"
    BLOCKED_AST_INJECTION = "BLOCKED_AST_INJECTION"
    BLOCKED_TOOL_UNMAPPED = "BLOCKED_TOOL_UNMAPPED"


class FirewallReceipt(BaseModel):
    receipt_id: str
    timestamp: int
    lease_id: str | None
    agent_id: str
    tool_name: str
    verdict: FirewallVerdict
    reason: str
    latency_ms: float
    mesh_digest: str
