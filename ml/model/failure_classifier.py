"""Two-stage failure classifier and the AnomalySignal output contract.

Stage 1 — IsolationForest on per-channel reconstruction error.
Stage 2 — RandomForest 6-class failure mode prediction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier

from ml.constants import FAILURE_MODES, METRIC_CHANNELS

ANOMALY_THRESHOLD_QUANTILE = 0.85


@dataclass
class AnomalySignal:
    anomaly_score: float
    failure_mode: str
    confidence: float
    time_to_impact_minutes: Optional[int]
    affected_metrics: List[str]
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


_EXPLANATIONS = {
    "NORMAL": "All channels within normal operating range.",
    "OOM_LEAK": "Memory RSS climbing linearly toward pod limit — pod restart imminent.",
    "CPU_THROTTLE": "CPU saturated near 100% with multi-fold latency increase.",
    "NETWORK_DEGRADATION": "Throughput dropped sharply with elevated tail latency.",
    "COST_SPIKE": "Hourly cost diverging from 7-day rolling baseline.",
    "SECURITY_DRIFT": "Outbound traffic anomaly without matching inbound activity.",
}

_AFFECTED = {
    "NORMAL": [],
    "OOM_LEAK": ["memory_rss_bytes", "pod_restart_count"],
    "CPU_THROTTLE": ["cpu_usage_percent", "http_p99_latency_ms"],
    "NETWORK_DEGRADATION": [
        "network_bytes_in",
        "network_bytes_out",
        "http_p99_latency_ms",
    ],
    "COST_SPIKE": ["azure_cost_per_hour_usd"],
    "SECURITY_DRIFT": ["network_bytes_out"],
}

_TIME_TO_IMPACT = {
    "NORMAL": None,
    "OOM_LEAK": 30,
    "CPU_THROTTLE": 5,
    "NETWORK_DEGRADATION": 10,
    "COST_SPIKE": 60,
    "SECURITY_DRIFT": 15,
}


@dataclass
class FailureClassifier:
    isolation_forest: IsolationForest = field(
        default_factory=lambda: IsolationForest(n_estimators=100, contamination=0.15, random_state=42)
    )
    random_forest: RandomForestClassifier = field(
        default_factory=lambda: RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
    )
    anomaly_threshold: float = 0.0
    classes_: List[str] = field(default_factory=list)

    def fit(self, recon_error_per_channel: np.ndarray, labels: np.ndarray) -> None:
        normal_mask = labels == "NORMAL"
        self.isolation_forest.fit(recon_error_per_channel[normal_mask])
        normal_scores = self.isolation_forest.score_samples(
            recon_error_per_channel[normal_mask]
        )
        self.anomaly_threshold = float(
            np.quantile(normal_scores, 1 - ANOMALY_THRESHOLD_QUANTILE)
        )

        self.random_forest.fit(recon_error_per_channel, labels)
        self.classes_ = list(self.random_forest.classes_)

    def predict(
        self, recon_error_per_channel: np.ndarray, anomaly_score: float
    ) -> AnomalySignal:
        if recon_error_per_channel.ndim == 1:
            recon_error_per_channel = recon_error_per_channel[None, :]

        iso_score = float(
            self.isolation_forest.score_samples(recon_error_per_channel)[0]
        )
        is_anomalous = iso_score < self.anomaly_threshold

        proba = self.random_forest.predict_proba(recon_error_per_channel)[0]
        idx = int(np.argmax(proba))
        mode = self.classes_[idx]
        confidence = float(proba[idx])

        if not is_anomalous:
            mode = "NORMAL"
            confidence = max(confidence, 0.5)

        return AnomalySignal(
            anomaly_score=float(np.clip(anomaly_score, 0.0, 1.0)),
            failure_mode=mode,
            confidence=confidence,
            time_to_impact_minutes=_TIME_TO_IMPACT[mode],
            affected_metrics=list(_AFFECTED[mode]),
            explanation=_EXPLANATIONS[mode],
        )

    def predict_batch(self, recon_error_per_channel: np.ndarray) -> np.ndarray:
        return self.random_forest.predict(recon_error_per_channel)


def validate_failure_modes(classes: List[str]) -> None:
    expected = set(FAILURE_MODES)
    actual = set(classes)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        raise ValueError(
            f"failure mode mismatch — missing={missing}, extra={extra}"
        )


def assert_channels_match(channels: List[str]) -> None:
    if list(channels) != METRIC_CHANNELS:
        raise ValueError(
            f"channel order mismatch — expected {METRIC_CHANNELS}, got {channels}"
        )
