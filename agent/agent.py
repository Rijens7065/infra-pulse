"""CloudSentro agent — Claude tool_use reasoning loop.

`run_once()` invokes Claude with the seven tools, walks up to MAX_TOOL_TURNS,
and returns the final `AgentAction`. `run_loop()` runs `run_once()` every
POLL_INTERVAL_SECONDS with exponential backoff on failure. The FastAPI
`/health` endpoint exposes liveness state for k8s probes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI

from agent.constants import (
    CLAUDE_MODEL,
    CONFIDENCE_THRESHOLD,
    INITIAL_BACKOFF_SECONDS,
    KEY_VAULT_SECRET_CLAUDE,
    KEY_VAULT_SECRET_GITHUB,
    MAX_BACKOFF_SECONDS,
    MAX_TOOL_TURNS,
    POLL_INTERVAL_SECONDS,
)
from agent.models import AgentAction
from agent.prompts import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE
from agent.tools import ALL_TOOLS, ToolContext, dispatch_tool

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Runtime state
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class AgentState:
    started_at: float = field(default_factory=time.time)
    last_run_at: Optional[float] = None
    last_anomaly_score: Optional[float] = None
    last_failure_mode: Optional[str] = None
    last_action_taken: Optional[str] = None
    last_pr_url: Optional[str] = None
    last_error: Optional[str] = None
    cycles_completed: int = 0
    healthy: bool = True


state = AgentState()


# ─────────────────────────────────────────────────────────────────────────
# Reasoning loop
# ─────────────────────────────────────────────────────────────────────────


def run_once(claude_client: Any, ctx: ToolContext) -> AgentAction:
    """One full investigation cycle. Returns the AgentAction recorded."""
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": USER_MESSAGE_TEMPLATE},
    ]
    captured: Dict[str, Any] = {}

    for turn in range(MAX_TOOL_TURNS):
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
            messages=messages,
        )

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        text_blocks = [block for block in response.content if block.type == "text"]

        if not tool_uses:
            for tb in text_blocks:
                captured.setdefault("final_text", "")
                captured["final_text"] += tb.text
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results: List[Dict[str, Any]] = []

        for tu in tool_uses:
            args = tu.input or {}
            result = dispatch_tool(tu.name, args, ctx)

            if tu.name == "get_current_anomaly_signal" and isinstance(result, dict):
                captured.setdefault("anomaly", result)
            if tu.name == "create_remediation_pr" and isinstance(result, dict):
                captured["pr_result"] = result
            if tu.name == "log_audit_event" and isinstance(result, dict):
                captured["audit"] = (args, result)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": _serialise(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            break

    return _summarise(captured)


def _serialise(result: Dict[str, Any]) -> str:
    import json

    try:
        return json.dumps(result, default=str)
    except TypeError:
        return json.dumps({"error": "result not JSON-serialisable"})


def _summarise(captured: Dict[str, Any]) -> AgentAction:
    anomaly = captured.get("anomaly") or {}
    score = float(anomaly.get("anomaly_score", 0.0))
    mode = anomaly.get("failure_mode", "NORMAL")
    confidence = float(anomaly.get("confidence", 0.0))

    pr = captured.get("pr_result") or {}
    pr_url = pr.get("pr_url") if isinstance(pr, dict) else None

    audit = captured.get("audit")
    if audit is not None and isinstance(audit[0], dict):
        action_taken = audit[0].get("action_taken")
    elif pr_url:
        action_taken = "pr_opened"
    elif mode == "NORMAL":
        action_taken = "skipped_normal"
    elif confidence < CONFIDENCE_THRESHOLD:
        action_taken = "skipped_low_confidence"
    else:
        action_taken = "logged_only"

    return AgentAction(
        anomaly_score=score,
        failure_mode=mode,
        confidence=confidence,
        action_taken=action_taken,
        pr_url=pr_url,
    )


async def run_loop(claude_client: Any, ctx: ToolContext) -> None:
    backoff = INITIAL_BACKOFF_SECONDS
    while True:
        try:
            action = await asyncio.to_thread(run_once, claude_client, ctx)
            state.last_run_at = time.time()
            state.last_anomaly_score = action.anomaly_score
            state.last_failure_mode = action.failure_mode
            state.last_action_taken = action.action_taken
            state.last_pr_url = action.pr_url
            state.last_error = None
            state.cycles_completed += 1
            state.healthy = True
            logger.info(
                "cycle complete: mode=%s score=%.3f action=%s pr=%s",
                action.failure_mode,
                action.anomaly_score,
                action.action_taken,
                action.pr_url,
            )
            backoff = INITIAL_BACKOFF_SECONDS
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except Exception as exc:  # noqa: BLE001
            logger.exception("cycle failed: %s", exc)
            state.last_error = f"{type(exc).__name__}: {exc}"
            state.healthy = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


# ─────────────────────────────────────────────────────────────────────────
# Bootstrap (Key Vault → context → loop)
# ─────────────────────────────────────────────────────────────────────────


def _build_context(claude_api_key: str, github_pem: str) -> ToolContext:
    """Wire up external clients. All optional clients tolerate being None
    in test/demo so that the agent still runs against a partial environment.
    """
    from agent.actions.github_app_auth import GitHubAppAuth

    github_auth = GitHubAppAuth(
        app_id=os.environ["GITHUB_APP_ID"],
        installation_id=os.environ["GITHUB_INSTALLATION_ID"],
        private_pem=github_pem,
    )

    azure_client: Any = None
    blob_container: Any = None
    k8s_core: Any = None

    aks_resource_id = os.environ.get("AZURE_AKS_RESOURCE_ID", "")
    storage_account = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")

    try:
        from azure.identity import DefaultAzureCredential
        from azure.monitor.query import MetricsQueryClient

        credential = DefaultAzureCredential()
        if aks_resource_id:
            azure_client = MetricsQueryClient(credential)
        if storage_account:
            from azure.storage.blob import BlobServiceClient

            from agent.constants import AUDIT_CONTAINER

            blob_service = BlobServiceClient(account_url=storage_account, credential=credential)
            blob_container = blob_service.get_container_client(AUDIT_CONTAINER)
    except Exception as exc:  # noqa: BLE001
        logger.warning("azure clients unavailable: %s", exc)

    try:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        k8s_core = k8s_client.CoreV1Api()
    except Exception as exc:  # noqa: BLE001
        logger.warning("kubernetes client unavailable: %s", exc)

    return ToolContext(
        ml_service_url=os.environ.get("ML_SERVICE_URL", "http://ml-service:8000"),
        github_owner=os.environ["GITHUB_REPO_OWNER"],
        github_repo=os.environ["GITHUB_REPO_NAME"],
        github_default_branch=os.environ.get("GITHUB_DEFAULT_BRANCH", "main"),
        github_auth=github_auth,
        azure_monitor_query=azure_client,
        aks_resource_id=aks_resource_id,
        k8s_core_v1=k8s_core,
        blob_container_client=blob_container,
        http_client=httpx.Client(timeout=20.0),
    )


def _load_secrets() -> tuple[str, str]:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    vault_url = os.environ["AZURE_KEYVAULT_URL"]
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    claude_key = client.get_secret(KEY_VAULT_SECRET_CLAUDE).value
    github_pem = client.get_secret(KEY_VAULT_SECRET_GITHUB).value
    return claude_key, github_pem


# ─────────────────────────────────────────────────────────────────────────
# FastAPI surface
# ─────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("AGENT_DRY_RUN", "false").lower() == "true":
        logger.info("AGENT_DRY_RUN set — skipping reasoning loop")
        yield
        return

    from anthropic import Anthropic

    claude_key, github_pem = _load_secrets()
    ctx = _build_context(claude_key, github_pem)
    claude_client = Anthropic(api_key=claude_key)

    task = asyncio.create_task(run_loop(claude_client, ctx))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="cloudsentro-agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok" if state.healthy else "degraded",
        "uptime_seconds": round(time.time() - state.started_at, 2),
        "cycles_completed": state.cycles_completed,
        "last_run_at": state.last_run_at,
        "last_anomaly_score": state.last_anomaly_score,
        "last_failure_mode": state.last_failure_mode,
        "last_action_taken": state.last_action_taken,
        "last_pr_url": state.last_pr_url,
        "last_error": state.last_error,
    }
