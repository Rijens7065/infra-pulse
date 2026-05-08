"""Tests for the system prompt — guards against accidental rule weakening."""

from __future__ import annotations

from agent.constants import CONFIDENCE_THRESHOLD
from agent.prompts import SYSTEM_PROMPT


def test_system_prompt_mentions_threshold():
    assert f"{CONFIDENCE_THRESHOLD}" in SYSTEM_PROMPT


def test_system_prompt_blocks_security_drift_pr():
    text = SYSTEM_PROMPT.lower()
    assert "security_drift" in text
    assert "log only" in text or "never open a pr" in text


def test_system_prompt_forbids_rbac_and_budget():
    text = SYSTEM_PROMPT.lower()
    assert "rbac" in text or "iam" in text
    assert "budget" in text


def test_system_prompt_requires_anomaly_signal_first():
    text = SYSTEM_PROMPT.lower()
    assert "get_current_anomaly_signal" in text


def test_system_prompt_requires_audit_log():
    assert "log_audit_event" in SYSTEM_PROMPT
