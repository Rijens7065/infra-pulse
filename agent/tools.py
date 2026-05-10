"""Tool definitions and implementations for the agent's Claude tool_use loop.

The seven tools roughly fall into three groups:
  - read-only context gathering (anomaly, metrics, infra changes, k8s events, files)
  - the action (open a remediation PR)
  - the audit log (append every cycle's outcome to Azure Blob)

Each `*_TOOL` constant is the JSON-serialisable schema sent to Claude.
Each `run_*` function is the local implementation Claude's tool call routes to.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

from agent.actions.github_app_auth import GitHubAppAuth
from agent.constants import (
    AUDIT_CONTAINER,
    FORBIDDEN_FAILURE_MODES_FOR_PR,
    FORBIDDEN_TERRAFORM_PATHS,
    PR_LABELS_BASE,
)
from agent.models import RemediationPlan

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# ─────────────────────────────────────────────────────────────────────────
# Tool schemas (sent to Claude)
# ─────────────────────────────────────────────────────────────────────────

GET_CURRENT_ANOMALY_SIGNAL_TOOL = {
    "name": "get_current_anomaly_signal",
    "description": (
        "Fetch the most recent anomaly prediction from the ML service. "
        "Always call this first. Returns AnomalySignal JSON."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

GET_AZURE_MONITOR_METRICS_TOOL = {
    "name": "get_azure_monitor_metrics",
    "description": (
        "Read AKS metrics from Azure Monitor for a recent time window. "
        "Use this to confirm or refine what the ML model is seeing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Azure Monitor metric names (e.g. node_cpu_usage_percentage).",
            },
            "hours": {
                "type": "integer",
                "minimum": 1,
                "maximum": 24,
                "description": "How many hours back to query (max 24).",
            },
        },
        "required": ["metric_names", "hours"],
    },
}

GET_RECENT_INFRA_CHANGES_TOOL = {
    "name": "get_recent_infra_changes",
    "description": "Last 10 commits touching infra/ on the default branch.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

GET_KUBERNETES_EVENTS_TOOL = {
    "name": "get_kubernetes_events",
    "description": (
        "List recent Warning events in the cloudsentro namespace. Useful "
        "for OOMKills, image pull failures, throttling, CrashLoopBackOff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "minutes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 720,
                "description": "Time window in minutes (default 60).",
            }
        },
        "required": [],
    },
}

READ_TERRAFORM_FILE_TOOL = {
    "name": "read_terraform_file",
    "description": (
        "Read the current contents of a Terraform file from main. "
        "Always call this before proposing changes to a file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path within the repo, e.g. infra/modules/aks/main.tf",
            }
        },
        "required": ["file_path"],
    },
}

CREATE_REMEDIATION_PR_TOOL = {
    "name": "create_remediation_pr",
    "description": (
        "Open a GitHub pull request with the proposed Terraform fix. "
        "Only call this after reasoning is complete and confidence > 0.75. "
        "Never call for SECURITY_DRIFT."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "remediation_plan": {
                "type": "object",
                "description": "Full RemediationPlan JSON.",
            }
        },
        "required": ["remediation_plan"],
    },
}

LOG_AUDIT_EVENT_TOOL = {
    "name": "log_audit_event",
    "description": (
        "Append a structured audit record for this investigation cycle. "
        "Call exactly once at the end of every reasoning loop."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "anomaly_score": {"type": "number"},
            "failure_mode": {"type": "string"},
            "confidence": {"type": "number"},
            "action_taken": {
                "type": "string",
                "enum": ["pr_opened", "logged_only", "skipped_normal", "skipped_low_confidence"],
            },
            "pr_url": {"type": ["string", "null"]},
            "notes": {"type": ["string", "null"]},
        },
        "required": ["anomaly_score", "failure_mode", "confidence", "action_taken"],
    },
}

ALL_TOOLS = [
    GET_CURRENT_ANOMALY_SIGNAL_TOOL,
    GET_AZURE_MONITOR_METRICS_TOOL,
    GET_RECENT_INFRA_CHANGES_TOOL,
    GET_KUBERNETES_EVENTS_TOOL,
    READ_TERRAFORM_FILE_TOOL,
    CREATE_REMEDIATION_PR_TOOL,
    LOG_AUDIT_EVENT_TOOL,
]


# ─────────────────────────────────────────────────────────────────────────
# Runtime context the implementations close over
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class ToolContext:
    """Everything the tool implementations need to reach external systems."""

    ml_service_url: str
    github_owner: str
    github_repo: str
    github_default_branch: str
    github_auth: GitHubAppAuth
    azure_monitor_query: Any  # azure.monitor.query.MetricsQueryClient (optional in tests)
    aks_resource_id: str
    k8s_core_v1: Any  # kubernetes.client.CoreV1Api (optional in tests)
    blob_container_client: Any  # azure.storage.blob.ContainerClient (optional in tests)
    http_client: httpx.Client


# ─────────────────────────────────────────────────────────────────────────
# Implementations
# ─────────────────────────────────────────────────────────────────────────


def run_get_current_anomaly_signal(ctx: ToolContext, _args: Dict[str, Any]) -> Dict[str, Any]:
    # ML's /predict is a POST endpoint that scores a 60x7 metrics window.
    # In the deployed demo we don't yet have Azure Monitor wiring, so we
    # send a baseline window and let the ML pod's /inject override (if
    # active) shape the response.
    baseline_sample = [40.0, 2.5e8, 0.0, 100.0, 2.5e6, 2.0e6, 0.12]
    body = {"metrics": [baseline_sample] * 60}
    response = ctx.http_client.post(
        f"{ctx.ml_service_url}/predict", json=body, timeout=10.0
    )
    response.raise_for_status()
    return response.json()


def run_get_azure_monitor_metrics(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    metric_names: List[str] = args["metric_names"]
    hours: int = args["hours"]

    if ctx.azure_monitor_query is None:
        return {"metrics": [], "warning": "azure_monitor_query client not configured"}

    response = ctx.azure_monitor_query.query_resource(
        ctx.aks_resource_id,
        metric_names=metric_names,
        timespan=timedelta(hours=hours),
    )

    out: List[Dict[str, Any]] = []
    for metric in response.metrics:
        for ts in metric.timeseries:
            samples = [
                {
                    "timestamp": pt.timestamp.isoformat() if pt.timestamp else None,
                    "value": pt.average if pt.average is not None else pt.total,
                }
                for pt in ts.data
            ]
            out.append({"name": metric.name, "samples": samples})
    return {"metrics": out}


def run_get_recent_infra_changes(
    ctx: ToolContext, _args: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{GITHUB_API}/repos/{ctx.github_owner}/{ctx.github_repo}/commits"
    response = ctx.http_client.get(
        url,
        params={"path": "infra/", "per_page": 10, "sha": ctx.github_default_branch},
        headers=ctx.github_auth.headers(),
    )
    response.raise_for_status()
    commits = response.json()
    return {
        "commits": [
            {
                "sha": c["sha"],
                "message": c["commit"]["message"],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
                "url": c["html_url"],
            }
            for c in commits
        ]
    }


def run_get_kubernetes_events(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    minutes = int(args.get("minutes", 60))
    if ctx.k8s_core_v1 is None:
        return {"events": [], "warning": "kubernetes client not configured"}

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    response = ctx.k8s_core_v1.list_namespaced_event(
        namespace="cloudsentro",
        field_selector="type=Warning",
    )

    events = []
    for ev in getattr(response, "items", []):
        last = getattr(ev, "last_timestamp", None) or getattr(ev, "event_time", None)
        if last is not None and last < cutoff:
            continue
        events.append(
            {
                "timestamp": last.isoformat() if last else None,
                "reason": getattr(ev, "reason", None),
                "message": getattr(ev, "message", None),
                "involved_object": (
                    getattr(getattr(ev, "involved_object", None), "name", None)
                ),
            }
        )
    return {"events": events}


def run_read_terraform_file(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    file_path: str = args["file_path"]
    if not file_path.startswith("infra/"):
        return {"error": "file_path must be under infra/"}

    url = f"{GITHUB_API}/repos/{ctx.github_owner}/{ctx.github_repo}/contents/{file_path}"
    response = ctx.http_client.get(
        url,
        params={"ref": ctx.github_default_branch},
        headers=ctx.github_auth.headers(),
    )
    if response.status_code == 404:
        return {"error": "file not found", "file_path": file_path}
    response.raise_for_status()
    body = response.json()

    import base64

    content = base64.b64decode(body["content"]).decode("utf-8")
    return {"file_path": file_path, "content": content, "sha": body["sha"]}


# ─────────────────────────────────────────────────────────────────────────
# create_remediation_pr — write path with hard guards
# ─────────────────────────────────────────────────────────────────────────


def _branch_name(failure_mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"fix/agent-{stamp}-{failure_mode.lower()}"


def _format_pr_body(plan: RemediationPlan) -> str:
    anomaly = plan.anomaly or {}
    score = anomaly.get("anomaly_score", "n/a")
    mode = anomaly.get("failure_mode", "n/a")
    explanation = anomaly.get("explanation", "")

    reasoning_block = "\n".join(f"- {step}" for step in plan.reasoning_chain) or "- (none)"
    changes_block = "\n".join(
        f"### `{c.file_path}`\n\n{c.explanation}"
        for c in plan.terraform_changes
    ) or "_no file changes proposed_"

    return (
        "## Anomaly Report\n"
        f"- **Failure mode:** `{mode}`\n"
        f"- **Anomaly score:** `{score}`\n"
        f"- **Confidence:** `{plan.confidence:.2f}`\n"
        f"- **ML explanation:** {explanation}\n\n"
        "## Root Cause\n"
        f"{plan.root_cause_summary}\n\n"
        "## Reasoning Chain\n"
        "<details><summary>Step-by-step reasoning</summary>\n\n"
        f"{reasoning_block}\n\n"
        "</details>\n\n"
        "## Proposed Changes\n"
        f"{changes_block}\n\n"
        "## Rollback Instructions\n"
        f"{plan.rollback_instructions}\n\n"
        "---\n"
        "_Generated by CloudSentro Agent · "
        "[View Dashboard](https://infra-pulse.cloudsentro.com)_\n"
    )


def _validate_plan(plan: RemediationPlan) -> Optional[str]:
    """Returns an error message if the plan must not be acted on, else None."""
    mode = plan.anomaly.get("failure_mode") if isinstance(plan.anomaly, dict) else None
    if mode in FORBIDDEN_FAILURE_MODES_FOR_PR:
        return f"failure_mode {mode} must never produce a PR"
    for change in plan.terraform_changes:
        if not change.file_path.startswith("infra/"):
            return f"file_path outside infra/: {change.file_path}"
        for forbidden in FORBIDDEN_TERRAFORM_PATHS:
            if change.file_path.startswith(forbidden):
                return f"file_path inside forbidden module: {change.file_path}"
    return None


def run_create_remediation_pr(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    raw = args.get("remediation_plan")
    if not isinstance(raw, dict):
        return {"error": "remediation_plan must be an object"}

    try:
        plan = RemediationPlan.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"invalid remediation_plan: {exc}"}

    error = _validate_plan(plan)
    if error is not None:
        return {"error": error}
    if not plan.terraform_changes:
        return {"error": "no terraform_changes to apply"}

    failure_mode = plan.anomaly.get("failure_mode", "UNKNOWN")
    branch = _branch_name(failure_mode)
    headers = ctx.github_auth.headers()
    repo_url = f"{GITHUB_API}/repos/{ctx.github_owner}/{ctx.github_repo}"

    base_ref = ctx.http_client.get(
        f"{repo_url}/git/ref/heads/{ctx.github_default_branch}", headers=headers
    )
    base_ref.raise_for_status()
    base_sha = base_ref.json()["object"]["sha"]

    create_branch = ctx.http_client.post(
        f"{repo_url}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
    )
    create_branch.raise_for_status()

    import base64

    for change in plan.terraform_changes:
        existing = ctx.http_client.get(
            f"{repo_url}/contents/{change.file_path}",
            params={"ref": branch},
            headers=headers,
        )
        sha = existing.json().get("sha") if existing.status_code == 200 else None
        payload = {
            "message": f"agent: {failure_mode} fix — {change.file_path}",
            "content": base64.b64encode(change.new_content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha is not None:
            payload["sha"] = sha
        put = ctx.http_client.put(
            f"{repo_url}/contents/{change.file_path}", headers=headers, json=payload
        )
        put.raise_for_status()

    pr = ctx.http_client.post(
        f"{repo_url}/pulls",
        headers=headers,
        json={
            "title": f"agent: {failure_mode} remediation",
            "head": branch,
            "base": ctx.github_default_branch,
            "body": _format_pr_body(plan),
        },
    )
    pr.raise_for_status()
    pr_body = pr.json()
    pr_number = pr_body["number"]
    pr_url = pr_body["html_url"]

    labels = PR_LABELS_BASE + [failure_mode.lower()]
    ctx.http_client.post(
        f"{repo_url}/issues/{pr_number}/labels",
        headers=headers,
        json={"labels": labels},
    )

    return {"pr_url": pr_url, "branch": branch, "labels": labels}


def run_log_audit_event(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "anomaly_score": args["anomaly_score"],
        "failure_mode": args["failure_mode"],
        "confidence": args["confidence"],
        "action_taken": args["action_taken"],
        "pr_url": args.get("pr_url"),
        "notes": args.get("notes"),
    }
    blob_name = (
        f"audit/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    )

    if ctx.blob_container_client is None:
        logger.info("audit (no blob client): %s", record)
        return {"logged": True, "warning": "blob client not configured"}

    blob = ctx.blob_container_client.get_blob_client(blob_name)
    line = (json.dumps(record) + "\n").encode("utf-8")

    try:
        from azure.storage.blob import BlobType  # local import to keep tests light

        if not blob.exists():
            blob.create_append_blob()
        elif blob.get_blob_properties().blob_type != BlobType.APPENDBLOB:
            raise RuntimeError(f"blob {blob_name} exists but is not an append blob")
        blob.append_block(line)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to append audit record: %s", exc)
        return {"logged": False, "error": str(exc)}

    return {"logged": True, "container": AUDIT_CONTAINER, "blob": blob_name}


TOOL_DISPATCH: Dict[str, Callable[[ToolContext, Dict[str, Any]], Dict[str, Any]]] = {
    "get_current_anomaly_signal": run_get_current_anomaly_signal,
    "get_azure_monitor_metrics": run_get_azure_monitor_metrics,
    "get_recent_infra_changes": run_get_recent_infra_changes,
    "get_kubernetes_events": run_get_kubernetes_events,
    "read_terraform_file": run_read_terraform_file,
    "create_remediation_pr": run_create_remediation_pr,
    "log_audit_event": run_log_audit_event,
}


def dispatch_tool(
    name: str, args: Dict[str, Any], ctx: ToolContext
) -> Dict[str, Any]:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return fn(ctx, args)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool %s raised", name)
        return {"error": f"{type(exc).__name__}: {exc}"}
