"""Synthetic AKS metrics generator with labeled anomaly windows.

Produces 30 days of 1-min interval data across 7 channels with a diurnal
baseline plus 8-15 injected anomaly windows covering the 5 non-NORMAL
failure modes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.constants import FAILURE_MODES, MEMORY_LIMIT_BYTES, METRIC_CHANNELS

ROWS_PER_DAY = 60 * 24
DEFAULT_DAYS = 30


@dataclass
class AnomalyWindow:
    start: int
    end: int
    failure_mode: str


def _diurnal_baseline(n_rows: int, rng: np.random.Generator) -> pd.DataFrame:
    """Healthy weekday-style traffic — peak 09:00-18:00 UTC, gaussian noise."""
    minutes = np.arange(n_rows)
    hour_of_day = (minutes // 60) % 24
    business_hours = ((hour_of_day >= 9) & (hour_of_day < 18)).astype(float)
    diurnal = 0.4 + 0.6 * business_hours + 0.1 * np.sin(2 * np.pi * minutes / 1440)

    data = {
        "cpu_usage_percent": np.clip(20 + 25 * diurnal + rng.normal(0, 3, n_rows), 5, 95),
        "memory_rss_bytes": np.clip(
            (180 + 40 * diurnal) * 1024 * 1024 + rng.normal(0, 5_000_000, n_rows),
            100 * 1024 * 1024,
            MEMORY_LIMIT_BYTES * 0.7,
        ),
        "pod_restart_count": np.zeros(n_rows),
        "http_p99_latency_ms": np.clip(
            80 + 60 * diurnal + rng.normal(0, 8, n_rows), 30, 400
        ),
        "network_bytes_in": np.clip(
            (1.5e6 + 3e6 * diurnal) + rng.normal(0, 2e5, n_rows), 1e5, None
        ),
        "network_bytes_out": np.clip(
            (1.0e6 + 2.5e6 * diurnal) + rng.normal(0, 2e5, n_rows), 1e5, None
        ),
        "azure_cost_per_hour_usd": np.clip(
            0.10 + 0.04 * diurnal + rng.normal(0, 0.005, n_rows), 0.05, None
        ),
    }
    return pd.DataFrame(data, columns=METRIC_CHANNELS)


def _inject_oom_leak(df: pd.DataFrame, start: int, end: int) -> None:
    """Memory grows linearly from baseline toward the pod limit over the window."""
    n = end - start
    base = df.loc[start - 1, "memory_rss_bytes"] if start > 0 else 200 * 1024 * 1024
    target = MEMORY_LIMIT_BYTES * 0.98
    df.loc[start : end - 1, "memory_rss_bytes"] = np.linspace(base, target, n)
    df.loc[end - 1, "pod_restart_count"] = 1


def _inject_cpu_throttle(df: pd.DataFrame, start: int, end: int, rng: np.random.Generator) -> None:
    """CPU pinned 95-100%, latency multiplies 3-5x."""
    n = end - start
    df.loc[start : end - 1, "cpu_usage_percent"] = np.clip(
        rng.uniform(95, 100, n), 0, 100
    )
    df.loc[start : end - 1, "http_p99_latency_ms"] *= rng.uniform(3, 5)


def _inject_network_degradation(
    df: pd.DataFrame, start: int, end: int, rng: np.random.Generator
) -> None:
    """Throughput drops 60-80%, latency +200-400%."""
    drop = rng.uniform(0.20, 0.40)
    lat_mult = rng.uniform(3.0, 5.0)
    df.loc[start : end - 1, "network_bytes_in"] *= drop
    df.loc[start : end - 1, "network_bytes_out"] *= drop
    df.loc[start : end - 1, "http_p99_latency_ms"] *= lat_mult


def _inject_cost_spike(df: pd.DataFrame, start: int, end: int, rng: np.random.Generator) -> None:
    """Hourly cost runs 50-90% above baseline."""
    multiplier = rng.uniform(1.5, 1.9)
    df.loc[start : end - 1, "azure_cost_per_hour_usd"] *= multiplier


def _inject_security_drift(
    df: pd.DataFrame, start: int, end: int, rng: np.random.Generator
) -> None:
    """Outbound traffic spikes erratically while inbound stays normal."""
    spike = rng.uniform(2.5, 5.0, end - start)
    df.loc[start : end - 1, "network_bytes_out"] *= spike


_INJECTORS = {
    "OOM_LEAK": lambda df, s, e, rng: _inject_oom_leak(df, s, e),
    "CPU_THROTTLE": _inject_cpu_throttle,
    "NETWORK_DEGRADATION": _inject_network_degradation,
    "COST_SPIKE": _inject_cost_spike,
    "SECURITY_DRIFT": _inject_security_drift,
}


def _plan_anomalies(
    n_rows: int, rng: np.random.Generator
) -> list[AnomalyWindow]:
    n_anomalies = rng.integers(8, 16)
    modes = [m for m in FAILURE_MODES if m != "NORMAL"]
    windows: list[AnomalyWindow] = []

    margin = 120
    placed: list[tuple[int, int]] = []

    for _ in range(int(n_anomalies)):
        mode = modes[rng.integers(0, len(modes))]
        duration = int(rng.integers(60, 240))

        for _attempt in range(50):
            start = int(rng.integers(margin, n_rows - duration - margin))
            end = start + duration
            if all(end + margin < ps or start > pe + margin for ps, pe in placed):
                placed.append((start, end))
                windows.append(AnomalyWindow(start, end, mode))
                break

    windows.sort(key=lambda w: w.start)
    return windows


def generate(seed: int, days: int) -> tuple[pd.DataFrame, pd.DataFrame, list[AnomalyWindow]]:
    rng = np.random.default_rng(seed)
    n_rows = days * ROWS_PER_DAY

    metrics = _diurnal_baseline(n_rows, rng)
    labels = pd.DataFrame({"failure_mode": ["NORMAL"] * n_rows})

    windows = _plan_anomalies(n_rows, rng)
    for w in windows:
        _INJECTORS[w.failure_mode](metrics, w.start, w.end, rng)
        labels.loc[w.start : w.end - 1, "failure_mode"] = w.failure_mode

    return metrics, labels, windows


def _write_report(
    out_dir: Path, metrics: pd.DataFrame, labels: pd.DataFrame, windows: list[AnomalyWindow]
) -> None:
    counts = labels["failure_mode"].value_counts().to_dict()
    lines = [
        f"rows: {len(metrics):,}",
        f"channels: {list(metrics.columns)}",
        f"anomaly_windows: {len(windows)}",
        "",
        "label distribution:",
        *[f"  {k}: {v:,} ({100 * v / len(labels):.1f}%)" for k, v in counts.items()],
        "",
        "windows:",
        *[
            f"  [{w.start:>6}, {w.end:>6}) {w.failure_mode}  ({w.end - w.start} min)"
            for w in windows
        ],
    ]
    (out_dir / "generator_report.txt").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic AKS metrics.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Directory for parquet outputs and report.",
    )
    args = parser.parse_args()

    metrics, labels, windows = generate(args.seed, args.days)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_parquet(args.out_dir / "synthetic_metrics.parquet", index=False)
    labels.to_parquet(args.out_dir / "synthetic_labels.parquet", index=False)
    _write_report(args.out_dir, metrics, labels, windows)

    print(
        f"generated {len(metrics):,} rows, {len(windows)} anomaly windows "
        f"-> {args.out_dir}"
    )


if __name__ == "__main__":
    main()
