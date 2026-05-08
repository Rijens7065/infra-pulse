"""Tests for the agent's Pydantic models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent.models import AgentAction, AnomalySignal, RemediationPlan, TerraformChange


def test_anomaly_signal_round_trip():
    raw = {
        "anomaly_score": 0.85,
        "failure_mode": "OOM_LEAK",
        "confidence": 0.92,
        "time_to_impact_minutes": 30,
        "affected_metrics": ["memory_rss_bytes"],
        "explanation": "Memory grows linearly.",
    }
    sig = AnomalySignal.model_validate(raw)
    assert sig.failure_mode == "OOM_LEAK"
    assert sig.affected_metrics == ["memory_rss_bytes"]


def test_anomaly_signal_rejects_unknown_failure_mode():
    with pytest.raises(ValidationError):
        AnomalySignal.model_validate(
            {
                "anomaly_score": 0.5,
                "failure_mode": "BOGUS_MODE",
                "confidence": 0.9,
                "explanation": "x",
            }
        )


def test_remediation_plan_validates_confidence_bounds():
    with pytest.raises(ValidationError):
        RemediationPlan.model_validate(
            {
                "anomaly": {},
                "root_cause_summary": "x",
                "confidence": 1.5,
                "rollback_instructions": "y",
            }
        )


def test_remediation_plan_serialises_changes():
    change = TerraformChange(
        file_path="infra/modules/aks/main.tf",
        original_content="old",
        new_content="new",
        explanation="bump replicas",
    )
    plan = RemediationPlan(
        anomaly={"failure_mode": "OOM_LEAK"},
        root_cause_summary="leak",
        confidence=0.9,
        terraform_changes=[change],
        reasoning_chain=["read file", "diff"],
        rollback_instructions="git revert",
    )
    payload = json.loads(plan.model_dump_json())
    assert payload["terraform_changes"][0]["file_path"] == "infra/modules/aks/main.tf"
    assert payload["confidence"] == 0.9


def test_agent_action_jsonl_record_endswith_newline():
    a = AgentAction(
        anomaly_score=0.4,
        failure_mode="NORMAL",
        confidence=0.99,
        action_taken="skipped_normal",
    )
    record = a.to_jsonl_record()
    assert record.endswith("\n")
    parsed = json.loads(record)
    assert parsed["action_taken"] == "skipped_normal"
    assert parsed["pr_url"] is None
