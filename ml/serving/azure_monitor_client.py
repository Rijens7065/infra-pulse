"""Azure Monitor metrics poller — fills a 60-step rolling window per channel.

The poller runs out-of-band of FastAPI request handling. The serving app
calls `latest_window()` to read the current 60x7 matrix.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Deque, List, Optional

import numpy as np
from azure.identity.aio import DefaultAzureCredential
from azure.monitor.query.aio import MetricsQueryClient

from ml.constants import N_CHANNELS, WINDOW_SIZE

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60
INITIAL_BACKOFF = 5
MAX_BACKOFF = 600

METRIC_MAP = [
    ("node_cpu_usage_percentage", "Average"),
    ("node_memory_working_set_bytes", "Average"),
    ("kube_pod_status_phase", "Total"),
    ("apiserver_request_duration_seconds_bucket", "Average"),
    ("node_network_in_bytes", "Average"),
    ("node_network_out_bytes", "Average"),
    ("Microsoft.Compute/virtualMachines.cost", "Total"),
]


@dataclass
class _Buffer:
    window: Deque[List[float]] = field(default_factory=deque)

    def push(self, sample: List[float]) -> None:
        if len(self.window) >= WINDOW_SIZE:
            self.window.popleft()
        self.window.append(sample)

    def filled(self) -> bool:
        return len(self.window) == WINDOW_SIZE

    def matrix(self) -> Optional[np.ndarray]:
        if not self.filled():
            return None
        return np.array(self.window, dtype=np.float32)


class AzureMonitorClient:
    def __init__(self, resource_id: Optional[str] = None) -> None:
        self.resource_id = resource_id or os.environ["AZURE_AKS_RESOURCE_ID"]
        self.buffer = _Buffer()
        self._credential: Optional[DefaultAzureCredential] = None
        self._client: Optional[MetricsQueryClient] = None
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def __aenter__(self) -> "AzureMonitorClient":
        self._credential = DefaultAzureCredential()
        self._client = MetricsQueryClient(self._credential)
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._client is not None:
            await self._client.close()
        if self._credential is not None:
            await self._credential.close()

    async def _query_once(self) -> List[float]:
        sample = [0.0] * N_CHANNELS
        for idx, (metric, agg) in enumerate(METRIC_MAP):
            try:
                response = await self._client.query_resource(
                    self.resource_id,
                    metric_names=[metric],
                    timespan=timedelta(minutes=1),
                    aggregations=[agg],
                )
                values = [
                    pt.average if agg == "Average" else pt.total
                    for m in response.metrics
                    for ts in m.timeseries
                    for pt in ts.data
                    if (pt.average if agg == "Average" else pt.total) is not None
                ]
                sample[idx] = float(values[-1]) if values else 0.0
            except Exception as exc:  # noqa: BLE001
                logger.warning("metric %s query failed: %s", metric, exc)
                sample[idx] = 0.0
        return sample

    async def _poll_loop(self) -> None:
        backoff = INITIAL_BACKOFF
        while not self._stop.is_set():
            try:
                sample = await self._query_once()
                self.buffer.push(sample)
                backoff = INITIAL_BACKOFF
                await asyncio.wait_for(
                    self._stop.wait(), timeout=POLL_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("poll loop error, backing off %ds: %s", backoff, exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, MAX_BACKOFF)

    async def backfill(self) -> None:
        """Pre-fill the buffer with WINDOW_SIZE samples on startup."""
        for _ in range(WINDOW_SIZE):
            sample = await self._query_once()
            self.buffer.push(sample)
            await asyncio.sleep(0)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    def latest_window(self) -> Optional[np.ndarray]:
        return self.buffer.matrix()


async def _run() -> None:
    logging.basicConfig(level=logging.INFO)
    async with AzureMonitorClient() as client:
        sample = await client._query_once()
        print(f"sample: {sample}")


if __name__ == "__main__":
    asyncio.run(_run())
