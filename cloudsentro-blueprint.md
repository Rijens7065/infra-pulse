# CloudSentro — Project Blueprint

> Autonomous Infrastructure Intelligence Platform  
> Built on Azure · Terraform HCP · GitHub Actions · Claude AI · AKS

---

## Project Constants

```
PROJECT          = cloudsentro
DOMAIN           = cloudsentro.com
PUBLIC_URL       = demo.cloudsentro.com
AZURE_REGION     = westeurope
AKS_VM_SIZE      = Standard_B2s (Spot)
BUDGET_LIMIT     = $50/month
TF_ORG           = cloudsentro
TF_WORKSPACE     = cloudsentro-prod
```

---

## Stack

| Layer | Technology |
|---|---|
| IaC | Terraform + HCP Cloud (remote runs) |
| CI/CD | GitHub Actions |
| Containers | Docker → ACR → AKS |
| ML | PyTorch LSTM + scikit-learn (CPU-only) |
| Agent | Claude claude-sonnet-4-20250514 (tool_use) |
| Auth | AKS Workload Identity Federation (zero secrets) |
| DNS | Cloudflare (proxied, free TLS) |
| Dashboard | Grafana + Prometheus on AKS |

---

## Repo Structure

```
cloudsentro/
├── infra/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── providers.tf
│   └── modules/
│       ├── aks/
│       ├── acr/
│       ├── keyvault/
│       ├── budget/
│       ├── identity/
│       ├── ingress/
│       ├── prometheus/
│       ├── grafana/
│       ├── nsg/
│       └── dns/
├── ml/
│   ├── data/generator.py
│   ├── model/lstm_autoencoder.py
│   ├── model/failure_classifier.py
│   ├── serving/app.py
│   ├── serving/azure_monitor_client.py
│   ├── k8s/
│   ├── train.py
│   ├── Dockerfile
│   └── requirements.txt
├── agent/
│   ├── agent.py
│   ├── tools.py
│   ├── prompts.py
│   ├── models.py
│   ├── actions/github_app_auth.py
│   ├── k8s/
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/
│   ├── grafana/cloudsentro-dashboard.json
│   └── static/index.html
├── scripts/
│   ├── inject_anomaly.py
│   └── demo.sh
├── tests/e2e/
├── docs/
├── .github/workflows/
├── .gitignore
├── .env.example
└── README.md
```

---

## Security Model (apply to every phase)

- **No secrets in code or env vars** — all credentials via AKS Workload Identity Federation
- **Two App Registrations** — one for ML pod, one for Agent pod, each with federated credentials
- RBAC: ML pod → `Monitoring Reader`. Agent pod → `Monitoring Reader` + `AKS Cluster User` + `Key Vault Secrets User`
- Only secret in the system: Claude API key + GitHub App private key → stored in Key Vault, read at runtime
- Cloudflare proxies all traffic — AKS public IP shielded by NSG (Cloudflare IP ranges only)
- All container pods: `runAsNonRoot`, `readOnlyRootFilesystem`, `capabilities.drop=ALL`

---

## Phase 1 — Foundation

**Goal:** `git push → terraform plan in HCP → you approve → Azure deploys`

### Terraform modules to create

**`modules/resource_group/`**
- `azurerm_resource_group` named `rg-cloudsentro-demo`

**`modules/acr/`**
- Basic SKU, `admin_enabled = false`, random 4-char suffix on name

**`modules/aks/`**
- 1 node pool, `Standard_B2s`, Spot (`priority=Spot, eviction=Delete`)
- `node_count=1`, autoscaler `min=1 max=2`
- `oidc_issuer_enabled = true`, `workload_identity_enabled = true`
- `network_plugin = kubenet`, `sku_tier = Free`
- Output: `cluster_name`, `kube_config`, `oidc_issuer_url`

