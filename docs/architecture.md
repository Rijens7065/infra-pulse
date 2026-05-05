# Architecture Overview

## System in one sentence
An ML model detects Azure infrastructure anomalies → Claude reasons about root cause → a Terraform PR fixes it → GitOps deploys the fix.

## Data flow
```
Azure Monitor metrics (every 60s)
        ↓
ML Pod (LSTM + Isolation Forest)
        ↓ AnomalySignal {score, failure_mode, confidence, time_to_impact}
Agent Pod (Claude claude-sonnet-4-20250514)
        ↓ tool calls: Azure Monitor, kubectl, GitHub API
GitHub PR (Terraform fix + reasoning chain)
        ↓ human approves
HCP Cloud terraform apply
        ↓
Azure infrastructure healed
```

## Component map
```
infra/          → Terraform modules (provisions everything below)
ml/             → Anomaly detection model + FastAPI serving
agent/          → Claude reasoning engine + GitHub PR creation
dashboard/      → Grafana + static landing page
scripts/        → Demo and injection tools
tests/e2e/      → Integration tests
.github/        → CI/CD workflows
```

## Inter-module contracts

| From | To | Interface |
|---|---|---|
| Azure Monitor | ML pod | REST API polling (azure-monitor-query) |
| ML pod | Agent pod | HTTP POST /predict → AnomalySignal JSON |
| Agent pod | Azure Monitor | Tool call via azure-monitor-query |
| Agent pod | GitHub | Tool call via PyGithub (GitHub App auth) |
| Agent pod | Key Vault | DefaultAzureCredential at startup |
| Agent pod | Blob Storage | Audit log append (JSONL) |
| Grafana | Prometheus | Scrape /metrics endpoints |
| Prometheus | ML pod | Scrape http://ml-service:8000/metrics |
| Prometheus | Agent pod | Scrape http://agent-service:8001/metrics |
| Cloudflare | AKS Ingress | DNS A record → Load Balancer IP |

## Kubernetes namespace
All pods run in namespace: `cloudsentro`

## Service endpoints (internal)
```
ml-service.cloudsentro.svc.cluster.local:8000      → ML inference
agent-service.cloudsentro.svc.cluster.local:8001   → Agent health
prometheus-server.cloudsentro:80                   → Metrics
```

## External endpoints
```
https://infra-pulse.cloudsentro.com          → Cloudflare → NGINX → Grafana
https://infra-pulse.cloudsentro.com/grafana  → Live dashboard
```

## Authentication flow
```
GitHub Actions → OIDC → mi-cloudsentro-terraform → builds infra
ML pod         → AKS Workload Identity → Azure Monitor API
Agent pod      → AKS Workload Identity → Key Vault, Blob, Monitor
Agent pod      → GitHub App JWT        → GitHub API
```

## Port map
```
ML pod:    8000 (FastAPI inference + /metrics)
Agent pod: 8001 (health check + /metrics)
Grafana:   3000 (internal, exposed via ingress)
Prometheus:9090 (internal only)
```
