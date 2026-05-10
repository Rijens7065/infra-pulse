"""Trigger an injected anomaly on the ML serving pod for the demo.

The ML pod's `/inject` endpoint is gated behind ``DEMO_MODE=true``. When
the ML deployment is configured for demo (it is by default in this repo),
this script wakes up the inject endpoint via ``kubectl port-forward``,
sends the override, and prints a watch URL.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import socket
import subprocess
import sys
import time
from typing import Optional

DEFAULT_NAMESPACE = "cloudsentro"
DEFAULT_SERVICE = "ml-service"
DEFAULT_PORT = 8000
LOCAL_PORT = 18000

INTENSITY_SCORES = {"low": 0.75, "medium": 0.85, "high": 0.95}

FAILURE_MODES = [
    "OOM_LEAK",
    "CPU_THROTTLE",
    "NETWORK_DEGRADATION",
    "COST_SPIKE",
    "SECURITY_DRIFT",
]


def _free_port_or(default: int) -> int:
    with contextlib.closing(socket.socket()) as s:
        try:
            s.bind(("127.0.0.1", default))
            return default
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.closing(socket.socket()) as s:
            s.settimeout(1.0)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.3)
    raise TimeoutError(f"port-forward to localhost:{port} did not open within {timeout}s")


@contextlib.contextmanager
def port_forward(namespace: str, service: str, remote_port: int, local_port: int):
    """Run kubectl port-forward in the background, yield once it's ready."""
    cmd = [
        "kubectl",
        "port-forward",
        "-n",
        namespace,
        f"svc/{service}",
        f"{local_port}:{remote_port}",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(local_port)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def post_inject(local_port: int, mode: str, intensity: float, duration: int) -> dict:
    body = json.dumps(
        {"failure_mode": mode, "intensity": intensity, "duration_minutes": duration}
    )
    conn = http.client.HTTPConnection("127.0.0.1", local_port, timeout=10)
    conn.request("POST", "/inject", body, {"Content-Type": "application/json"})
    response = conn.getresponse()
    payload = response.read().decode("utf-8")
    if response.status >= 400:
        raise RuntimeError(f"inject failed [{response.status}]: {payload}")
    return json.loads(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=FAILURE_MODES)
    parser.add_argument(
        "--intensity",
        choices=list(INTENSITY_SCORES.keys()),
        default="high",
    )
    parser.add_argument("--duration", type=int, default=10, help="Minutes (1-120).")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--remote-port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--watch-url",
        default="https://infra-pulse.cloudsentro.com/grafana/",
        help="URL printed at the end so the user can monitor.",
    )
    args = parser.parse_args()

    intensity_score = INTENSITY_SCORES[args.intensity]
    local_port = _free_port_or(LOCAL_PORT)

    print(
        f"injecting {args.mode} (intensity={args.intensity}={intensity_score}, "
        f"duration={args.duration}m) via {args.namespace}/{args.service}:{args.remote_port}"
    )

    with port_forward(args.namespace, args.service, args.remote_port, local_port):
        result = post_inject(local_port, args.mode, intensity_score, args.duration)

    print("inject accepted:")
    print(json.dumps(result, indent=2))
    print()
    print(f"watch the dashboard: {args.watch_url}")
    print("the agent will see the anomaly on its next polling cycle (max 300s).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