**`modules/keyvault/`**
- Standard SKU, `soft_delete_retention_days=7`, `purge_protection_enabled=true`
- `enable_rbac_authorization = true`, random 4-char suffix

**`modules/budget/`**
- `amount=50`, `time_grain=Monthly`
- Alert at 70% (warning) and 90% (critical) → `var.alert_email`

**`modules/identity/`**
- Two `azuread_application` + `azuread_service_principal` pairs: `cloudsentro-ml-sp` and `cloudsentro-agent-sp`
- Federated credential for each: `issuer = aks.oidc_issuer_url`, subjects:
  - ML: `system:serviceaccount:cloudsentro:ml-service-account`
  - Agent: `system:serviceaccount:cloudsentro:agent-service-account`
- RBAC assignments per security model above

**`infra/providers.tf`**
- `azurerm ~>3.0`, `azuread ~>2.0`, `cloudflare ~>4.0`, `helm`, `kubernetes`
- Backend: HCP Cloud remote, org=`cloudsentro`, workspace=`cloudsentro-prod`

**`infra/variables.tf`**
- `location`, `environment`, `project`, `alert_email`, `admin_ip`
- `cloudflare_zone_id` (sensitive), `cloudflare_api_token` (sensitive)

**`infra/main.tf`** — call all modules in dependency order

**`infra/outputs.tf`** — `acr_login_server`, `aks_cluster_name`, `aks_oidc_issuer_url`, `key_vault_uri`, `ml_sp_client_id`, `agent_sp_client_id`

### GitHub Actions workflows

**`tf-plan.yml`** — triggers on push to `main` and PRs
1. Checkout → setup-terraform (HCP token) → `terraform init` → `fmt -check` → `validate` → `plan`
2. Post plan output as PR comment via `actions/github-script`
3. Env: `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID` from secrets

**`tf-apply.yml`** — `workflow_dispatch` only (HCP Cloud executes actual apply)

**`ml-build.yml`** — triggers on `ml/**` changes
1. Checkout → `azure/login` (OIDC, no client secret) → ACR login → `docker build` + push `:$GITHUB_SHA` and `:latest`

**`agent-build.yml`** — same as `ml-build.yml` for `agent/**`

