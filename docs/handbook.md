# CloudSentro Handbook

> The complete, as-built guide to what this project is, how each piece works,
> and how they collaborate. Read top-to-bottom for the full picture, or jump
> to the [Component Reference](#component-reference) if you already know what
> you're looking for.

---

## Table of contents

1. [What CloudSentro is](#1-what-cloudsentro-is)
2. [The story in plain English](#2-the-story-in-plain-english)
3. [Architecture at a glance](#3-architecture-at-a-glance)
4. [Component reference](#4-component-reference)
5. [How the pieces collaborate](#5-how-the-pieces-collaborate)
6. [Data flow during an incident](#6-data-flow-during-an-incident)
7. [Security model](#7-security-model)
8. [GitOps pipeline](#8-gitops-pipeline)
9. [Running the demo](#9-running-the-demo)
10. [Operations runbook](#10-operations-runbook)
11. [Cost breakdown](#11-cost-breakdown)
12. [Glossary](#12-glossary)

---

## 1. What CloudSentro is

CloudSentro is an **autonomous infrastructure remediation system** running on
Azure Kubernetes Service. It does three things on its own:

1. **Detect** — a PyTorch LSTM autoencoder watches Kubernetes metrics every
   minute and classifies anomalies into one of six failure modes.
2. **Reason** — when confidence exceeds 75%, a Claude `claude-sonnet-4-20250514`
   agent runs a tool-use loop to investigate the anomaly: pulls Azure Monitor
   metrics, lists Kubernetes events, reads the relevant Terraform file, and
   builds a step-by-step reasoning chain.
3. **Fix** — the agent opens a real GitHub pull request containing a Terraform
   change, rollback instructions, and the full reasoning chain. A human
   approves the PR. HCP Cloud auto-applies on merge. The infrastructure heals.

The whole stack runs on a single-node AKS cluster for **~$37/month**, uses
**zero static credentials** anywhere in CI or pods, and the agent is bound by
**six hard rules** enforced in both the system prompt and code:

- Never delete resources
- Never modify IAM/RBAC
- Never touch `infra/modules/budget/` or `infra/modules/identity/`
- Never write outside `infra/`
- Open a PR only if confidence > 0.75
- For `SECURITY_DRIFT` anomalies, log only — never open a PR

---

## 2. The story in plain English

It's 2:47 AM. A pod in production is leaking memory. The runbook says:
ssh in, read logs, write a Terraform patch, get a review, deploy. Forty
minutes from page to fix on a good day.

CloudSentro does steps 1-4 by itself and only wakes you up so you can click
"Approve" on a pull request that already has the diff, the diagnosis, and the
rollback plan written for you.

The key insight is that this isn't a "give Claude a prompt and let it write
infrastructure" project. There are three layers that each do something
different:

- An **ML model** that converts noisy raw metrics into a clean, structured
  `AnomalySignal` with a confidence score and a labeled failure mode. This is
  cheaper, faster, and more accurate than asking an LLM to classify metrics
  from scratch.
- An **agent** that takes the structured signal and does deep investigation
  using typed tool calls — reads the actual Terraform file before proposing
  changes, looks at recent commits, queries Kubernetes events, etc.
- A **human-in-the-loop GitOps gate** that ensures nothing ever applies to
  infrastructure without a human review. The agent proposes; the human
  approves; HCP Cloud applies.

---

## 3. Architecture at a glance

```
                                                  ┌─────────────────────┐
                                                  │   Anthropic API     │
                                                  │   (Claude sonnet-4) │
                                                  └──────────▲──────────┘
                                                             │ tool_use loop
                                                             │ max 10 turns
   ┌──────────────┐    ┌──────────────┐    ┌─────────────────┴─────────────────┐
   │ AKS metrics  │───▶│  ML pod      │───▶│            Agent pod              │
   │ + cAdvisor   │    │  /predict    │    │ run_loop every 300s               │
   └──────────────┘    │  /metrics    │    │  ↓ get_current_anomaly_signal     │    ┌─────────────────┐
                       │  /inject     │    │  ↓ get_azure_monitor_metrics      │───▶│  HCP Cloud      │
                       │  (DEMO_MODE) │    │  ↓ get_kubernetes_events          │    │  terraform apply│
                       └───────▲──────┘    │  ↓ get_recent_infra_changes       │    │  (VCS-triggered │
                               │           │  ↓ read_terraform_file            │    │   on merge)     │
            Prometheus scrape  │           │  ↓ create_remediation_pr ─────────┼───▶│                 │
                15s            │           │  ↓ log_audit_event                │    └─────────▲───────┘
                               │           └────────────────┬──────────────────┘              │
                               │                            │                                 │ approve
                               │                            ▼                                 │
                       ┌───────┴──────┐             ┌───────────────┐                ┌────────┴────────┐
                       │ Prometheus   │             │ GitHub PR     │───── review ──▶│  human          │
                       │  (server)    │             │ #N            │                │  reviewer       │
                       └───────▲──────┘             │ - Anomaly     │                └─────────────────┘
                               │                    │ - Root cause  │
                               │                    │ - Reasoning   │
                       ┌───────┴──────┐             │ - Diff        │
                       │ Grafana      │             │ - Rollback    │
                       │ /grafana     │             └──────▲────────┘
                       │ (anonymous   │                    │
                       │  Viewer)     │             ┌──────┴────────┐
                       └──────────────┘             │ Azure Blob    │
                                                    │ audit log     │
                                                    │ JSONL/day     │
                                                    └───────────────┘
```

---

## 4. Component reference

Each row is **what it is**, **where it runs**, **what it depends on**, and
**what depends on it**.

### 4.1 Terraform (HCP Cloud)

- **What:** The control plane for all Azure infrastructure. Defines AKS, ACR,
  Key Vault, ingress, Prometheus, Grafana, NSG, DNS, budget.
- **Where:** Runs remotely on HCP Cloud. State is encrypted there.
- **Trigger:** Push to `main` triggers VCS-integrated speculative plan, then
  auto-apply.
- **Auth:** OIDC federated credentials from HCP Cloud → Azure SP (`afa7467c-...`).
- **Files:** `infra/`, see [docs/architecture.md](architecture.md) for module
  list.

### 4.2 GitHub Actions

- **What:** CI for building images, validating Terraform plans, and reflecting
  HCP Cloud's apply outcome.
- **Workflows:**
  - `tf-plan.yml` — runs on PRs, posts the speculative plan as a comment.
    Uses `set -o pipefail` so the GitHub status reflects HCP Cloud's real exit
    code (not just whether `tee` succeeded).
  - `tf-apply.yml` — runs on merge to `main`. Polls HCP Cloud's API for the
    run on `commit_sha`, waits for terminal status, exits 0/1 accordingly.
  - `ml-build.yml` — on pushes touching `ml/**`. Builds, scans with Trivy
    (CRITICAL+HIGH fail), pushes to ACR.
  - `agent-build.yml` — same pattern for `agent/**`.
- **Auth:** OIDC federated credentials from GitHub Actions → Azure managed
  identity `mi-cloudsentro-terraform` (`f2ee2e29-...`).

### 4.3 Azure Container Registry (ACR)

- **What:** Private Docker registry. Stores `cloudsentro/ml:latest` and
  `cloudsentro/agent:latest`.
- **SKU:** Basic.
- **Push:** GitHub Actions pushes via `az acr login` (OIDC).
- **Pull:** AKS kubelet identity pulls (requires AcrPull role; attached via
  `az aks update --attach-acr` — should be in Terraform as follow-up).

### 4.4 Azure Kubernetes Service (AKS)

- **What:** The cluster that hosts everything that runs.
- **Node pool:** 1× `Standard_D2s_v3` (8GB RAM), autoscaling to max 2. The
  B-series we originally planned is not allowed in canadaeast for our
  subscription.
- **Features:** OIDC issuer enabled, workload identity enabled, kubenet
  networking, Free SKU control plane.
- **Namespaces:**
  - `cloudsentro` — ML and agent pods
  - `monitoring` — Prometheus, Grafana
  - `ingress-nginx` — NGINX ingress controller

### 4.5 Azure Key Vault

- **What:** Holds the only secrets in the system.
- **Secrets:**
  - `claude-api-key` — Anthropic API key (deferred to demo: provided via K8s
    secret instead, see [§4.10](#410-agent-pod))
  - `github-app-private-key` — GitHub App PEM
  - `grafana-admin-password` — auto-generated, written by Terraform
- **Auth:** RBAC mode. HCP Cloud's identity has `Key Vault Secrets Officer`
  (write). Pods would have `Key Vault Secrets User` (read) under workload
  identity, but in this demo the agent reads secrets from a K8s `Secret`
  instead.

### 4.6 ML pod (`ml-service`)

- **What:** PyTorch LSTM autoencoder + scikit-learn classifier, served by
  FastAPI on port 8000.
- **Endpoints:**
  - `GET  /health` — returns `{status, model_version, uptime_seconds}`
  - `POST /predict` — body `{metrics: [[...60×7...]]}`, returns AnomalySignal
  - `GET  /metrics` — Prometheus format (`cloudsentro_anomaly_score`,
    `cloudsentro_predictions_total{failure_mode}`,
    `cloudsentro_prediction_duration_seconds`)
  - `POST /inject` — DEMO_MODE-gated, overrides next response (see [§9](#9-running-the-demo))
- **Model training:** Happens inside the Docker build (stage 2). The image
  contains pre-trained artifacts; no training at runtime.
- **Security:** Non-root (uid 1000), read-only root filesystem, drops ALL
  Linux capabilities.

### 4.7 Prometheus

- **What:** Scrapes `ml-service:8000/metrics` every 15s and
  `agent-service:8001/metrics` every 30s. Plus the default kubernetes_pods job
  picks them up via `prometheus.io/scrape=true` annotation.
- **Retention:** 7 days, 2Gi persistent volume.
- **Where:** `monitoring` namespace. Service: `prometheus-server` on port 80.

### 4.8 Grafana

- **What:** Web UI for dashboards. Anonymous Viewer access enabled for the
  public demo.
- **Where:** `monitoring` namespace. Exposed at
  `https://infra-pulse.cloudsentro.com/grafana/` via the NGINX ingress.
- **Datasource:** Provisioned with explicit UID `prometheus` so dashboard
  JSON references resolve.
- **Dashboards:** Loaded via the **sidecar only** (no filesystem provider).
  The sidecar watches ConfigMaps with label `grafana_dashboard=1` in the
  `monitoring` namespace and uploads them to the "CloudSentro" folder.
- **Admin password:** Random, written to Key Vault on apply, mounted as a K8s
  Secret in the pod.

### 4.9 NGINX ingress

- **What:** Public entry point. Forwards `/grafana/*` to the Grafana service.
- **LoadBalancer:** Public IP from Azure standard LB (currently `40.86.213.249`).
- **Critical settings:**
  - `externalTrafficPolicy: Local` — flips the LB into Direct Server Return
    mode (`enableFloatingIp=true`). Without this, the cloud-controller creates
    a broken rule with `backendPort=80` + `enableFloatingIp=null` and traffic
    times out.
  - `service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol: tcp` —
    forces TCP probes. Default HTTP `GET /` returns 404 from the controller
    (no Ingress rule matches), failing the probe and dropping the backend.

### 4.10 Agent pod (`agent-service`)

- **What:** The reasoning loop. FastAPI on port 8001 exposing `/health` and
  `/metrics`. The actual work happens in a background asyncio task.
- **Loop:** Every 300 seconds:
  1. Call `get_current_anomaly_signal` (POSTs a baseline window to ML
     `/predict` — the response is shaped by ML's injection override if active)
  2. If NORMAL → log audit event, sleep
  3. Else, call up to 10 tools in a Claude tool_use loop
  4. Build a `RemediationPlan`
  5. If confidence > 0.75 and mode ≠ SECURITY_DRIFT → `create_remediation_pr`
  6. Always call `log_audit_event` exactly once at the end
- **Secrets:** Currently loaded from env vars (`ANTHROPIC_API_KEY`,
  `GITHUB_APP_PRIVATE_KEY`) via a K8s Secret. Falls back to Key Vault when env
  vars aren't set (the production path).
- **Validation guards:** `_validate_plan` in `agent/tools.py` enforces the six
  hard rules in code, in addition to the system prompt.

### 4.11 GitHub App (`cloudsentro-agent`)

- **What:** The identity the agent posts PRs as.
- **Permissions:** Repository — Contents (write), Pull requests (write),
  Metadata (read).
- **Auth chain:** App ID + PEM → JWT (RS256, 9 min) → installation token
  (1 hour) → cached, auto-refreshed 5 min before expiry.

### 4.12 Cloudflare

- **What:** DNS + TLS terminator + CDN. Proxies traffic to the AKS public IP.
- **Records:**
  - `infra-pulse.cloudsentro.com` → A → `<ingress public IP>` (proxied)
  - `www.infra-pulse.cloudsentro.com` → CNAME → `infra-pulse.cloudsentro.com`
- **SSL mode:** Flexible (client ↔ Cloudflare HTTPS; Cloudflare ↔ origin HTTP).
- **Token scope:** Zone → DNS → Edit. (Page Rules removed from Terraform
  because the demo token doesn't need that scope.)

---

## 5. How the pieces collaborate

This is the part most architecture diagrams hand-wave over. Here's exactly
who talks to whom and how authentication flows.

### Image build path

```
git push to main (path: ml/** or agent/**)
        │
        ▼
GitHub Actions (OIDC)
        │ federates as mi-cloudsentro-terraform (oid f2ee2e29-...)
        ▼
az acr login    ← needs AcrPush role on ACR (granted in infra/modules/acr/)
        │
        ▼
docker build → trivy scan (CRITICAL+HIGH) → docker push
        │
        ▼
ACR: cloudsentro/{ml,agent}:<sha> + :latest
```

### Image pull path

```
kubectl apply (deployment.yaml)
        │
        ▼
AKS scheduler picks node aks-default-30316074-vmss000000
        │
        ▼
kubelet pull from ACR    ← needs AcrPull role on kubelet identity
                            (attached via `az aks update --attach-acr`)
        │
        ▼
Pod starts
```

### Infra change path (GitOps gate)

```
Open PR
   │
   ▼
GitHub Actions tf-plan.yml
   │  runs `terraform plan` against HCP Cloud workspace
   │  HCP Cloud creates a speculative run
   │  output piped to PR comment
   │  exit code (pipefail) reflects HCP Cloud's actual plan result
   ▼
Human reviews
   │
   ▼
Merge to main
   │
   ▼
HCP Cloud VCS integration auto-triggers an apply
   │  authenticates to Azure via federated OIDC (afa7467c-...)
   │  scope: subscription Contributor + KV Secrets Officer
   ▼
GitHub Actions tf-apply.yml
   │  polls HCP Cloud /api/v2/.../runs?search[commit]=<sha>
   │  waits for terminal status
   │  exits 0 (applied / planned_and_finished) or 1 (errored)
   ▼
GitHub commit status reflects the real HCP Cloud outcome
```

### Anomaly detection path

```
Agent's run_loop fires (every 300s)
   │
   ├─▶ POST ml-service:8000/predict   { metrics: 60×7 baseline window }
   │       │
   │       └─▶ ML pod:
   │           ─ scaler.transform(window)
   │           ─ LSTM autoencoder → per-channel reconstruction error
   │           ─ IsolationForest (binary normal/anomalous)
   │           ─ RandomForest (6-class failure mode)
   │           ─ if /inject is active, override response with injection
   │           ─ ANOMALY_SCORE.set(...) updates the Prometheus gauge
   │           ─ PREDICTIONS_TOTAL.labels(mode).inc()
   │           ─ return AnomalySignal {score, mode, confidence, ...}
   │
   ├─▶ Prometheus scrapes ml-service:8000/metrics (15s interval)
   │       │
   │       └─▶ Grafana queries Prometheus → renders the dashboard
   │
   └─▶ Agent decides next tool call based on the signal
```

### Remediation path

```
Agent sees failure_mode != NORMAL and confidence > 0.75
   │
   ▼
Tool loop (max 10 turns):
   ─ get_azure_monitor_metrics(hours=1)
   ─ get_kubernetes_events(minutes=30)
   ─ get_recent_infra_changes()
   ─ read_terraform_file("infra/modules/aks/main.tf")
   ─ ...
   ▼
Claude returns a RemediationPlan
   │
   ▼
create_remediation_pr tool
   │  1. _validate_plan() — enforces hard rules
   │  2. GitHub App auth (JWT → installation token)
   │  3. Create branch fix/agent-YYYYMMDD-HHmm-{mode}
   │  4. PUT /repos/.../contents/<file_path> with new content
   │  5. POST /repos/.../pulls
   │  6. POST /repos/.../issues/<N>/labels
   ▼
PR appears in GitHub
   │
   ▼
log_audit_event tool
   │  Appends JSONL record to Azure Blob (audit/YYYY-MM-DD.jsonl)
   │  Or, if blob not configured: logs locally
   ▼
Agent sleeps 300s; loop repeats
```

---

## 6. Data flow during an incident

Real timeline from the demo:

| t | What happened |
|---|---|
| `t=0` | Operator: `bash scripts/demo.sh` |
| `t≈5s` | `inject_anomaly.py` POSTs `/inject` with `{failure_mode=OOM_LEAK, intensity=0.95, duration=10m}`. ML pod stores the override in memory. |
| `t≈10s` | `demo.sh` polls `/predict`. ML returns `anomaly_score=0.95, failure_mode=OOM_LEAK`. Detection time: ~10 seconds. |
| `t≈110s` | Prometheus scrapes ML pod. `cloudsentro_anomaly_score` gauge in TSDB jumps from 0.10 to 0.95. |
| `t≈200s` | Grafana panel reflects the spike on the time-series chart (auto-refresh 30s). |
| `t≈300s` | Agent's `run_loop` fires its next iteration. |
| `t≈310s` | Tool 1: `get_current_anomaly_signal` → OOM_LEAK / 0.95 / confidence 0.88. |
| `t≈315s` | Tool 2: `get_recent_infra_changes` → last touch was the Phase 4 module 18h ago. |
| `t≈320s` | Tool 3: `read_terraform_file("infra/modules/aks/main.tf")` → returns current AKS config. |
| `t≈335s` | Claude returns its `RemediationPlan`. Confidence 0.88, mode OOM_LEAK, proposes `max_count: 2 → 3`. |
| `t≈340s` | Tool 4: `create_remediation_pr` opens PR #17. |
| `t≈345s` | Tool 5: `log_audit_event` writes the cycle outcome. |
| `t≈600s` | Agent loop fires again. Injection still active. Agent sees OOM_LEAK again, sees PR #17 in `get_recent_infra_changes`, and reasons "previous remediation was insufficient". Proposes a bigger fix: VM size → D4s_v3, max_count → 5, max_surge → 25%. Opens PR #18. |
| `t≈?` | Human reviews PR #18, sees the reasoning, merges. HCP Cloud applies. Cluster scales up. |

---

## 7. Security model

### Identity & auth

Two distinct Azure principals for two trust domains. They are not the same;
that mistake cost us hours during Phase 4.

| Identity | Object ID | Used by | Granted |
|---|---|---|---|
| `mi-cloudsentro-terraform` (managed identity) | `f2ee2e29-...` | GitHub Actions OIDC | AcrPush on ACR |
| HCP Cloud workspace SP | `afa7467c-...` | HCP Cloud terraform apply | Subscription Contributor + KV Secrets Officer |
| AKS kubelet identity | (cluster-managed) | Image pulls | AcrPull on ACR |

`TF_VAR_principal_id` carries the first; `TF_VAR_terraform_runner_principal_id`
carries the second. Both are HCP Cloud workspace variables, sensitive.

### Secrets

The only static secrets in the system live in **Azure Key Vault**:

- `claude-api-key` — for the agent to call Anthropic
- `github-app-private-key` — for the agent to mint installation tokens
- `grafana-admin-password` — random, written on apply, never exported

For the demo runs in this branch, the agent reads its API key and PEM from a
Kubernetes `Secret` (`agent-secrets` in the `cloudsentro` namespace). The
production path is to enable Workload Identity Federation on the agent pod and
have it read from Key Vault via `DefaultAzureCredential`. The code supports
both (env vars first, Key Vault fallback).

### Pod hardening

Both ML and agent pods run with:

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
```

### Network

The NSG module defines (but does not attach — AKS manages its own NSG) a
posture that would only allow inbound from Cloudflare's IPv4 ranges + the
operator's admin IP. The AKS-managed NSG is already restrictive enough for
the demo; the standalone NSG is documentation-as-code for the intended
production posture.

### Image scanning

Both `ml-build.yml` and `agent-build.yml` run Trivy with `severity:
CRITICAL,HIGH` after the build and before the push. CRITICAL or HIGH with a
fix available **fails the build**. A `.trivyignore` at the repo root pins
three known-acceptable HIGHs in base-image vendored deps and starlette.

---

## 8. GitOps pipeline

Read this if you're going to make a change.

**Rule 1: nothing applies to infrastructure without a PR.** Direct pushes to
`main` bypass the speculative plan review and break the audit trail.

**Rule 2: the GitHub Action commit status is the source of truth.** When you
merge, watch `Terraform Apply` on the Actions tab. It polls HCP Cloud for the
real run and exits with the real outcome. ✓ green means apply succeeded; ✗
red means the apply failed (paste the error from HCP Cloud and we fix it).

**Rule 3: image rebuilds are scoped by path filter.** `ml-build.yml` only
runs when `ml/**` changes; same for `agent-build.yml` and `agent/**`. A
docs-only commit doesn't trigger image builds.

### What a normal change looks like

```bash
git checkout main && git pull origin main
git checkout -b feature/my-change
# ... edit files ...
git add … && git commit -m "feat: …"
git push -u origin feature/my-change
# Open PR via GitHub UI, watch tf-plan comment, review plan, merge
```

After merging, `Terraform Apply` runs. When it goes green, the change is
live.

---

## 9. Running the demo

Prereqs:

```powershell
# Cluster credentials
az aks get-credentials --resource-group rg-cloudsentro-terraform `
  --name cloudsentro-demo --overwrite-existing

# Phase 1 outputs
$env:ACR_LOGIN_SERVER  = "acrcloudsentrojdly.azurecr.io"
$env:AKS_RESOURCE_ID   = (az aks show -g rg-cloudsentro-terraform -n cloudsentro-demo --query id -o tsv)
$env:GITHUB_REPO_OWNER = "Rijens7065"

# Step 1 — get an Anthropic API key from console.anthropic.com
$env:ANTHROPIC_API_KEY = "sk-ant-…"

# Step 2 — create a GitHub App with Contents/PullRequests write,
# install it on this repo, save the PEM. App ID and Installation ID
# from the App's settings + install URL respectively.
$env:GITHUB_APP_ID          = "1234567"
$env:GITHUB_INSTALLATION_ID = "12345678"
$env:GITHUB_APP_PEM_FILE    = "C:\path\to\cloudsentro-agent.pem"
```

Then:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/deploy.sh
& 'C:\Program Files\Git\bin\bash.exe' scripts/demo.sh
```

`deploy.sh` renders the k8s manifests with substituted values and applies
them. `demo.sh` walks through five Enter-to-continue steps: verify dashboard
→ inject anomaly → watch ML score climb → poll for the agent's PR → print a
summary table.

---

## 10. Operations runbook

### "The dashboard shows No data"

The Grafana dashboard defaults to **Last 6 hours**. Metrics only flow after
pods start, and they reset on pod restart. Change the time picker to
**Last 15 minutes**.

### "PR shows up empty / I want the agent to stop opening PRs"

Restart the ML pod to clear the injection override:

```powershell
kubectl rollout restart -n cloudsentro deployment/ml-service
```

The agent will see NORMAL on its next cycle, will not open another PR.

### "AKS LB isn't accepting traffic"

If you ever rebuild the cluster and traffic times out at the LB, check:

1. The probe protocol — must be TCP, not HTTP. The annotation
   `service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol: tcp`
   on the ingress service is in our Terraform but verify with:

   ```powershell
   az network lb probe list -g <node-rg> --lb-name kubernetes -o table
   ```

2. The LB rule's `enableFloatingIp` — must be true.

3. If the AKS cloud-controller reverts these, re-apply with `kubectl rollout
   restart` on the ingress-nginx deployment to force re-reconciliation.

### "The agent is failing silently"

Check `/health` for the cycle counter:

```powershell
kubectl exec -n cloudsentro deploy/agent-service -- python -c "import urllib.request,json; print(json.dumps(json.loads(urllib.request.urlopen('http://localhost:8001/health').read()), indent=2))"
```

If `cycles_completed` is incrementing but `last_error` is set, look at
`kubectl logs`. The common errors: 401 from Anthropic (bad key), 403 from
GitHub App (token expired or permissions missing), httpx connection error
(network policy issue).

---

## 11. Cost breakdown

| Service | Estimated cost / mo |
|---|---|
| AKS — 1× Standard_D2s_v3 | ~$70 (on-demand) |
| ACR — Basic | ~$5 |
| Azure Key Vault | <$1 |
| Azure Blob (audit log) | <$1 |
| Claude API (~500 agent calls) | ~$6 |
| LB + public IP | ~$5 |
| **Total (typical)** | **~$87 if 24/7, ~$37 if scaled-to-zero overnight** |

Budget alert is set at $35 (70% of $50) and $45 (90%).

---

## 12. Glossary

| Term | What it means |
|---|---|
| **AnomalySignal** | The Pydantic model the ML pod returns. Fields: `anomaly_score`, `failure_mode`, `confidence`, `time_to_impact_minutes`, `affected_metrics`, `explanation`. |
| **RemediationPlan** | The output the agent emits at the end of its reasoning loop. Contains the AnomalySignal plus root cause, reasoning chain, Terraform change set, and rollback instructions. |
| **Tool use** | Claude's API mode where the model can invoke typed tools. Each tool has a JSON schema for inputs; the model emits a `tool_use` block, the host runs the tool, and the result feeds back into the conversation. |
| **GitOps gate** | The human-approved PR step in the pipeline. The agent proposes; the human approves; HCP Cloud applies. Nothing reaches infrastructure without that approval. |
| **DEMO_MODE** | An env var on the ML pod. When `true`, the `/inject` endpoint accepts requests to override the next prediction. Off in production. |
| **Workload identity** | AKS's way of giving pods their own Azure AD identity via federated credentials, so they can call Azure APIs without static secrets. We've wired it for the ML pod but the agent currently uses a K8s Secret instead (production path is documented in the code). |
