"""Train the LSTM autoencoder + failure classifier and save artifacts.

Pipeline:
  1. Load synthetic_metrics + synthetic_labels (run generator if missing)
  2. Build 60-step sliding windows, label each by majority class
  3. 70/15/15 stratified train/val/test split
  4. Fit StandardScaler on NORMAL training windows
  5. Train LSTM autoencoder on NORMAL training windows
  6. Compute per-channel reconstruction error on every window
  7. Train two-stage classifier
  8. Assert test accuracy > 0.85, otherwise raise
  9. Save artifacts to ml/model/artifacts/
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch import nn, optim
from torch.utils.data import DataLoader, TensorDataset

from ml.constants import METRIC_CHANNELS, N_CHANNELS, WINDOW_SIZE
from ml.data.generator import generate as generate_data
from ml.model.failure_classifier import (
    FailureClassifier,
    assert_channels_match,
    validate_failure_modes,
)
from ml.model.lstm_autoencoder import LSTMAutoencoder, reconstruction_error

ML_DIR = Path(__file__).parent
ARTIFACTS_DIR = ML_DIR / "model" / "artifacts"
DATA_DIR = ML_DIR / "data"

WINDOW_STRIDE = 5
BATCH_SIZE = 64
LEARNING_RATE = 1e-3
MAX_EPOCHS = 30
PATIENCE = 5
ACCURACY_THRESHOLD = 0.85
MODEL_VERSION = "0.1.0"


def _load_or_generate(seed: int, days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    metrics_path = DATA_DIR / "synthetic_metrics.parquet"
    labels_path = DATA_DIR / "synthetic_labels.parquet"

    if metrics_path.exists() and labels_path.exists():
        print(f"loading existing data from {DATA_DIR}")
        return pd.read_parquet(metrics_path), pd.read_parquet(labels_path)

    print(f"generating synthetic data (seed={seed}, days={days})")
    metrics, labels, _ = generate_data(seed, days)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_parquet(metrics_path, index=False)
    labels.to_parquet(labels_path, index=False)
    return metrics, labels


def _build_windows(
    metrics: pd.DataFrame, labels: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    assert_channels_match(list(metrics.columns))
    arr = metrics.to_numpy(dtype=np.float32)
    label_arr = labels["failure_mode"].to_numpy()

    n = len(arr) - WINDOW_SIZE + 1
    indices = np.arange(0, n, WINDOW_STRIDE)
    X = np.stack([arr[i : i + WINDOW_SIZE] for i in indices])

    window_labels = []
    for i in indices:
        slice_labels = label_arr[i : i + WINDOW_SIZE]
        vals, counts = np.unique(slice_labels, return_counts=True)
        window_labels.append(vals[np.argmax(counts)])
    y = np.array(window_labels)

    return X, y


def _scale(
    X_train: np.ndarray, X_val: np.ndarray, X_test: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, StandardScaler]:
    scaler = StandardScaler()
    flat_train = X_train.reshape(-1, N_CHANNELS)
    scaler.fit(flat_train)

    def apply(x: np.ndarray) -> np.ndarray:
        return scaler.transform(x.reshape(-1, N_CHANNELS)).reshape(x.shape).astype(np.float32)

    return apply(X_train), apply(X_val), apply(X_test), scaler


def _train_autoencoder(
    X_train_normal: np.ndarray, X_val_normal: np.ndarray
) -> LSTMAutoencoder:
    device = torch.device("cpu")
    torch.manual_seed(42)
    model = LSTMAutoencoder().to(device)

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_train_normal)),
        batch_size=BATCH_SIZE,
        shuffle=True,
    )
    val_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_val_normal)),
        batch_size=BATCH_SIZE,
    )

    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

    best_val = float("inf")
    best_state = None
    epochs_no_improve = 0

    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        running = 0.0
        n_batches = 0
        for (xb,) in train_loader:
            xb = xb.to(device)
            optimizer.zero_grad()
            recon = model(xb)
            loss = criterion(recon, xb)
            loss.backward()
            optimizer.step()
            running += loss.item()
            n_batches += 1
        train_loss = running / max(n_batches, 1)

        model.eval()
        val_running = 0.0
        n_val = 0
        with torch.no_grad():
            for (xb,) in val_loader:
                xb = xb.to(device)
                recon = model(xb)
                val_running += criterion(recon, xb).item()
                n_val += 1
        val_loss = val_running / max(n_val, 1)

        print(
            f"  epoch {epoch:2d}  train={train_loss:.5f}  val={val_loss:.5f}"
        )

        if val_loss < best_val - 1e-5:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= PATIENCE:
                print(f"  early stopping at epoch {epoch}")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def _per_channel_errors(
    model: LSTMAutoencoder, X: np.ndarray
) -> np.ndarray:
    out: list[np.ndarray] = []
    chunk = 256
    for i in range(0, len(X), chunk):
        batch = torch.from_numpy(X[i : i + chunk])
        out.append(reconstruction_error(model, batch, per_channel=True).numpy())
    return np.concatenate(out, axis=0)


def _normalize_anomaly_score(err: np.ndarray, ref_max: float) -> np.ndarray:
    return np.clip(err.mean(axis=1) / max(ref_max, 1e-8), 0.0, 1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    started = time.time()
    metrics, labels = _load_or_generate(args.seed, args.days)
    print(f"data: {len(metrics):,} rows")

    X, y = _build_windows(metrics, labels)
    print(f"windows: {X.shape}, label distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y, test_size=0.15, stratify=y, random_state=args.seed
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval,
        y_trainval,
        test_size=0.15 / 0.85,
        stratify=y_trainval,
        random_state=args.seed,
    )

    X_train_s, X_val_s, X_test_s, scaler = _scale(X_train, X_val, X_test)

    train_normal = X_train_s[y_train == "NORMAL"]
    val_normal = X_val_s[y_val == "NORMAL"]
    print(f"training autoencoder on {len(train_normal):,} NORMAL windows")
    model = _train_autoencoder(train_normal, val_normal)

    err_train = _per_channel_errors(model, X_train_s)
    err_val = _per_channel_errors(model, X_val_s)
    err_test = _per_channel_errors(model, X_test_s)

    print("training failure classifier")
    classifier = FailureClassifier()
    classifier.fit(err_train, y_train)
    validate_failure_modes(classifier.classes_)

    y_pred = classifier.predict_batch(err_test)
    test_accuracy = accuracy_score(y_test, y_pred)
    print(f"\ntest accuracy: {test_accuracy:.4f}")
    print(classification_report(y_test, y_pred, zero_division=0))

    if test_accuracy < ACCURACY_THRESHOLD:
        raise AssertionError(
            f"test accuracy {test_accuracy:.4f} < threshold {ACCURACY_THRESHOLD}"
        )

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), ARTIFACTS_DIR / "lstm_autoencoder.pt")
    with (ARTIFACTS_DIR / "failure_classifier.pkl").open("wb") as f:
        pickle.dump(classifier, f)
    with (ARTIFACTS_DIR / "scaler.pkl").open("wb") as f:
        pickle.dump(scaler, f)

    ref_max = float(np.quantile(err_train.mean(axis=1), 0.99))
    metadata = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "days": args.days,
        "window_size": WINDOW_SIZE,
        "n_channels": N_CHANNELS,
        "channels": METRIC_CHANNELS,
        "test_accuracy": test_accuracy,
        "anomaly_score_ref_max": ref_max,
        "duration_seconds": round(time.time() - started, 2),
    }
    (ARTIFACTS_DIR / "model_metadata.json").write_text(
        json.dumps(metadata, indent=2)
    )
    print(f"\nartifacts saved to {ARTIFACTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
