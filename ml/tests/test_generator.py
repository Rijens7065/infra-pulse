"""Tests for the synthetic data generator."""

from __future__ import annotations

import numpy as np
import pytest

from ml.constants import FAILURE_MODES, MEMORY_LIMIT_BYTES, METRIC_CHANNELS
from ml.data.generator import ROWS_PER_DAY, generate


@pytest.fixture(scope="module")
def small_dataset():
    metrics, labels, windows = generate(seed=42, days=10)
    return metrics, labels, windows


def test_shape_and_columns(small_dataset):
    metrics, labels, _ = small_dataset
    assert len(metrics) == 10 * ROWS_PER_DAY
    assert list(metrics.columns) == METRIC_CHANNELS
    assert len(labels) == len(metrics)
    assert "failure_mode" in labels.columns


def test_labels_are_known_classes(small_dataset):
    _, labels, _ = small_dataset
    unique = set(labels["failure_mode"].unique())
    assert unique.issubset(set(FAILURE_MODES))


def test_normal_dominates(small_dataset):
    _, labels, _ = small_dataset
    counts = labels["failure_mode"].value_counts(normalize=True)
    assert counts.get("NORMAL", 0) >= 0.7


def test_metrics_within_physical_ranges(small_dataset):
    metrics, _, _ = small_dataset
    assert metrics["cpu_usage_percent"].between(0, 100).all()
    assert (metrics["memory_rss_bytes"] <= MEMORY_LIMIT_BYTES).all()
    assert (metrics["http_p99_latency_ms"] >= 0).all()
    assert (metrics["network_bytes_in"] >= 0).all()
    assert (metrics["network_bytes_out"] >= 0).all()


def test_seed_is_deterministic():
    a, _, _ = generate(seed=7, days=2)
    b, _, _ = generate(seed=7, days=2)
    np.testing.assert_array_equal(a.to_numpy(), b.to_numpy())


def test_anomaly_windows_present(small_dataset):
    _, _, windows = small_dataset
    modes_seen = {w.failure_mode for w in windows}
    assert modes_seen.issubset(set(FAILURE_MODES) - {"NORMAL"})
