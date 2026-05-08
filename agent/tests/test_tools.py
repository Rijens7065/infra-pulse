"""Tests for the agent's tool implementations — all external calls mocked."""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List
from unittest.mock import MagicMock

import httpx
import pytest

from agent.constants import PR_LABELS_BASE
from agent.tools import (
    ALL_TOOLS,
    ToolContext,
    _format_pr_body,
    _validate_plan,
    dispatch_tool,
    run_create_remediation_pr,
    run_get_current_anomaly_signal,
    run_get_recent_infra_changes,
    run_log_audit_event,
    run_read_terraform_file,
)
from agent.models import RemediationPlan, TerraformChange


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_github_auth():
    auth = MagicMock()
    auth.headers.return_value = {"Authorization": "token stub"}
    return auth


@pytest.fixture
def http_transport_recorder():
    """Returns (handler, calls) — push httpx.Response objects from `responses` queue."""
    calls: List[Dict[str, Any]] = []
    responses: List[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "content": request.content.decode("utf-8") if request.content else "",
            }
        )
        if not responses:
            return httpx.Response(500, json={"error": "no canned response"})
        return responses.pop(0)

    return handler, calls, responses


@pytest.fixture
def make_ctx(stub_github_auth, http_transport_recorder):
    handler, calls, responses = http_transport_recorder
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    def factory(**overrides) -> ToolContext:
        defaults = dict(
            ml_service_url="http://ml-service:8000",
            github_owner="cloudsentro",
            github_repo="infra-pulse",
            github_default_branch="main",
            github_auth=stub_github_auth,
            azure_monitor_query=None,
            aks_resource_id="",
            k8s_core_v1=None,
            blob_container_client=None,
            http_client=client,
        )
        defaults.update(overrides)
        return ToolContext(**defaults)

    return factory, calls, responses


# ─────────────────────────────────────────────────────────────────────────
# Schema sanity
# ─────────────────────────────────────────────────────────────────────────


def test_seven_tools_exposed():
    assert len(ALL_TOOLS) == 7
    names = {t["name"] for t in ALL_TOOLS}
    assert names == {
        "get_current_anomaly_signal",
        "get_azure_monitor_metrics",
        "get_recent_infra_changes",
        "get_kubernetes_events",
        "read_terraform_file",
        "create_remediation_pr",
        "log_audit_event",
    }


def test_dispatch_unknown_tool_returns_error():
    ctx = MagicMock()
    result = dispatch_tool("not_a_real_tool", {}, ctx)
    assert "error" in result


# ─────────────────────────────────────────────────────────────────────────
# get_current_anomaly_signal
# ─────────────────────────────────────────────────────────────────────────


def test_get_current_anomaly_signal_calls_ml_service(make_ctx):
    factory, calls, responses = make_ctx
    ctx = factory()
    responses.append(
        httpx.Response(
            200,
            json={
                "anomaly_score": 0.8,
                "failure_mode": "OOM_LEAK",
                "confidence": 0.9,
                "time_to_impact_minutes": 30,
                "affected_metrics": ["memory_rss_bytes"],
                "explanation": "x",
            },
        )
    )

    result = run_get_current_anomaly_signal(ctx, {})
    assert result["failure_mode"] == "OOM_LEAK"
    assert calls[0]["url"] == "http://ml-service:8000/predict"


# ─────────────────────────────────────────────────────────────────────────
# get_recent_infra_changes
# ─────────────────────────────────────────────────────────────────────────


def test_get_recent_infra_changes_returns_normalised_commits(make_ctx):
    factory, calls, responses = make_ctx
    ctx = factory()
    responses.append(
        httpx.Response(
            200,
            json=[
                {
                    "sha": "abc123",
                    "commit": {
                        "message": "fix aks",
                        "author": {"name": "rijens", "date": "2026-05-01T00:00:00Z"},
                    },
                    "html_url": "https://github.com/cloudsentro/infra-pulse/commit/abc123",
                }
            ],
        )
    )

    result = run_get_recent_infra_changes(ctx, {})
    assert len(result["commits"]) == 1
    commit = result["commits"][0]
    assert commit["sha"] == "abc123"
    assert "path=infra" in calls[0]["url"]


# ─────────────────────────────────────────────────────────────────────────
# read_terraform_file
# ─────────────────────────────────────────────────────────────────────────


def test_read_terraform_file_decodes_base64(make_ctx):
    factory, calls, responses = make_ctx
    ctx = factory()
    content = "resource \"azurerm_kubernetes_cluster\" \"main\" {\n}"
    responses.append(
        httpx.Response(
            200,
            json={
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "sha": "deadbeef",
            },
        )
    )

    result = run_read_terraform_file(ctx, {"file_path": "infra/modules/aks/main.tf"})
    assert result["content"] == content
    assert result["sha"] == "deadbeef"


def test_read_terraform_file_rejects_non_infra_path(make_ctx):
    factory, _calls, _responses = make_ctx
    ctx = factory()
    result = run_read_terraform_file(ctx, {"file_path": "agent/agent.py"})
    assert "error" in result


