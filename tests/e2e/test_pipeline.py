"""End-to-end pipeline tests against a deployed CloudSentro cluster.

Skips automatically if the cluster isn't reachable, so the suite is safe
to include in normal CI without infrastructure access. To run:

    DASHBOARD_URL=https://infra-pulse.cloudsentro.com/grafana/ \\
    GH_REPO=Rijens7065/infra-pulse \\
    pytest tests/e2e -v -s

The tests use ``kubectl port-forward`` for in-cluster service calls. They
expect the ML and agent pods deployed in the ``cloudsentro`` namespace.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import socket
import subprocess
import time
import urllib.request
from typing import Optional, Tuple

import pytest

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://infra-pulse.cloudsentro.com/grafana/")
GH_REPO = os.environ.get("GH_REPO", "Rijens7065/infra-pulse")
NAMESPACE = os.environ.get("NAMESPACE", "cloudsentro")
ML_PORT = int(os.environ.get("ML_LOCAL_PORT", "18000"))
AGENT_PORT = int(os.environ.get("AGENT_LOCAL_PORT", "18001"))


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


def _kubectl_available() -> bool:
    try:
        subprocess.run(
            ["kubectl", "version", "--client=true", "--output=json"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def _has_pod(label: str) -> bool:
    try:
        out = subprocess.run(
            ["kubectl", "get", "pods", "-n", NAMESPACE, "-l", label, "-o", "name"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(out.stdout.strip())
    except subprocess.SubprocessError:
        return False


pytestmark = pytest.mark.skipif(
    not _kubectl_available(),
    reason="kubectl not available — e2e tests require a configured kubeconfig",
)


@contextlib.contextmanager
def port_forward(service: str, remote: int, local: int):
    proc = subprocess.Popen(
        [
            "kubectl",
            "port-forward",
            "-n",
            NAMESPACE,
            f"svc/{service}",
            f"{local}:{remote}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        with contextlib.closing(socket.socket()) as s:
            s.settimeout(1.0)
            try:
                s.connect(("127.0.0.1", local))
                break
            except OSError:
                time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError(f"port-forward to localhost:{local} did not open")
    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _http_get(host: str, port: int, path: str, timeout: float = 5.0) -> Tuple[int, str]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, resp.read().decode("utf-8")


def _http_post(host: str, port: int, path: str, body: dict, timeout: float = 10.0) -> Tuple[int, dict]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
    resp = conn.getresponse()
    payload = resp.read().decode("utf-8")
    try:
        decoded = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        decoded = {"raw": payload}
    return resp.status, decoded


def _baseline_window() -> list:
    sample = [40.0, 2.5e8, 0.0, 100.0, 2.5e6, 2.0e6, 0.12]
    return [sample[:] for _ in range(60)]


# ─────────────────────────────────────────────────────────────────────────
# Tests — order matters: pytest -p no:randomly OR rely on default ordering
# ─────────────────────────────────────────────────────────────────────────


def test_01_services_healthy():
    """Public dashboard, ML pod, agent pod all healthy."""
    with urllib.request.urlopen(DASHBOARD_URL, timeout=8) as r:
        assert r.status in (200, 302), f"dashboard returned {r.status}"

    if not _has_pod("app=ml-service"):
        pytest.skip("ml-service pod not deployed")
    with port_forward("ml-service", 8000, ML_PORT):
        status, body = _http_get("127.0.0.1", ML_PORT, "/health")
        assert status == 200, body
        assert json.loads(body).get("status") == "ok"

    if not _has_pod("app=agent-service"):
        pytest.skip("agent-service pod not deployed")
    with port_forward("agent-service", 8001, AGENT_PORT):
        status, body = _http_get("127.0.0.1", AGENT_PORT, "/health")
        assert status == 200, body
        assert json.loads(body).get("status") in ("ok", "degraded")


def test_02_baseline_normal():
    """A normal-looking 60×7 window should classify as NORMAL with low score."""
    if not _has_pod("app=ml-service"):
        pytest.skip("ml-service pod not deployed")

    with port_forward("ml-service", 8000, ML_PORT):
        status, body = _http_post(
            "127.0.0.1", ML_PORT, "/predict", {"metrics": _baseline_window()}
        )
        assert status == 200, body
        assert body["failure_mode"] == "NORMAL", body
        assert body["anomaly_score"] < 0.5, body


@pytest.mark.parametrize("mode", ["OOM_LEAK", "CPU_THROTTLE"])
def test_03_inject_raises_score(mode: str):
    """After /inject, /predict reflects the injected mode within the duration."""
    if not _has_pod("app=ml-service"):
        pytest.skip("ml-service pod not deployed")

    with port_forward("ml-service", 8000, ML_PORT):
        status, body = _http_post(
            "127.0.0.1",
            ML_PORT,
            "/inject",
            {"failure_mode": mode, "intensity": 0.95, "duration_minutes": 3},
        )
        if status == 403:
            pytest.skip("DEMO_MODE=false on ML deployment — skipping injection test")
        assert status == 200, body

        deadline = time.time() + 180
        while time.time() < deadline:
            _, predict = _http_post(
                "127.0.0.1", ML_PORT, "/predict", {"metrics": _baseline_window()}
            )
            if predict.get("anomaly_score", 0) > 0.7 and predict.get("failure_mode") == mode:
                return
            time.sleep(5)
        pytest.fail(f"score for {mode} did not exceed 0.7 within 3 min")


def test_04_agent_opens_pr():
    """The agent should open a PR labeled `agent-remediation` within 8 minutes."""
    if not GH_REPO:
        pytest.skip("GH_REPO not set")

    deadline = time.time() + 8 * 60
    while time.time() < deadline:
        with urllib.request.urlopen(
            f"https://api.github.com/repos/{GH_REPO}/pulls?state=open&per_page=20",
            timeout=8,
        ) as r:
            pulls = json.loads(r.read())
        for pr in pulls:
            labels = {label["name"] for label in pr.get("labels", [])}
            if "agent-remediation" in labels:
                assert pr["html_url"].startswith("https://github.com/")
                body = pr.get("body") or ""
                for section in [
                    "Anomaly Report",
                    "Root Cause",
                    "Reasoning Chain",
                    "Proposed Changes",
                    "Rollback Instructions",
                ]:
                    assert section in body, f"PR body missing section: {section}"
                return
        time.sleep(15)
    pytest.fail("no agent-remediation PR appeared within 8 minutes")


def test_05_audit_log_exists():
    """Best-effort: verify the audit blob exists. Skips if storage isn't configured."""
    storage_url = os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not storage_url:
        pytest.skip("AZURE_STORAGE_ACCOUNT_URL not set — cannot check audit log")

    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        pytest.skip("azure-identity / azure-storage-blob not installed")

    today = time.strftime("%Y-%m-%d", time.gmtime())
    blob_name = f"audit/{today}.jsonl"

    client = BlobServiceClient(account_url=storage_url, credential=DefaultAzureCredential())
    container = client.get_container_client("agent-audit-log")
    blob = container.get_blob_client(blob_name)
    assert blob.exists(), f"audit blob missing: {blob_name}"
