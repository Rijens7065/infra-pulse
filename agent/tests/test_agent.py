"""Tests for the run_once reasoning loop — Claude client mocked end-to-end."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from agent.agent import run_once
from agent.tools import ToolContext


def _block_tool_use(tool_id: str, name: str, input_dict: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input_dict)


def _block_text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _claude_response(content: list, stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason)


@pytest.fixture
def stub_ctx():
    """Build a ToolContext that lets get_current_anomaly_signal return a fixed payload."""
    sig = {
        "anomaly_score": 0.2,
        "failure_mode": "NORMAL",
        "confidence": 0.99,
        "time_to_impact_minutes": None,
        "affected_metrics": [],
        "explanation": "all good",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/predict":
            return httpx.Response(200, json=sig)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    return ToolContext(
        ml_service_url="http://ml-service:8000",
        github_owner="cloudsentro",
        github_repo="infra-pulse",
        github_default_branch="main",
        github_auth=MagicMock(headers=MagicMock(return_value={})),
        azure_monitor_query=None,
        aks_resource_id="",
        k8s_core_v1=None,
        blob_container_client=None,
        http_client=httpx.Client(transport=transport),
    )


def test_run_once_normal_path_logs_skipped_normal(stub_ctx):
    """Claude returns: tool_use(get_current_anomaly_signal) → tool_use(log_audit_event) → end."""
    claude = MagicMock()
    claude.messages.create.side_effect = [
        _claude_response([
            _block_tool_use("t1", "get_current_anomaly_signal", {}),
        ]),
        _claude_response([
            _block_tool_use(
                "t2",
                "log_audit_event",
                {
                    "anomaly_score": 0.2,
                    "failure_mode": "NORMAL",
                    "confidence": 0.99,
                    "action_taken": "skipped_normal",
                },
            ),
        ]),
        _claude_response([_block_text("Done.")], stop_reason="end_turn"),
    ]

    action = run_once(claude, stub_ctx)
    assert action.failure_mode == "NORMAL"
    assert action.action_taken == "skipped_normal"
    assert action.pr_url is None


def test_run_once_low_confidence_anomaly_logs_only(stub_ctx):
    """Anomaly with confidence below threshold should be logged as skipped_low_confidence."""
    sig = {
        "anomaly_score": 0.7,
        "failure_mode": "OOM_LEAK",
        "confidence": 0.5,  # below threshold
        "time_to_impact_minutes": 30,
        "affected_metrics": ["memory_rss_bytes"],
        "explanation": "x",
    }

    def handler(request):
        return httpx.Response(200, json=sig) if request.url.path == "/predict" else httpx.Response(404)

    stub_ctx.http_client = httpx.Client(transport=httpx.MockTransport(handler))

    claude = MagicMock()
    claude.messages.create.side_effect = [
        _claude_response([_block_tool_use("t1", "get_current_anomaly_signal", {})]),
        _claude_response([
            _block_tool_use(
                "t2",
                "log_audit_event",
                {
                    "anomaly_score": 0.7,
                    "failure_mode": "OOM_LEAK",
                    "confidence": 0.5,
                    "action_taken": "skipped_low_confidence",
                },
            ),
        ]),
        _claude_response([_block_text("Done.")], stop_reason="end_turn"),
    ]

    action = run_once(claude, stub_ctx)
    assert action.action_taken == "skipped_low_confidence"
    assert action.failure_mode == "OOM_LEAK"


def test_run_once_respects_max_turns(stub_ctx):
    """If Claude keeps using tools indefinitely, the loop must terminate at MAX_TOOL_TURNS."""
    from agent.constants import MAX_TOOL_TURNS

    claude = MagicMock()
    claude.messages.create.return_value = _claude_response([
        _block_tool_use("t", "get_current_anomaly_signal", {}),
    ])
    run_once(claude, stub_ctx)
    assert claude.messages.create.call_count == MAX_TOOL_TURNS
