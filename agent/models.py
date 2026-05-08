"""Pydantic models for the CloudSentro agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

FailureMode = Literal[
    "NORMAL",
    "OOM_LEAK",
    "CPU_THROTTLE",
    "NETWORK_DEGRADATION",
    "COST_SPIKE",
    "SECURITY_DRIFT",
]


class AnomalySignal(BaseModel):
    """Mirror of ml/ AnomalySignal contract — never change field names."""

    anomaly_score: float
    failure_mode: FailureMode
    confidence: float
    time_to_impact_minutes: Optional[int] = None
    affected_metrics: List[str] = Field(default_factory=list)
    explanation: str


class TerraformChange(BaseModel):
    file_path: str
    original_content: str
    new_content: str
    explanation: str


class RemediationPlan(BaseModel):
    anomaly: dict
    root_cause_summary: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    terraform_changes: List[TerraformChange] = Field(default_factory=list)
    reasoning_chain: List[str] = Field(default_factory=list)
    rollback_instructions: str


class AgentAction(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    anomaly_score: float
    failure_mode: FailureMode
    confidence: float
    action_taken: Literal["pr_opened", "logged_only", "skipped_normal", "skipped_low_confidence"]
    pr_url: Optional[str] = None
    notes: Optional[str] = None

    def to_jsonl_record(self) -> str:
        return self.model_dump_json() + "\n"