### Root files
- `.gitignore` — Terraform (`.terraform/`, `*.tfstate`, `*.tfvars`), Python, Docker, `.env*`, `*.pem`, `*.key`
- `.env.example` — `ARM_SUBSCRIPTION_ID`, `ARM_TENANT_ID`, `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `TF_VAR_cloudflare_zone_id`, `TF_VAR_cloudflare_api_token`, `TF_VAR_alert_email`, `TF_VAR_admin_ip`, `TERRAFORM_CLOUD_TOKEN`
- `README.md` — placeholder with phase progress checklist

### Phase 1 done when
- `terraform validate` passes
- `git push` triggers HCP plan and posts diff as PR comment
- Approve in HCP UI → Resource Group, ACR, AKS, Key Vault provisioned in Azure

---

## Phase 2 — ML Model

**Goal:** Trained anomaly model running locally, Docker image builds successfully

### Failure modes (6 classes)

| Class | Signal Pattern |
|---|---|
| `NORMAL` | Healthy baseline ~80% of data |
| `OOM_LEAK` | Memory RSS grows linearly toward pod limit over 2–8 hours |
| `CPU_THROTTLE` | CPU jumps to 95–100% instantly, latency multiplies 3–5x |
| `NETWORK_DEGRADATION` | Throughput drops 60–80%, latency +200–400% |
| `COST_SPIKE` | Azure spend exceeds 7-day rolling average by >40% |
| `SECURITY_DRIFT` | Abnormal API call volume, new outbound IPs |

### `ml/data/generator.py`
- 30 days at 1-min intervals (43,200 rows), 7 channels: `cpu_usage_percent`, `memory_rss_bytes`, `pod_restart_count`, `http_p99_latency_ms`, `network_bytes_in`, `network_bytes_out`, `azure_cost_per_hour_usd`
- Diurnal baseline (peak 09:00–18:00 UTC) + gaussian noise
- Inject 8–15 anomaly windows with realistic patterns per class
- Save: `synthetic_metrics.parquet`, `synthetic_labels.parquet`, `generator_report.txt`
- Accept `--seed` arg (default 42)

### `ml/model/lstm_autoencoder.py` (PyTorch)
- Input: `(batch, 60, 7)` — 60-min sliding window
- Encoder: `LSTM(7→64)` → `LSTM(64→32)` → latent vector
- Decoder: repeat latent 60× → `LSTM(32→64)` → `LSTM(64→7)` → `Linear(7,7)`
- Loss: MSE reconstruction. Anomaly score = mean reconstruction error on last 10 timesteps
- Train on NORMAL windows only

### `ml/model/failure_classifier.py`
- Stage 1: `IsolationForest` on per-channel reconstruction error → binary normal/anomalous
- Stage 2: `RandomForestClassifier(n_estimators=100)` → 6-class failure mode
- Output dataclass `AnomalySignal`: `anomaly_score`, `failure_mode`, `confidence`, `time_to_impact_minutes` (Optional), `affected_metrics`, `explanation` (1 sentence)

### `ml/train.py`
- 70/15/15 train/val/test split stratified by class
- Fit `StandardScaler` on normal training windows
- Train autoencoder (Adam lr=1e-3, batch=64, early stopping patience=5)
- Train classifier on all classes
- **Assert test accuracy > 0.85** — raise if not
- Save to `ml/model/artifacts/`: `lstm_autoencoder.pt`, `failure_classifier.pkl`, `scaler.pkl`, `model_metadata.json`

### `ml/serving/app.py` (FastAPI, port 8000)
- `GET /health` → `{status, model_version, uptime_seconds}`
- `POST /predict` → body `{metrics: [[...60×7...]]}` → `AnomalySignal` JSON, target <200ms
- `GET /metrics` → Prometheus: `cloudsentro_anomaly_score`, `cloudsentro_predictions_total{failure_mode}`, `cloudsentro_prediction_duration_seconds`
- `POST /inject` → `{failure_mode, intensity, duration_minutes}` — only active if `DEMO_MODE=true`

### `ml/serving/azure_monitor_client.py`
- `DefaultAzureCredential`, polls Azure Monitor every 60s
- AKS resource from env `AZURE_AKS_RESOURCE_ID`
- Backfills last 60 min on startup, maintains rolling deque
- Exponential backoff on API errors

### `ml/k8s/`
- `serviceaccount.yaml` — annotation `azure.workload.identity/client-id: PLACEHOLDER`
- `deployment.yaml` — 1 replica, requests `256Mi/100m`, limits `512Mi/500m`, security context (non-root, read-only fs, drop ALL caps), label `azure.workload.identity/use: "true"`, liveness probe `GET /health`
- `service.yaml` — ClusterIP port 8000

### `ml/Dockerfile`
- Multi-stage, `python:3.11-slim`, non-root uid=1000
- CPU-only PyTorch (`torch==2.1.0+cpu`)
- Bake model artifacts into image
- `CMD: uvicorn ml.serving.app:app --host 0.0.0.0 --port 8000`

### `ml/requirements.txt` (pin all versions)
`torch==2.1.0+cpu`, `scikit-learn`, `fastapi`, `uvicorn`, `pandas`, `pyarrow`, `prometheus-client`, `azure-monitor-query`, `azure-identity`, `numpy`, `scipy`

### Phase 2 done when
- `python ml/train.py` prints classification report with accuracy >85%
- `pytest ml/tests/ -v` all green
- `docker build -t cloudsentro-ml:local -f ml/Dockerfile .` succeeds

---

## Phase 3 — Claude Agent

**Goal:** Agent pod polls ML model, reasons with Claude, opens real GitHub PR with Terraform fix

### `agent/models.py` (Pydantic v2)
- `TerraformChange` — `file_path`, `original_content`, `new_content`, `explanation`
- `RemediationPlan` — `anomaly` (dict), `root_cause_summary`, `confidence`, `terraform_changes`, `reasoning_chain`, `rollback_instructions`
- `AgentAction` — `action_id` (uuid4), `created_at`, `anomaly_score`, `failure_mode`, `confidence`, `action_taken`, `pr_url` (Optional)

### `agent/tools.py` — 7 tools for Claude `tool_use`

| Tool | What it does |
|---|---|
| `get_current_anomaly_signal` | GET ml-service:8000/predict |
| `get_azure_monitor_metrics` | Last N hours via azure-monitor-query |
| `get_recent_infra_changes` | Last 10 commits to `infra/` on GitHub |
| `get_kubernetes_events` | Warning events in `cloudsentro` namespace |
| `read_terraform_file` | GitHub contents API, returns file + sha |
| `create_remediation_pr` | Opens real PR — only if confidence >0.75 |
| `log_audit_event` | Appends to Azure Blob `agent-audit-log/audit/YYYY-MM-DD.jsonl` |

**PR format** (markdown body):
```
## Anomaly Report    ## Root Cause    ## Reasoning Chain (collapsible)
## Proposed Changes  ## Rollback Instructions
Footer: Generated by CloudSentro Agent · [View Dashboard](https://demo.cloudsentro.com)
```
Branch name: `fix/agent-{YYYYMMDD-HHmm}-{failure_mode}`
Labels: `agent-remediation`, `terraform`, `{failure_mode}`

### `agent/prompts.py`
System prompt must enforce:
- Always call `get_current_anomaly_signal` first, then gather context before concluding
- Reason step-by-step in plain English
- **Hard constraints:** never delete resources, never modify RBAC/IAM, never touch budget module
- `SECURITY_DRIFT` → log only, never open PR
- Only call `create_remediation_pr` if confidence >0.75
- Always read current file before proposing changes to it
- Final output: JSON block matching `RemediationPlan`

### `agent/agent.py`
- Load Claude API key from Key Vault via `DefaultAzureCredential` on startup
- `run_once()`: call Claude with all 7 tools, agentic loop max 10 turns, parse `RemediationPlan`, open PR if confidence >0.75 and not SECURITY_DRIFT, always log audit event
- `run_loop()`: `run_once()` every 300s, catch all exceptions, exponential backoff max 10 min
- FastAPI health endpoint port 8001: `GET /health`

### `agent/actions/github_app_auth.py`
- GitHub App auth (not PAT) — load private key from Key Vault
- Generate JWT (RS256, exp 10 min) → exchange for installation token (1 hour)
- Cache with auto-refresh 5 min before expiry

### `agent/k8s/`
- `namespace.yaml`, `serviceaccount.yaml` (workload identity annotation), `configmap.yaml` (all non-secret env vars as PLACEHOLDERs), `deployment.yaml` (requests `128Mi/100m`, limits `256Mi/500m`, security context same as ML pod), `service.yaml` ClusterIP port 8001

### `agent/requirements.txt`
`anthropic==0.28.0`, `fastapi`, `uvicorn`, `azure-identity`, `azure-keyvault-secrets`, `azure-storage-blob`, `kubernetes==28.1.0`, `PyGithub==2.1.1`, `pydantic==2.5.2`, `cryptography`, `PyJWT`, `httpx`

### Phase 3 done when
- `pytest agent/tests/ -v` all green (all tests use mocks, no real API calls)
- `docker build -t cloudsentro-agent:local -f agent/Dockerfile .` succeeds
- Sample PR body for OOM_LEAK renders all 5 required sections

---

## Phase 4 — Dashboard

**Goal:** `https://demo.cloudsentro.com` shows live Grafana with anomaly scores

### `infra/modules/ingress/`
- `helm_release` ingress-nginx v4.8.3, `LoadBalancer` service
- `use-forwarded-headers=true`, `compute-full-forwarded-for=true` (Cloudflare)
- `null_resource` waits until public IP is assigned (Azure LB takes 2–3 min)
- Output: `ingress_public_ip`

### `infra/modules/prometheus/`
- `helm_release` prometheus v25.8.0 (NOT kube-prometheus-stack — too heavy)
- Persistence: 2Gi, retention: 7d, requests `128Mi/100m`
- Scrape: `ml-service:8000/metrics` every 15s, `agent-service:8001/metrics` every 30s

### `infra/modules/grafana/`
- Generate random admin password → Key Vault → K8s secret
- `helm_release` grafana v7.0.19
- `grafana.ini`: `root_url=https://demo.cloudsentro.com/grafana`, `auth.anonymous.enabled=true`, `org_role=Viewer`, `allow_embedding=true`
- Provisioned datasources: Prometheus (default) + Azure Monitor (MSI auth)
- Ingress: nginx class, rewrite target, path `/grafana(/|$)(.*)`
- Mount `dashboard/grafana/cloudsentro-dashboard.json` as ConfigMap

### `dashboard/grafana/cloudsentro-dashboard.json`
4 rows, dark theme, 30s refresh, `now-6h` default:
- **Row 1 Live Anomaly:** Stat (anomaly_score, colour thresholds), Stat (failure_mode), Time series (score 24h)
- **Row 2 AKS Health:** Time series (CPU, memory), Stat (time_to_impact)
- **Row 3 Agent Activity:** Stats (total predictions, anomalous count), histogram (latency)
- **Row 4 Cost:** Time series (cost/hr 7d), Stat (est. monthly), Gauge (budget %)

### `infra/modules/nsg/`
NSG on AKS subnet — allow inbound 80/443 from Cloudflare IPv4 ranges only + `var.admin_ip`. Deny all other.
Cloudflare ranges: `173.245.48.0/20, 103.21.244.0/22, 103.22.200.0/22, 103.31.4.0/22, 141.101.64.0/18, 108.162.192.0/18, 190.93.240.0/20, 188.114.96.0/20, 197.234.240.0/22, 198.41.128.0/17, 162.158.0.0/15, 104.16.0.0/13, 104.24.0.0/14, 172.64.0.0/13, 131.0.72.0/22`

### `infra/modules/dns/`
- `cloudflare_record` demo → type A, `ingress_public_ip`, proxied
- `cloudflare_record` www → CNAME, proxied
- `page_rule` bypass cache for `/grafana/*`

### `dashboard/static/index.html`
- Single file, no frameworks, no CDN, under 20KB
- CSS `prefers-color-scheme` dark/light
- Hero, CTA → `https://demo.cloudsentro.com/grafana`, 3 feature cards, tech stack bar, footer
- `_redirects` file for Cloudflare Pages

### Update `infra/main.tf`
Add: `module ingress` → `module prometheus` → `module grafana` → `module nsg` → `module dns`

### Phase 4 done when
- `terraform plan` shows expected resources
- `https://demo.cloudsentro.com` loads the landing page
- `https://demo.cloudsentro.com/grafana` loads Grafana (anonymous read-only)
- Grafana shows live anomaly_score metric from ML pod

---

## Phase 5 — Integration & Demo

**Goal:** Reproducible 5-min demo, security hardened, LinkedIn-ready deliverables

### `scripts/inject_anomaly.py`
```
python scripts/inject_anomaly.py --mode OOM_LEAK --intensity high --duration 20
```
- `--mode`: `OOM_LEAK|CPU_THROTTLE|NETWORK_DEGRADATION|COST_SPIKE|SECURITY_DRIFT`
- `--intensity`: `low` (~0.75) | `medium` (~0.85) | `high` (~0.95)
- Calls ML pod `POST /inject` via kubectl port-forward or in-cluster DNS
- Auto-cleanup after `--duration` minutes
- Prints watch URL on injection

### `scripts/demo.sh`
5-step scripted demo using tput colours + Enter-to-continue pauses:
1. Verify dashboard accessible, open browser
2. Inject OOM_LEAK high intensity
3. Poll ML `/predict` every 10s, print score, bold green when >0.70 + elapsed time
4. Poll GitHub every 15s for `agent-remediation` PR, print URL + open browser
5. Print summary table: injection→detection, detection→PR (seconds), peak score, confidence

### `tests/e2e/test_pipeline.py`
5 sequential integration tests (require deployed cluster):
- `test_01` — all services healthy (Grafana 200, ML /health, agent /health)
- `test_02` — baseline anomaly_score <0.5, failure_mode=NORMAL
- `test_03` — inject OOM_LEAK, assert score >0.70 within 3 min (parametrize with CPU_THROTTLE too)
- `test_04` — agent opens PR within 8 min, PR body has all 5 sections
- `test_05` — audit log JSONL exists in Blob with correct entry

### Security hardening
Add to both pod `deployment.yaml`:
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  seccompProfile:
    type: RuntimeDefault
volumes:
  - name: tmp
    emptyDir: {}
volumeMounts:
  - name: tmp
    mountPath: /tmp
```

Add Trivy scan to both build workflows (after build, before push):
```yaml
- uses: aquasecurity/trivy-action@master
  with:
    image-ref: ${{ env.IMAGE }}
    severity: CRITICAL,HIGH
    exit-code: 1
    ignore-unfixed: true
```

Add to `infra/modules/aks/main.tf`: `azure_policy_enabled=true`, `microsoft_defender` block
Add to `infra/modules/keyvault/main.tf`: `network_acls` deny all except AzureServices + AKS subnet

### `docs/architecture.md`
Sections: What is CloudSentro, ASCII architecture diagram, component table (name|role|Azure service|cost), security model, ML model, agent capabilities, data flow (numbered steps), setup guide, demo instructions

### Final `README.md`
- One compelling opening sentence
- Shields.io badges (Terraform, Azure, Python, Claude AI, MIT)
- Live demo link → `https://demo.cloudsentro.com`
- "How it works" — 5 numbered steps, one sentence each
- "What makes this different" — 4 bullets
- Tech stack table
- Quick start (3 commands)

### `docs/linkedin-post.md`
- 500–700 words
- Hook: infra failure at 2am
- 3-layer explanation in plain English
- Specific tech choices + why
- Human approval gate mentioned
- Live demo link
- 3 closing questions
- Hashtags: `#MLOps #AzureCloud #DevOps #AIEngineering #Terraform #GitOps #CloudNative #LLM`

### Phase 5 done when
- `pytest tests/e2e/ -v` all green
- `bash scripts/demo.sh` completes under 6 minutes
- LinkedIn post and final README written

---

## How to use this blueprint with Claude Code

Open VS Code in the empty repo root. Tell Claude Code:

> "I have a project blueprint at `cloudsentro-blueprint.md`. Read it fully, then execute **Phase 1 only**. Do not proceed to Phase 2. When done, tell me what GitHub secrets and HCP Cloud variables I need to set."

After each phase is complete and tested, tell it:

> "Phase N is done. Now execute **Phase N+1** from the blueprint."

---

## Budget summary

| Service | Cost/mo |
|---|---|
| AKS (1× B2s Spot) | ~$10 |
| ACR Basic | ~$5 |
| Grafana (essential) | ~$9 |
| Azure Blob Storage | ~$2 |
| Claude API (~500 agent calls) | ~$6 |
| NGINX Load Balancer + DNS | ~$5 |
| **Total** | **~$37** |
| Budget alert | $35 warn · $45 hard |
