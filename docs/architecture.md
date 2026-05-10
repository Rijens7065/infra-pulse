# CloudSentro — Architecture

> One-stop reference for what each component does, how they fit together,
> and what the data flow looks like under load.

---

## What CloudSentro is

An autonomous remediation system for Azure infrastructure: a PyTorch
anomaly model watches AKS metrics, a Claude agent reasons about every
flagged anomaly, and the system opens **real GitHub pull requests with
Terraform fixes**. A human approves the PR, HCP Cloud applies, the
infrastructure heals.

The whole thing runs for **~$37/month** on a single-node AKS cluster.

---

## Components

```
                                                     ┌───────────────────┐
                                                     │ Claude API        │
                                                     │ (sonnet-4)        │
                                                     └─────────▲─────────┘
                                                               │ tool_use loop
                                                               │
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │    ┌──────────────┐
   │ AKS pods +   │───▶│ ML pod       │───▶│ Agent pod    │────┘    │ HCP Cloud    │
   │ Azure Monitor│    │ (FastAPI :   │    │ (every 300s) │         │ Terraform    │
   └──────────────┘    │  /predict)   │    └──────┬───────┘         └──────▲───────┘
                       └──────┬───────┘           │                        │
                              │ Prometheus        │ if confidence > 0.75   │ apply
                              │                   │ + ¬SECURITY_DRIFT      │
                              ▼                   ▼                        │
                       ┌──────────────┐    ┌──────────────┐                │
                       │ Grafana      │    │ GitHub PR    │────────────────┘
                       │ (public)     │    │ (with Terra- │
                       └──────────────┘    │  form patch) │
                                           └──────────────┘
```

| Layer | Component | Azure service | Cost/mo |
|---|---|---|---|
| Compute | AKS cluster (1× D2s_v3) | Azure Kubernetes Service | ~$70 (on-demand) |
| Registry | Container images | Azure Container Registry (Basic) | ~$5 |
| Secrets | Claude API key, GitHub App PEM | Azure Key Vault | <$1 |
| Observability | Metrics, dashboards | Prometheus + Grafana on AKS | included |
| ML | Anomaly detection | PyTorch + scikit-learn (CPU) | included |
| Agent | Reasoning + remediation | Claude `claude-sonnet-4-20250514` | ~$6 |
| Audit | Action log | Azure Blob Storage | <$1 |
| DNS / TLS | Public surface | Cloudflare (free) | $0 |
| IaC | Infrastructure as code | HCP Cloud (free tier) | $0 |
| **Total** | | | **~$37–80** depending on AKS uptime |

---

## Security model

- **Zero static credentials in CI.** GitHub Actions and HCP Cloud both
  authenticate to Azure via OIDC federated credentials. No client secrets,
  no service-account keys.
- **Two distinct Azure principals** for the two trust domains:
  - GitHub Actions identity → AcrPush (image push only)
  - HCP Cloud identity → broader role (Terraform-managed scope)
- **Pod identities** are isolated. ML and agent pods run as non-root
  (uid 1000), read-only root filesystem, drop ALL Linux capabilities,
  use seccomp `RuntimeDefault`. Workload Identity Federation is the
  intended path for production (each pod gets its own SP); for the demo,
  the agent reads its API keys from a Kubernetes secret.
- **Secrets only live in Azure Key Vault.** RBAC mode, soft-delete on,
  purge-protection on.
- **Agent hard rules**, enforced both by prompt and by `_validate_plan`
  in `agent/tools.py`:
  - Never opens a PR for `SECURITY_DRIFT` anomalies
  - Never touches `infra/modules/budget/` or `infra/modules/identity/`
  - Never writes outside `infra/`
  - Confidence must exceed `0.75` before any PR is opened
  - Loop is hard-capped at 10 tool turns

---

## ML model

Trained from synthetic 30-day, 7-channel AKS metrics with 8–15 labeled
anomaly windows (one per non-NORMAL class).

```
input  (60 minutes × 7 channels)
   │
   ▼
LSTM autoencoder
   encoder:  LSTM(7 → 64) → LSTM(64 → 32)
   decoder:  repeat → LSTM(32 → 64) → LSTM(64 → 7) → Linear
   loss:     MSE on the last 10 timesteps (the anomaly score)
   │
   ▼
Per-channel reconstruction error
   │
   ▼
IsolationForest gate           ← contamination = 0.15
   │   if anomalous
   ▼
RandomForestClassifier         ← n_estimators = 100
   │
   ▼
AnomalySignal {
   anomaly_score: 0.0–1.0,
   failure_mode: NORMAL | OOM_LEAK | CPU_THROTTLE
                 | NETWORK_DEGRADATION | COST_SPIKE | SECURITY_DRIFT,
   confidence:   0.0–1.0,
   time_to_impact_minutes,
   affected_metrics,
   explanation
}
```

