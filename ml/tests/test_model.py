"""Tests for the LSTM autoencoder and failure classifier."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from ml.constants import FAILURE_MODES, N_CHANNELS, WINDOW_SIZE
from ml.model.failure_classifier import (
    AnomalySignal,
    FailureClassifier,
    assert_channels_match,
    validate_failure_modes,
)
from ml.model.lstm_autoencoder import LSTMAutoencoder, reconstruction_error


def test_autoencoder_forward_shape():
    model = LSTMAutoencoder()
    x = torch.zeros(4, WINDOW_SIZE, N_CHANNELS)
    out = model(x)
    assert out.shape == x.shape


def test_reconstruction_error_shapes():
    model = LSTMAutoencoder()
    x = torch.randn(8, WINDOW_SIZE, N_CHANNELS)
    err = reconstruction_error(model, x)
    assert err.shape == (8,)
    err_pc = reconstruction_error(model, x, per_channel=True)
    assert err_pc.shape == (8, N_CHANNELS)


def test_classifier_round_trip():
    rng = np.random.default_rng(0)
    n_per_class = 60
    samples, labels = [], []
    for class_idx, mode in enumerate(FAILURE_MODES):
        center = np.zeros(N_CHANNELS)
        if mode != "NORMAL":
            center[class_idx % N_CHANNELS] = 5.0
        samples.append(center + rng.normal(0, 0.3, (n_per_class, N_CHANNELS)))
        labels.extend([mode] * n_per_class)
    X = np.vstack(samples)
    y = np.array(labels)

    clf = FailureClassifier()
    clf.fit(X, y)
    validate_failure_modes(clf.classes_)

    pred = clf.predict(X[0], anomaly_score=0.1)
    assert isinstance(pred, AnomalySignal)
    assert pred.failure_mode in FAILURE_MODES
    assert 0.0 <= pred.anomaly_score <= 1.0
    assert 0.0 <= pred.confidence <= 1.0


def test_validate_failure_modes_rejects_mismatch():
    with pytest.raises(ValueError):
        validate_failure_modes(["NORMAL", "OOM_LEAK"])


def test_assert_channels_match_rejects_wrong_order():
    with pytest.raises(ValueError):
        assert_channels_match(["memory_rss_bytes", "cpu_usage_percent"])


def test_anomaly_signal_to_dict_keys():
    s = AnomalySignal(
        anomaly_score=0.4,
        failure_mode="NORMAL",
        confidence=0.9,
        time_to_impact_minutes=None,
        affected_metrics=[],
        explanation="x",
    )
    d = s.to_dict()
    assert set(d.keys()) == {
        "anomaly_score",
        "failure_mode",
        "confidence",
        "time_to_impact_minutes",
        "affected_metrics",
        "explanation",
    }
