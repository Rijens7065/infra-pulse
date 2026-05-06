"""FastAPI inference server for the CloudSentro anomaly model."""

from __future__ import annotations

import json
import os
import pickle
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from ml.constants import FAILURE_MODES, N_CHANNELS, WINDOW_SIZE
from ml.model.failure_classifier import AnomalySignal, FailureClassifier
from ml.model.lstm_autoencoder import LSTMAutoencoder, reconstruction_error

ARTIFACTS_DIR = Path(__file__).parent.parent / "model" / "artifacts"

ANOMALY_SCORE = Gauge(
    "cloudsentro_anomaly_score", "Current anomaly score (0.0-1.0)"
)
PREDICTIONS_TOTAL = Counter(
    "cloudsentro_predictions_total",
    "Total predictions served",
    ["failure_mode"],
)
PREDICTION_DURATION = Histogram(
    "cloudsentro_prediction_duration_seconds",
    "Prediction latency in seconds",
)


class PredictRequest(BaseModel):
    metrics: List[List[float]] = Field(
        ...,
        description=f"{WINDOW_SIZE}x{N_CHANNELS} matrix of metric values",
    )


class InjectRequest(BaseModel):
    failure_mode: str
    intensity: float = Field(default=0.8, ge=0.0, le=1.0)
    duration_minutes: int = Field(default=10, ge=1, le=120)


class HealthResponse(BaseModel):
    status: str
    model_version: str
    uptime_seconds: float


class ModelBundle:
    def __init__(self) -> None:
        self.autoencoder: Optional[LSTMAutoencoder] = None
        self.classifier: Optional[FailureClassifier] = None
        self.scaler = None
        self.metadata: dict = {}
        self.loaded_at: float = 0.0
        self.injection: Optional[InjectRequest] = None
        self.injection_expires_at: float = 0.0

    def load(self) -> None:
        with (ARTIFACTS_DIR / "model_metadata.json").open() as f:
            self.metadata = json.load(f)
        self.autoencoder = LSTMAutoencoder()
        state = torch.load(
            ARTIFACTS_DIR / "lstm_autoencoder.pt",
            map_location="cpu",
            weights_only=True,
        )
        self.autoencoder.load_state_dict(state)
        self.autoencoder.eval()
        with (ARTIFACTS_DIR / "failure_classifier.pkl").open("rb") as f:
            self.classifier = pickle.load(f)
        with (ARTIFACTS_DIR / "scaler.pkl").open("rb") as f:
            self.scaler = pickle.load(f)
        self.loaded_at = time.time()

    @property
    def ref_max(self) -> float:
        return float(self.metadata.get("anomaly_score_ref_max", 1e-3))

    def active_injection(self) -> Optional[InjectRequest]:
        if self.injection is None:
            return None
        if time.time() > self.injection_expires_at:
            self.injection = None
            return None
        return self.injection


bundle = ModelBundle()
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle.load()
    yield


app = FastAPI(title="cloudsentro-ml", version="0.1.0", lifespan=lifespan)


def _predict_signal(window: np.ndarray) -> AnomalySignal:
    if window.shape != (WINDOW_SIZE, N_CHANNELS):
        raise HTTPException(
            status_code=400,
            detail=f"metrics must be {WINDOW_SIZE}x{N_CHANNELS}, got {window.shape}",
        )

    scaled = bundle.scaler.transform(window).astype(np.float32)
    tensor = torch.from_numpy(scaled).unsqueeze(0)
    per_channel = reconstruction_error(
        bundle.autoencoder, tensor, per_channel=True
    ).numpy()
    raw_score = float(per_channel.mean())
    anomaly_score = float(np.clip(raw_score / max(bundle.ref_max, 1e-8), 0.0, 1.0))

    signal = bundle.classifier.predict(per_channel[0], anomaly_score)

    injection = bundle.active_injection()
    if injection is not None:
        signal.failure_mode = injection.failure_mode
        signal.confidence = max(signal.confidence, injection.intensity)
        signal.anomaly_score = max(signal.anomaly_score, injection.intensity)

    return signal


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    if bundle.autoencoder is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return HealthResponse(
        status="ok",
        model_version=bundle.metadata.get("model_version", "unknown"),
        uptime_seconds=round(time.time() - bundle.loaded_at, 2),
    )


@app.post("/predict")
async def predict(req: PredictRequest) -> dict:
    start = time.time()
    window = np.asarray(req.metrics, dtype=np.float32)
    signal = _predict_signal(window)

    elapsed = time.time() - start
    PREDICTION_DURATION.observe(elapsed)
    PREDICTIONS_TOTAL.labels(failure_mode=signal.failure_mode).inc()
    ANOMALY_SCORE.set(signal.anomaly_score)
    return signal.to_dict()


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/inject")
async def inject(req: InjectRequest) -> dict:
    if not DEMO_MODE:
        raise HTTPException(
            status_code=403, detail="inject endpoint disabled (set DEMO_MODE=true)"
        )
    if req.failure_mode not in FAILURE_MODES:
        raise HTTPException(
            status_code=400, detail=f"failure_mode must be one of {FAILURE_MODES}"
        )
    bundle.injection = req
    bundle.injection_expires_at = time.time() + req.duration_minutes * 60
    return {
        "status": "injected",
        "failure_mode": req.failure_mode,
        "expires_at": bundle.injection_expires_at,
    }
