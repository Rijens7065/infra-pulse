# ml/ — ML Model Context

> Read this before touching any file in ml/

## What this module does
Trains and serves an anomaly detection model on Azure Kubernetes metrics.
Runs as a pod in AKS namespace `cloudsentro`, service name `ml-service`.
Polls Azure Monitor every 60 seconds and exposes predictions via FastAPI.

## Critical rules
- PyTorch must be CPU-only: `torch==2.1.0+cpu` — no GPU on Standard_B2s
- Model size must stay under 100MB
- Inference must complete in under 200ms
- Training accuracy must exceed 85% or train.py raises AssertionError
- Never store Azure credentials in code — use DefaultAzureCredential
- DEMO_MODE env var must be true for /inject endpoint to work

## The 6 failure classes (never change these names)
```
NORMAL              healthy baseline ~80% of data
OOM_LEAK            memory RSS grows linearly toward pod limit
CPU_THROTTLE        CPU jumps to 95-100%, latency multiplies 3-5x
NETWORK_DEGRADATION throughput drops 60-80%, latency +200-400%
COST_SPIKE          spend exceeds 7-day rolling average by >40%
SECURITY_DRIFT      abnormal API patterns, new outbound IPs
```

## AnomalySignal output contract
This is what the agent expects. Never change field names.
```python
@dataclass
class AnomalySignal:
    anomaly_score: float          # 0.0-1.0
    failure_mode: str             # one of 6 class names above
    confidence: float             # 0.0-1.0
    time_to_impact_minutes: Optional[int]
    affected_metrics: List[str]
    explanation: str              # 1 sentence
```

## API endpoints
```
GET  /health    → {status, model_version, uptime_seconds}
POST /predict   → AnomalySignal JSON (input: 60×7 float array)
GET  /metrics   → Prometheus format
POST /inject    → demo anomaly injection (DEMO_MODE=true only)
```

## Prometheus metrics exposed
```
cloudsentra_anomaly_score              gauge
cloudsentra_predictions_total{mode}   counter
cloudsentra_prediction_duration_seconds histogram
```

## 7 metric channels (exact order matters)
```
index 0: cpu_usage_percent
index 1: memory_rss_bytes
index 2: pod_restart_count
index 3: http_p99_latency_ms
index 4: network_bytes_in
index 5: network_bytes_out
index 6: azure_cost_per_hour_usd
```

## Files in this module
```
ml/
├── data/
│   ├── generator.py          ← synthetic data generation
│   ├── synthetic_metrics.parquet    ← generated (gitignored)
│   └── synthetic_labels.parquet     ← generated (gitignored)
├── model/
│   ├── lstm_autoencoder.py   ← PyTorch LSTM autoencoder
│   ├── failure_classifier.py ← IsolationForest + RandomForest
│   └── artifacts/            ← saved models (gitignored)
│       ├── lstm_autoencoder.pt
│       ├── failure_classifier.pkl
│       ├── scaler.pkl
│       └── model_metadata.json
├── serving/
│   ├── app.py                ← FastAPI inference server
│   └── azure_monitor_client.py ← polls Azure Monitor
├── k8s/
│   ├── serviceaccount.yaml
│   ├── deployment.yaml
│   └── service.yaml
├── tests/
│   ├── test_generator.py
│   ├── test_model.py
│   └── test_api.py
├── train.py                  ← training script
├── Dockerfile                ← multi-stage, CPU-only
└── requirements.txt          ← pinned versions
```

## Kubernetes identity
```
ServiceAccount: ml-service-account
Namespace: cloudsentro
Annotation: azure.workload.identity/client-id: <terraform output ml_sp_client_id>
Label on pod: azure.workload.identity/use: "true"
RBAC: Monitoring Reader on rg-cloudsentro-terraform
```

## What NOT to touch
- Never change the AnomalySignal field names — agent depends on them
- Never change metric channel order — model weights depend on it
- Never use GPU libraries — no GPU available
- Never commit model artifacts — they are gitignored
- Never hardcode Azure resource IDs — use AZURE_AKS_RESOURCE_ID env var
