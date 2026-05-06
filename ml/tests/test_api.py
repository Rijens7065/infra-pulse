"""End-to-end test of the FastAPI app — requires trained artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ml.constants import N_CHANNELS, WINDOW_SIZE

ARTIFACTS_DIR = Path(__file__).parent.parent / "model" / "artifacts"
ARTIFACTS_PRESENT = (
    (ARTIFACTS_DIR / "lstm_autoencoder.pt").exists()
    and (ARTIFACTS_DIR / "failure_classifier.pkl").exists()
    and (ARTIFACTS_DIR / "scaler.pkl").exists()
    and (ARTIFACTS_DIR / "model_metadata.json").exists()
)

pytestmark = pytest.mark.skipif(
    not ARTIFACTS_PRESENT,
    reason="run python ml/train.py first to produce model artifacts",
)


@pytest.fixture(scope="module")
def client():
    from ml.serving.app import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "model_version" in body


def test_predict_normal(client):
    rng = np.random.default_rng(0)
    sample = rng.normal(loc=[40, 250_000_000, 0, 100, 2_500_000, 2_000_000, 0.12], scale=2, size=(WINDOW_SIZE, N_CHANNELS))
    r = client.post("/predict", json={"metrics": sample.tolist()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {
        "anomaly_score",
        "failure_mode",
        "confidence",
        "time_to_impact_minutes",
        "affected_metrics",
        "explanation",
    }
    assert 0.0 <= body["anomaly_score"] <= 1.0


def test_predict_rejects_wrong_shape(client):
    bad = [[0.0] * N_CHANNELS for _ in range(WINDOW_SIZE - 1)]
    r = client.post("/predict", json={"metrics": bad})
    assert r.status_code == 400


def test_metrics_prometheus(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "cloudsentro_predictions_total" in r.text


def test_inject_disabled_by_default(client):
    r = client.post(
        "/inject",
        json={"failure_mode": "OOM_LEAK", "intensity": 0.9, "duration_minutes": 5},
    )
    assert r.status_code == 403