Test accuracy on the held-out 15% split: **0.99**. Inference < 200 ms.

---

## Agent capabilities

Seven typed tools, defined in [agent/tools.py](../agent/tools.py):

| Tool | What it does |
|---|---|
| `get_current_anomaly_signal` | GET ml-service:8000/predict |
| `get_azure_monitor_metrics` | Read AKS metrics for a recent window |
| `get_recent_infra_changes` | Last 10 commits touching `infra/` |
| `get_kubernetes_events` | Warning events in `cloudsentro` namespace |
| `read_terraform_file` | Read current Terraform file via GitHub API |
| `create_remediation_pr` | Open a PR with the proposed Terraform change |
| `log_audit_event` | Append a JSONL record to Azure Blob |

Every cycle ends with exactly one `log_audit_event` call. The audit log
is the system of record for every action — when humans review the PRs,
they can cross-reference the audit log to see what context the agent had
at the moment it decided to act.

---

## Data flow — what happens when an anomaly is injected

```
t=0    operator runs:
           bash scripts/demo.sh

t≈5s   /inject sets the ML pod's override flag
           {failure_mode=OOM_LEAK, intensity=0.95, duration=10m}

t≈30s  ML pod's /predict starts returning OOM_LEAK with score > 0.75

t≈300s agent's run_loop fires:
         1. get_current_anomaly_signal → OOM_LEAK / 0.92 / conf 0.88
         2. get_azure_monitor_metrics  → memory_rss climbing
         3. get_kubernetes_events      → no OOMKills yet
         4. get_recent_infra_changes   → last touch was 12 days ago
         5. read_terraform_file        → infra/modules/aks/main.tf
         6. create_remediation_pr      → PR #N opened
         7. log_audit_event            → audit/2026-MM-DD.jsonl

t≈320s GitHub PR appears with:
           ## Anomaly Report      ← failure mode, score, ML explanation
           ## Root Cause          ← agent's plain-English diagnosis
           ## Reasoning Chain     ← collapsible step-by-step
           ## Proposed Changes    ← Terraform diff
           ## Rollback Instructions

t=N    human approves the PR
           HCP Cloud auto-applies on merge
           infrastructure heals
```

---

## Deployment

```bash
# 1. Bring up base infra (Phase 1–4)
git push origin main          # triggers HCP Cloud apply via VCS

# 2. Build and push images
git push origin main          # triggers ml-build / agent-build via path filters

# 3. Deploy the pods
export ACR_LOGIN_SERVER=$(terraform output -raw acr_login_server)
export AKS_RESOURCE_ID=$(az aks show -g rg-cloudsentro-terraform -n cloudsentro-demo --query id -o tsv)
export ANTHROPIC_API_KEY=sk-ant-…
export GITHUB_APP_PEM_FILE=./github-app.pem
export GITHUB_REPO_OWNER=Rijens7065
export GITHUB_APP_ID=…
export GITHUB_INSTALLATION_ID=…

bash scripts/deploy.sh

# 4. Run the demo
bash scripts/demo.sh
```

---

## Repository layout

```
infra-pulse/
├── infra/                  Terraform (Phase 1 + 4)
│   └── modules/{resource_group,acr,aks,keyvault,budget,
│                ingress,prometheus,grafana,nsg,dns}/
├── ml/                     PyTorch anomaly model + FastAPI
│   ├── data/generator.py
│   ├── model/{lstm_autoencoder,failure_classifier}.py
│   ├── serving/app.py
│   ├── train.py
│   ├── k8s/
│   └── tests/              17 unit tests
├── agent/                  Claude reasoning agent
│   ├── agent.py            run_loop + FastAPI health
│   ├── tools.py            7 tools + dispatcher
│   ├── actions/github_app_auth.py
│   ├── k8s/
│   └── tests/              35 unit tests
├── dashboard/
│   ├── grafana/            cloudsentro-dashboard.json
│   └── static/             single-file landing page
├── scripts/
│   ├── inject_anomaly.py
│   ├── deploy.sh
│   └── demo.sh
├── tests/e2e/test_pipeline.py
└── .github/workflows/
    ├── tf-plan.yml
    ├── tf-apply.yml         polls HCP Cloud for the real apply outcome
    ├── ml-build.yml
    └── agent-build.yml      both with Trivy scans
```