def test_read_terraform_file_handles_404(make_ctx):
    factory, _calls, responses = make_ctx
    ctx = factory()
    responses.append(httpx.Response(404, json={"message": "Not Found"}))
    result = run_read_terraform_file(ctx, {"file_path": "infra/missing.tf"})
    assert result["error"] == "file not found"


# ─────────────────────────────────────────────────────────────────────────
# _validate_plan and PR body formatting
# ─────────────────────────────────────────────────────────────────────────


def _sample_plan(failure_mode: str = "OOM_LEAK", file_path: str = "infra/modules/aks/main.tf"):
    return RemediationPlan(
        anomaly={
            "failure_mode": failure_mode,
            "anomaly_score": 0.9,
            "confidence": 0.85,
            "explanation": "x",
        },
        root_cause_summary="memory leak in node pool",
        confidence=0.85,
        terraform_changes=[
            TerraformChange(
                file_path=file_path,
                original_content="old",
                new_content="new",
                explanation="raise memory limit",
            )
        ],
        reasoning_chain=["a", "b", "c"],
        rollback_instructions="git revert HEAD",
    )


def test_validate_plan_blocks_security_drift():
    plan = _sample_plan(failure_mode="SECURITY_DRIFT")
    assert _validate_plan(plan) is not None


def test_validate_plan_blocks_budget_module():
    plan = _sample_plan(file_path="infra/modules/budget/main.tf")
    assert _validate_plan(plan) is not None


def test_validate_plan_blocks_identity_module():
    plan = _sample_plan(file_path="infra/modules/identity/main.tf")
    assert _validate_plan(plan) is not None


def test_validate_plan_blocks_path_outside_infra():
    plan = _sample_plan(file_path="agent/agent.py")
    assert _validate_plan(plan) is not None


def test_validate_plan_accepts_clean_plan():
    plan = _sample_plan()
    assert _validate_plan(plan) is None


def test_pr_body_renders_all_required_sections():
    plan = _sample_plan()
    body = _format_pr_body(plan)
    for section in [
        "## Anomaly Report",
        "## Root Cause",
        "## Reasoning Chain",
        "## Proposed Changes",
        "## Rollback Instructions",
    ]:
        assert section in body
    assert "<details>" in body
    assert "OOM_LEAK" in body


# ─────────────────────────────────────────────────────────────────────────
# create_remediation_pr — happy path with a fully mocked GitHub API
# ─────────────────────────────────────────────────────────────────────────


def test_create_remediation_pr_opens_pr_with_labels(make_ctx):
    factory, calls, responses = make_ctx
    ctx = factory()
    plan_dict = json.loads(_sample_plan().model_dump_json())

    # 1. GET base ref
    responses.append(httpx.Response(200, json={"object": {"sha": "base-sha"}}))
    # 2. POST create branch
    responses.append(httpx.Response(201, json={"ref": "refs/heads/fix/agent-x-oom_leak"}))
    # 3. GET existing file on branch (not present yet)
    responses.append(httpx.Response(404, json={"message": "Not Found"}))
    # 4. PUT contents
    responses.append(httpx.Response(201, json={"content": {"sha": "new-sha"}}))
    # 5. POST pull request
    responses.append(
        httpx.Response(
            201,
            json={
                "number": 42,
                "html_url": "https://github.com/cloudsentro/infra-pulse/pull/42",
            },
        )
    )
    # 6. POST labels
    responses.append(httpx.Response(200, json=[{"name": "agent-remediation"}]))

    result = run_create_remediation_pr(ctx, {"remediation_plan": plan_dict})
    assert result["pr_url"].endswith("/pull/42")
    assert "oom_leak" in result["labels"]
    for required in PR_LABELS_BASE:
        assert required in result["labels"]


def test_create_remediation_pr_rejects_security_drift(make_ctx):
    factory, _calls, _responses = make_ctx
    ctx = factory()
    plan_dict = json.loads(_sample_plan(failure_mode="SECURITY_DRIFT").model_dump_json())
    result = run_create_remediation_pr(ctx, {"remediation_plan": plan_dict})
    assert "error" in result


def test_create_remediation_pr_rejects_empty_changes(make_ctx):
    factory, _calls, _responses = make_ctx
    ctx = factory()
    plan = _sample_plan()
    plan.terraform_changes = []
    result = run_create_remediation_pr(ctx, {"remediation_plan": json.loads(plan.model_dump_json())})
    assert "error" in result


# ─────────────────────────────────────────────────────────────────────────
# log_audit_event — without a blob client it logs locally
# ─────────────────────────────────────────────────────────────────────────


def test_log_audit_event_without_blob_client(make_ctx):
    factory, _calls, _responses = make_ctx
    ctx = factory()
    result = run_log_audit_event(
        ctx,
        {
            "anomaly_score": 0.8,
            "failure_mode": "OOM_LEAK",
            "confidence": 0.9,
            "action_taken": "pr_opened",
            "pr_url": "https://github.com/x/y/pull/1",
        },
    )
    assert result["logged"] is True
    assert "warning" in result
