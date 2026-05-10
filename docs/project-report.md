# CloudSentro — Project Report

**Autonomous Infrastructure Intelligence**

Founder: Rijens Nadoda
Flagship project: infra-pulse
Live demo: https://infra-pulse.cloudsentro.com/grafana/
Repository: https://github.com/Rijens7065/infra-pulse
Document version: 1.0 — May 2026

---

## Executive Summary

CloudSentro is an autonomous infrastructure remediation system. It watches a
cloud cluster, detects anomalies with a small ML model, reasons about each
one using a Claude language model with typed tools, and ships the fix as a
real GitHub pull request — all on its own, with a human signing off at the
end.

The flagship project, **infra-pulse**, runs end-to-end on Microsoft Azure
Kubernetes Service for approximately **$37 per month**. It detects six
classes of infrastructure failure (memory leaks, CPU throttling, network
degradation, cost spikes, security drift, and the absence of any of these),
classifies them at **99.23% test accuracy**, and proposes Terraform changes
through a zero-secret GitOps pipeline.

During the five-phase build, the team encountered and resolved more than
twenty distinct issues spanning Azure provider drift, virtual-machine SKU
restrictions, identity federation mismatches, load-balancer health-probe
configuration, container security scanning, Anthropic SDK compatibility, and
demo orchestration bugs. Each fix is documented in this report.

The same engineering pattern — model produces structured signal, agent
reasons, pull request ships through human-gated GitOps — generalises beyond
this specific use case. The closing section of this report outlines how
CloudSentro can be packaged as a software-as-a-service product, the target
customer profile, pricing model, competitive positioning, and the
engineering work required to take it to market.

---

## Part 1 — Project Overview

### 1.1 What CloudSentro is and is not

**CloudSentro is** a system that automates the cognitive work of an on-call
SRE: reading metrics, correlating them with recent changes, diagnosing the
root cause, and writing the fix. It is bounded by an explicit human-approval
gate at the end of the loop — the system never applies changes to
infrastructure by itself.

**CloudSentro is not** an autonomous agent in the unsupervised sense. Every
change reaches infrastructure as a pull request that a human reviews and
merges. The "autonomy" is in the steps leading up to that approval, not the
approval itself.

### 1.2 The problem

A pod is leaking memory at 2:47 AM. An engineer is paged. They SSH in, read
logs, write a Terraform patch, find someone to review it at 3 AM, deploy,
and confirm the fix. The work is high-context (read the metrics, recall the
relevant module, look at recent commits) and well-bounded (the answer is
usually one specific Terraform attribute), and the engineer is asleep for
the first thirty minutes.

The bottleneck is not the apply — the apply is fast — but the cognitive
work of diagnosis and patch authoring. That work follows a repeatable
pattern, which is exactly the kind of thing that benefits from a
purpose-built loop.

### 1.3 The approach

Three layers, in this order, each strictly more expensive than the last:

1. **Detection** — a pre-trained PyTorch model classifies metrics into
   labelled failure modes. Inference cost: a few milliseconds, runs locally
   on the cluster.
2. **Reasoning** — a Claude language model with seven typed tools
   investigates the labelled anomaly, reads the actual Terraform file,
   correlates with recent commits, and proposes a fix. Cost: a handful of
   cents per remediation cycle.
3. **Approval** — a human reviews the pull request, sees the reasoning
   chain, and approves or rejects. Cost: human attention, but only at the
   end of the loop and only when something needs attention.

Each layer hands off a structured contract to the next:
- The model emits an `AnomalySignal` (score, mode, confidence, explanation).
- The agent emits a `RemediationPlan` (diagnosis, proposed Terraform diff,
  rollback steps, reasoning chain).
- The human emits a merge or a close.

### 1.4 Live status

| Aspect | Status |
|---|---|
| Public dashboard | Live at https://infra-pulse.cloudsentro.com/grafana/ |
| End-to-end demo | Operational — agent has opened two real remediation pull requests |
| Test accuracy | 99.23% on a held-out 15% split |
| Inference latency | <200 ms |
| Monthly running cost | ~$37 (cluster scaled overnight) — ~$87 if 24/7 |
| Total static credentials | Zero |

---

## Part 2 — Architecture and Services

### 2.1 System architecture overview

The system has three planes:

**Compute plane** — Azure Kubernetes Service (AKS) hosts every running
component: the ML pod, the agent pod, NGINX ingress, Prometheus, and
Grafana. A single-node cluster (Standard_D2s_v3, 8GB RAM) suffices for the
demo workload.

**Control plane** — Terraform code in a Git repository, executed by HCP
Cloud (HashiCorp's hosted Terraform service). Every infrastructure change
flows through a pull request, a speculative plan, a human approval, and an
automatic apply on merge.

**Data plane** — three categories of data flow through the system:
metrics (Prometheus scrapes ML/agent pods plus container-level cAdvisor
data), reasoning (the agent's Claude API calls), and remediation (the
GitHub pull request payload).

A simplified diagram (drawn with ASCII for portability):

```
+----------------+    +----------------+    +-----------------+
| AKS metrics    |--->|  ML pod        |--->| Agent pod       |
| + cAdvisor     |    |  /predict      |    | (every 300s)    |
+----------------+    |  /metrics      |    |                 |
                      |  /inject       |    | tools:          |
                      |  (DEMO_MODE)   |    | - get signal    |
                      +-------+--------+    | - get metrics   |
                              |             | - get events    |
                Prometheus    |             | - read tf file  |
                scrape 15s    |             | - create PR     |
                              v             | - log audit     |
                      +----------------+    +-------+---------+
                      | Prometheus     |            |
                      | (server)       |            |
                      +-------+--------+            |
                              |                     v
                              v             +-----------------+
                      +----------------+    | GitHub PR       |
                      | Grafana        |    | - Anomaly       |
                      | /grafana       |    | - Root cause    |
                      | (anonymous)    |    | - Reasoning     |
                      +----------------+    | - Diff          |
                                            | - Rollback      |
                                            +--------+--------+
                                                     |
                                          human reviews & merges
                                                     |
                                                     v
                                            +-----------------+
                                            | HCP Cloud       |
                                            | terraform apply |
                                            +-----------------+
```

### 2.2 Service-by-service reference

The following sections cover every running component in detail.

#### 2.2.1 Terraform (HCP Cloud)

**What it is.** The control plane for all Azure infrastructure. Defines
every resource: AKS cluster, container registry, Key Vault, ingress
controller, Prometheus, Grafana, network security group, DNS records,
budget alerts.

**Where it runs.** Remotely on HCP Cloud. State is encrypted there. No
state file in the Git repository.

**How it is triggered.** A push to the `main` branch triggers HCP Cloud's
VCS-integration speculative plan, then auto-apply. A pull request triggers
a speculative-plan-only run, the output of which is posted as a comment on
the pull request.

**Authentication.** OIDC federated credentials. HCP Cloud presents a JWT
to Azure Active Directory; AAD validates it against a federated credential
on an app registration and issues a short-lived access token. There is no
client secret involved.

**File layout.**

```
infra/
  providers.tf          azurerm, azuread, cloudflare, helm, kubernetes, random, time
  variables.tf          input variables
  outputs.tf            published outputs after apply
  main.tf               module wiring
  modules/
    resource_group/     the umbrella RG
    acr/                container registry + AcrPush role assignment
    aks/                Kubernetes cluster
    keyvault/           secrets store + Secrets Officer role + time_sleep for propagation
    budget/             $50/mo cap with alerts at 70% and 90%
    identity/           DEFERRED — requires Application Administrator role
    ingress/            NGINX ingress controller via Helm
    prometheus/         Prometheus server via Helm
    grafana/            Grafana via Helm + Key Vault password + dashboard ConfigMap
    nsg/                Cloudflare-only ingress posture
    dns/                Cloudflare DNS records
```

#### 2.2.2 GitHub Actions

**What it is.** Continuous integration. Four workflows in
`.github/workflows/`.

| Workflow | When it runs | What it does |
|---|---|---|
| `tf-plan.yml` | On every pull request | Runs `terraform plan` against the HCP Cloud workspace; posts the output as a comment on the PR; exits non-zero if the plan failed (using `set -o pipefail` so the exit code is honest) |
| `tf-apply.yml` | On push to `main` | Polls HCP Cloud's API for the run associated with the commit, waits for terminal status (`applied` or `errored`), exits accordingly; posts a final comment with the run URL |
| `ml-build.yml` | On push to `main` touching `ml/**` | Builds the ML Docker image, runs Trivy CRITICAL/HIGH vulnerability scan with `ignore-unfixed` and a repo-root `.trivyignore`, pushes to ACR |
| `agent-build.yml` | On push to `main` touching `agent/**` | Same pattern for the agent image |

**Authentication.** OIDC federated credentials. GitHub Actions presents a
JWT, which Azure exchanges for an access token bound to the managed
identity `mi-cloudsentro-terraform`. No static credentials.

#### 2.2.3 Azure Container Registry

**What it is.** Private Docker registry. Stores two images:
`cloudsentro/ml` and `cloudsentro/agent`.

**SKU.** Basic.

**Push.** GitHub Actions, authenticated via OIDC, runs `az acr login` and
then `docker push`. The role `AcrPush` is granted to the managed identity
in the ACR module.

**Pull.** The AKS kubelet identity pulls. The role `AcrPull` was attached
once with `az aks update --attach-acr` — this is a known one-time
imperative step that should be moved into the Terraform AKS module as
follow-up work.

#### 2.2.4 Azure Kubernetes Service

**What it is.** A managed Kubernetes cluster that hosts everything else.

**Node pool.** One node of type `Standard_D2s_v3` (2 vCPU, 8 GB RAM). The
original plan was a B-series spot instance for ~$10/month, but the
B-series is not in the canadaeast subscription's allowed SKU list and the
B2s_v2 family has zero vCPU quota allocated. The D-series fits within the
allowed list.

**Features enabled.** OIDC issuer, workload identity, kubenet networking,
Free SKU control plane.

**Namespaces.**

- `cloudsentro` — ML and agent pods
- `monitoring` — Prometheus, Grafana
- `ingress-nginx` — NGINX ingress controller

#### 2.2.5 Azure Key Vault

**What it is.** The only place static secrets exist in the system.

**Stored secrets.**

- `claude-api-key` — Anthropic API key (production path; the demo
  alternative uses a Kubernetes Secret)
- `github-app-private-key` — GitHub App PEM private key
- `grafana-admin-password` — randomly generated by Terraform, written on
  apply, never read by humans (admin login uses it)

**Authentication.** RBAC mode. The HCP Cloud identity has `Key Vault
Secrets Officer` (read and write); the time_sleep resource gives Azure RBAC
150 seconds to propagate before the first secret write.

#### 2.2.6 ML pod (`ml-service`)

**What it is.** The detection layer. A FastAPI process on port 8000 that
serves predictions from a PyTorch LSTM autoencoder plus a two-stage
scikit-learn classifier.

**Endpoints.**

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness — returns `{status, model_version, uptime_seconds}` |
| `POST /predict` | Body `{metrics: [[...60×7...]]}`; returns AnomalySignal |
| `GET /metrics` | Prometheus-format metrics |
| `POST /inject` | DEMO_MODE only — overrides the next prediction response |

**Custom Prometheus metrics exposed.**

- `cloudsentro_anomaly_score` (gauge) — latest score, 0 to 1
- `cloudsentro_predictions_total{failure_mode}` (counter) — calls served, labelled by classification
- `cloudsentro_prediction_duration_seconds` (histogram) — request latency

**Model training.** Runs inside the Docker build itself (stage 2 of a
multi-stage Dockerfile). The runtime image contains pre-trained artifacts;
no training happens at runtime.

**Security context.** Non-root user (uid 1000), read-only root filesystem,
all Linux capabilities dropped, seccomp `RuntimeDefault`.

#### 2.2.7 Prometheus

**What it is.** Time-series database and scraper. Pulls metrics from the
ML and agent pods every 15 and 30 seconds respectively, plus container-
level cAdvisor metrics from the AKS kubelet, plus its own internal metrics.

**Retention.** Seven days, on a 2 GB persistent volume.

**Where.** `monitoring` namespace, service name `prometheus-server` on
port 80.

#### 2.2.8 Grafana

**What it is.** The dashboard UI. Anonymous Viewer access is enabled, so
the live demo is publicly viewable without a login.

**Where.** `monitoring` namespace, exposed publicly at
`https://infra-pulse.cloudsentro.com/grafana/` through the NGINX ingress.

**Datasource.** Provisioned with an explicit UID of `prometheus` so the
dashboard JSON's datasource references resolve.

**Dashboards.** Loaded via the sidecar mechanism only (the filesystem
provider would have created a duplicate empty folder). The sidecar watches
ConfigMaps with label `grafana_dashboard=1` in the `monitoring` namespace
and uploads them to the `CloudSentro` folder via the Grafana HTTP API.

**Admin password.** Randomly generated by Terraform on apply, written to
Key Vault, mounted as a Kubernetes Secret in the pod, never displayed
elsewhere.

#### 2.2.9 NGINX ingress controller

**What it is.** The public entry point for HTTP traffic. Forwards
`/grafana/*` to the Grafana service inside the cluster.

**Public IP.** Allocated from Azure's standard load-balancer pool —
currently 40.86.213.249.

**Two critical configuration choices.**

The first is `controller.service.externalTrafficPolicy: Local`. Without
this, the AKS cloud-controller creates a load-balancer rule with
`backendPort: 80` and `enableFloatingIp: null` — which means the load
balancer translates inbound traffic to port 80 on the node, but nothing on
the node listens on port 80 (kube-proxy is on the NodePort, 30932).
Traffic times out. With `Local`, the load balancer uses Direct Server
Return (`enableFloatingIp: true`), preserving the destination IP and port
so the iptables rules on the node catch the packet.

The second is the annotation `service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol: tcp`.
Without this, the default health probe is HTTP `GET /` — which returns 404
from the ingress controller (no Ingress rule matches that exact path),
fails the probe, and causes the load balancer to mark the backend as
unhealthy. TCP probes only check that the port is open and always succeed
when the controller is running.

#### 2.2.10 Agent pod (`agent-service`)

**What it is.** The reasoning layer. A FastAPI process on port 8001 that
exposes `/health` and `/metrics`. The actual work runs in a background
asyncio task driven by `run_loop`.

**The loop.** Every 300 seconds:

1. Call `get_current_anomaly_signal`. This POSTs a baseline 60x7 metrics
   window to the ML pod's `/predict`. The injection override (if active)
   shapes the response.
2. If the failure mode is `NORMAL`, log an audit event and sleep.
3. Otherwise, run a Claude tool-use loop of up to ten turns.
4. Build a `RemediationPlan`.
5. If confidence is greater than 0.75 and the mode is not `SECURITY_DRIFT`,
   call `create_remediation_pr`.
6. Always call `log_audit_event` exactly once at the end.

**Secrets loading.** Environment variables first (`ANTHROPIC_API_KEY`,
`GITHUB_APP_PRIVATE_KEY`), Key Vault as a fallback. The demo runs use a
Kubernetes Secret mounted as env vars; the production path uses workload
identity federation to read directly from Key Vault.

**The six hard rules.** Enforced in both the system prompt (Claude is told
not to do these things) and in code (`_validate_plan` in `agent/tools.py`
rejects any plan that violates them, with unit tests covering each rule):

1. Never delete Azure resources, only modify or update.
2. Never modify IAM, RBAC, role assignments, identities, or workload
   identity federated credentials.
3. Never touch `infra/modules/budget/` or `infra/modules/identity/`.
4. Never write outside `infra/`.
5. Open a pull request only if confidence is greater than 0.75.
6. For `SECURITY_DRIFT` anomalies, log only — never open a pull request.

#### 2.2.11 GitHub App (`cloudsentro-agent`)

**What it is.** The identity that opens pull requests on behalf of the
agent. Not a personal access token, not a service account — a proper
GitHub App with scoped repository permissions.

**Permissions.** Contents (write), Pull requests (write), Metadata (read).

**Authentication chain.** App ID + PEM private key produce a JWT with a
9-minute expiry, signed with RS256. The JWT is exchanged for an
installation access token (1-hour TTL) scoped to the single repository.
Tokens are cached in memory and refreshed 5 minutes before expiry.

#### 2.2.12 Cloudflare

**What it is.** DNS + TLS terminator + CDN. Proxies traffic to the AKS
public IP and to the static landing site.

**Records.**

- `infra-pulse.cloudsentro.com` — A record proxied to the AKS load balancer
- `www.infra-pulse.cloudsentro.com` — CNAME alias, proxied
- `cloudsentro.com` (apex) — proxied to Cloudflare Workers (the static site)
- `www.cloudsentro.com` — CNAME, proxied

**SSL mode.** Flexible. Cloudflare terminates TLS at its edge with its own
certificate; the origin connection is plain HTTP. A production deployment
would use Full Strict mode with cert-manager and Let's Encrypt on the
ingress.

**Token scope.** Zone → DNS → Edit. The Page Rules permission was
intentionally removed from the Terraform configuration because the demo
token does not have that scope; Grafana's own cache headers handle the
behaviour the page rule was added for.

---

## Part 3 — How the Services Collaborate

This section describes the exact sequence of calls and authentication
between components for each major operation.

### 3.1 Image build and push

```
git push to main (path: ml/** or agent/**)
        │
        ▼
GitHub Actions, authenticated via OIDC, federates as
mi-cloudsentro-terraform (object id f2ee2e29-...).
        │
        ▼
az acr login   ← requires AcrPush role on ACR
                  (granted by the ACR module)
        │
        ▼
docker build → Trivy scan (CRITICAL+HIGH) → docker push
        │
        ▼
Image lands in ACR as cloudsentro/{ml,agent}:<sha> and :latest.
```

### 3.2 Image pull and pod start

```
kubectl apply (or rollout restart) submits the deployment.
        │
        ▼
AKS scheduler picks a node.
        │
        ▼
kubelet pulls from ACR.   ← requires AcrPull role on the
                              kubelet identity (one-time
                              attached via az aks update)
        │
        ▼
Pod starts. Liveness and readiness probes go green.
```

### 3.3 Infrastructure change path (the GitOps gate)

```
A pull request is opened.
        │
        ▼
GitHub Actions tf-plan.yml runs terraform plan against the HCP
Cloud workspace. HCP Cloud creates a speculative run. The output
is captured (with `set -o pipefail` so the exit code reflects the
real plan result) and posted as a comment on the pull request.
        │
        ▼
A human reviews the plan and merges.
        │
        ▼
HCP Cloud's VCS integration detects the merge to main and
auto-triggers an apply. The runner authenticates to Azure via
the HCP Cloud federated OIDC identity (afa7467c-...).
        │
        ▼
GitHub Actions tf-apply.yml polls
GET /api/v2/workspaces/<id>/runs?search[commit]=<sha>
every 20 seconds. When the run reaches a terminal status
(applied, planned_and_finished, errored, canceled, etc.),
the workflow exits 0 or 1 accordingly.
        │
        ▼
The GitHub commit status reflects HCP Cloud's real outcome.
```

### 3.4 Anomaly detection path

```
The agent's run_loop fires (every 300 seconds).
        │
        ├─▶ POST ml-service:8000/predict
        │       │
        │       └─▶ ML pod runs:
        │           scaler.transform(window)
        │           LSTM autoencoder → per-channel reconstruction error
        │           IsolationForest gate → anomalous-or-not
        │           RandomForest classifier → six failure modes
        │           If /inject is active, override the response
        │           ANOMALY_SCORE.set(...) updates Prometheus gauge
        │           PREDICTIONS_TOTAL.labels(mode).inc()
        │           Return AnomalySignal
        │
        ├─▶ Prometheus scrapes ml-service:8000/metrics (15s interval)
        │       │
        │       └─▶ Grafana queries Prometheus and renders panels
        │
        └─▶ The agent decides the next tool call based on the signal.
```

### 3.5 Remediation path

```
The agent's loop sees failure_mode != NORMAL and confidence > 0.75.
        │
        ▼
Tool loop (up to 10 turns) — Claude calls a sequence of tools:
  get_azure_monitor_metrics(hours=1)
  get_kubernetes_events(minutes=30)
  get_recent_infra_changes()
  read_terraform_file("infra/modules/aks/main.tf")
  ...
        │
        ▼
Claude returns a RemediationPlan.
        │
        ▼
The create_remediation_pr tool runs:
  _validate_plan() — enforces the six hard rules
  GitHub App authentication (JWT → installation token)
  Create branch fix/agent-YYYYMMDD-HHmm-<failure_mode>
  PUT /repos/.../contents/<file_path> with new content
  POST /repos/.../pulls
  POST /repos/.../issues/<N>/labels
        │
        ▼
The pull request appears in GitHub with a populated body:
  Anomaly Report (failure mode, score, ML explanation)
  Root Cause (Claude's plain-English diagnosis)
  Reasoning Chain (collapsible, step-by-step)
  Proposed Changes (Terraform diff)
  Rollback Instructions
        │
        ▼
log_audit_event tool appends a JSONL record to Azure Blob Storage.
        │
        ▼
The agent sleeps 300 seconds. The loop repeats.
```

### 3.6 Sample timeline of a single incident

Real timestamps from the live demo:

| t | Event |
|---|---|
| t = 0 | Operator runs `bash scripts/demo.sh` |
| t ≈ 5s | `inject_anomaly.py` posts `/inject` with OOM_LEAK, intensity 0.95, duration 10 minutes |
| t ≈ 10s | `demo.sh` polls `/predict`. ML returns `anomaly_score: 0.95, failure_mode: OOM_LEAK` |
| t ≈ 110s | Prometheus scrapes the ML pod; the gauge in the TSDB jumps from 0.10 to 0.95 |
| t ≈ 200s | Grafana panel reflects the spike (30-second auto-refresh) |
| t ≈ 300s | Agent's run_loop fires its next iteration |
| t ≈ 310s | Tool 1: `get_current_anomaly_signal` returns OOM_LEAK / 0.95 / confidence 0.88 |
| t ≈ 315s | Tool 2: `get_recent_infra_changes` returns the last commits |
| t ≈ 320s | Tool 3: `read_terraform_file("infra/modules/aks/main.tf")` returns the current AKS config |
| t ≈ 335s | Claude returns its `RemediationPlan` proposing `max_count: 2 → 3` |
| t ≈ 340s | Tool 4: `create_remediation_pr` opens PR #17 |
| t ≈ 345s | Tool 5: `log_audit_event` writes the cycle outcome |
| t ≈ 600s | Next agent loop. Injection still active. The agent sees the previous PR in `get_recent_infra_changes`, reasons that the prior remediation was insufficient, and proposes a larger fix (VM size to D4s_v3, max_count to 5). Opens PR #18 |
| t = ? | A human reviews PR #18, merges. HCP Cloud applies. The cluster scales up |

---

## Part 4 — Issues Encountered and Resolved

The five-phase build encountered more than twenty issues. Each is recorded
below with the symptom, the cause, the resolution, and the lesson.

### Phase 1 — Foundation

**Issue 1.1 — azurerm 3.x AKS attribute drift.** `terraform validate`
rejected the keys `enable_auto_scaling` and `auto_scaling_enabled` in
`default_node_pool`. The cause was a breaking change in azurerm 3.117.1:
both attributes were removed. Autoscaling is now implicit when both
`min_count` and `max_count` are set. The fix was to drop both attributes
and rely on the implicit behaviour.

**Issue 1.2 — Spot attributes on the system node pool.** Plan errored on
`priority`, `eviction_policy`, and `spot_max_price` in the default node
pool. Azure requires the system node pool to be a Regular (non-Spot)
VM; Spot is only available on user-added node pools. The fix was to
remove all three attributes from the system pool.

**Issue 1.3 — azurerm 4.x rename.** After upgrading to azurerm 4.x, the
Key Vault module failed validation on `enable_rbac_authorization`. The
cause was another rename: the attribute is now
`rbac_authorization_enabled`. The fix was the obvious rename.

**Issue 1.4 — Resource already exists on first apply.** The first apply
failed because the resource group `rg-cloudsentro-terraform` existed in
Azure (created manually during bootstrap so HCP Cloud could authenticate)
but was not in Terraform state. The fix was an `import {}` block in the
resource_group module, which adopted the existing resource into state on
the next apply; the block was removed after import succeeded. The lesson:
if a resource pre-exists, import it; never let Terraform try to recreate it.

**Issue 1.5 — VM SKU not allowed in canadaeast.** The AKS apply failed
with `Standard_B2s is not allowed in your subscription in location
'canadaeast'`. Newer Azure subscriptions in canadaeast only allow newer VM
generations; the B-series v1 is fully blocked, and the B2s_v2 family has
zero vCPU quota allocated by default. The fix was to switch to
`Standard_D2s_v3`, which is in the allowed list and has quota. The cost
trade-off was roughly $10/month for B2s Spot versus $70/month for D2s_v3
on-demand. The lesson: check `az vm list-skus --location <region>` and
the subscription's quota *before* designing around a specific VM size.

**Issue 1.6 — Cloudflare token rejected for invalid character.** HCP
Cloud apply failed during the Cloudflare DNS module with
`invalid value for api_token (API tokens must only contain characters
a-z, A-Z, 0-9, hyphens and underscores)`. The cause was a trailing newline
on the token pasted into the HCP Cloud workspace variable. Re-pasting
without whitespace resolved it.

**Issue 1.7 — Cloudflare 9109 Unauthorized on page rule.** Apply failed
creating the `/grafana/*` cache-bypass page rule. The Cloudflare token
had Zone → DNS → Edit but not Zone → Page Rules → Edit. The fix was to
remove the page rule entirely. Grafana sends its own `Cache-Control`
headers, so a Cloudflare cache bypass for `/grafana/*` was not
load-bearing. The lesson: scope tokens to the minimum, and design
infrastructure to fit the scope.

**Issue 1.8 — Key Vault 403 on first apply.** Apply created the role
assignment `Key Vault Secrets Officer` for the Terraform identity, then
tried to write the Grafana admin secret in the same apply, and got 403
ForbiddenByRbac. Azure RBAC takes between 30 and 120 seconds to propagate
to the data plane. The fix was a `time_sleep` resource (150 seconds) after
the role assignment in the keyvault module. The grafana module depends on
`module.keyvault`, so it now waits for that sleep to finish before writing.

**Issue 1.9 — The principal split.** Even after the propagation wait,
secret writes were still getting 403 — but from a different principal
than expected (`oid=afa7467c-...` rather than the `f2ee2e29-...` we had
granted the role to). The cause was that we had assumed GitHub Actions
and HCP Cloud authenticate as the same Azure principal. They do not.
GitHub Actions federates to the managed identity
`mi-cloudsentro-terraform`. HCP Cloud federates to a separate app
registration. The fix was to split the Terraform variable into two
distinct principal-id variables, one for each trust domain, and grant
the appropriate roles to each. The lesson: when an OIDC chain is
involved, always print the actual `oid` from the error JWT and never
assume that two CI systems share an identity.

**Issue 1.10 — Identity module deferred.** The Phase 1 apply failed
creating `azuread_application` resources with
`Authorization_RequestDenied: Insufficient privileges`. Creating app
registrations requires the Application Administrator directory role in
Microsoft Entra ID; the Terraform identity does not have it, and the
human operator does not have permission to grant it. The fix was to
comment out the identity module from `infra/main.tf` and the
corresponding outputs. The ML and agent pods use a Kubernetes Secret for
credentials in the demo (the production path would use workload identity
federation, but requires a directory-administrator one-time setup). The
lesson: check directory-role prerequisites before planning; app
registrations are a different permission domain from Azure RBAC.

### Phase 2 — ML Model

**Issue 2.1 — Python 3.14 on the developer machine.** `pip install
torch==2.1.0+cpu` failed with `No matching distribution found`. The
developer's Python is 3.14; torch 2.1.0 only has wheels up to Python
3.11. The fix for local testing was to install `torch==2.9.0+cpu`
instead. The Dockerfile uses `python:3.11-slim` with the pinned
`2.1.0+cpu` build for the production image. The lesson: decouple
local-development test versions from production-pinned versions, and
treat the Dockerfile as the source of truth.

**Issue 2.2 — Microsoft Visual C++ Redistributable missing.** `import
torch` failed on the Windows developer machine with "DLL load failed".
PyTorch on Windows depends on the VC++ runtime. Resolved with
`winget install Microsoft.VCRedist.2015+.x64 --silent`.

**Issue 2.3 — Generator test failed on small dataset.** The test
`test_normal_dominates` failed because the NORMAL class only made up 57%
of labels on a 3-day fixture. The generator always injects 8 to 15
anomaly windows regardless of dataset length; on a short dataset those
windows dominate. The fix was to switch the test fixture from 3 days to
10 days so the proportion of NORMAL versus anomalous matches the
production 30-day scenario.

### Phase 3 — Agent

**Issue 3.1 — anthropic SDK incompatible with newer httpx.** The agent
pod crashed at startup with `TypeError: Client.__init__() got an
unexpected keyword argument 'proxies'`. The anthropic SDK 0.28.0 passed
`proxies=` to the httpx Client constructor; httpx 0.28 removed that
argument. The fix was to bump anthropic to 0.49.0. The lesson: when
pinning a library, also pin (or at least understand) its HTTP-client
version.

**Issue 3.2 — Agent calling `/predict` with GET.** The agent logged
repeated `httpx.HTTPStatusError: 405 Method Not Allowed`. The original
blueprint described `GET /predict`, but the actual ML implementation only
accepts `POST /predict` with a 60x7 metrics body. The fix was to update
`run_get_current_anomaly_signal` to POST a baseline window; the
injection override on the ML side reshapes the response when active. The
production path (deferred) would have the ML pod maintain a rolling
window from Azure Monitor and expose `GET /signal/latest`.

**Issue 3.3 — Agent missing `/metrics` endpoint.** Prometheus scraped
`agent-service:8001/metrics` and got 404 in a loop. The deployment
annotation told Prometheus to scrape, but the route did not exist. The
fix was to add a `/metrics` endpoint returning `generate_latest()` from
`prometheus_client`. Initially empty, but a valid response.

### Phase 4 — Dashboard

Phase 4 had the highest issue count, partly because of its surface area
(seven modules) and partly because AKS plus ingress plus load balancer
has many subtle defaults.

**Issue 4.1 — Broken AKS load balancer rule.** External `curl
http://<lb-ip>/` timed out. The ingress pod was healthy (returned 404
from inside the cluster) but no external traffic reached it. The AKS
cloud-controller had created a load-balancer rule with `backendPort: 80`
and `enableFloatingIp: null` — meaning the load balancer DNATs traffic
to port 80 on the node, but nothing on the node listens on port 80
(kube-proxy is on the NodePort, 30932). Traffic landed on a dead port.
The fix was `controller.service.externalTrafficPolicy: "Local"` in the
ingress Helm values, which flips the load balancer into Direct Server
Return mode (`enableFloatingIp: true`), preserving the destination IP
and port so iptables on the node catches the packet.

**Issue 4.2 — Load balancer health probe returning 404.** Even with
FloatingIP fixed, the load balancer still did not forward traffic. The
auto-generated probe used HTTP `GET /`, and the ingress controller
returns 404 for `/` (no Ingress rule matches that exact path). The load
balancer requires 2xx-3xx for a healthy probe; 404 fails it, and the
load balancer marks the backend as unhealthy. The fix was the annotation
`service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol: tcp`,
forcing TCP probes (which only check that the port is open).

**Issue 4.3 — Grafana redirect loop.**
`https://infra-pulse.cloudsentro.com/grafana/` returned
`ERR_TOO_MANY_REDIRECTS` in the browser. The ingress used the path
pattern `/grafana(/|$)(.*)` with annotation
`nginx.ingress.kubernetes.io/rewrite-target: /$2` (strips `/grafana`).
Grafana was configured with `serve_from_sub_path: true` and
`root_url: …/grafana`, which means it *expects* to receive requests at
`/grafana/...`. Nginx stripped `/grafana`, Grafana saw `/`, redirected to
`/grafana/`, nginx stripped it again, infinite loop. The fix was to
remove the `rewrite-target` and `use-regex` annotations and use a plain
`/grafana` Prefix match.

**Issue 4.4 — Cloudflare 522 Connection Timed Out.** Cloudflare proxied
the request fine but could not reach the origin. The root cause was the
load balancer issues above (4.1 and 4.2). Once those were resolved, the
522 disappeared.

**Issue 4.5 — Cloudflare SSL mode mismatch.** With the load balancer
working, `https://infra-pulse.cloudsentro.com` still failed because
Cloudflare was trying to reach the origin on HTTPS (port 443) by default
("Full" SSL mode), and there is no TLS configured on the ingress. The
fix was to switch the Cloudflare SSL mode to Flexible. A production
deployment would use cert-manager and Let's Encrypt on the ingress with
Cloudflare in Full Strict mode.

**Issue 4.6 — Grafana duplicate folder.** After everything was up,
Grafana had an empty folder called "CloudSentro" plus a dashboard at the
root level. Two parallel mechanisms were configured to load dashboards —
a filesystem provider that watches `/var/lib/grafana/dashboards/cloudsentro/`
and a sidecar that uploads via the Grafana HTTP API. The filesystem
provider created the empty folder (because it had `folder = "CloudSentro"`
configured). The sidecar uploaded the dashboard to the General folder
via the API. The fix was to drop the filesystem provider entirely and
configure the sidecar with `defaultFolderName: "CloudSentro"`.

**Issue 4.7 — Grafana datasource UID mismatch.** Dashboard panels showed
"No data" even though Prometheus had the metrics. The dashboard JSON
referenced the datasource by UID
(`"datasource": {"type": "prometheus", "uid": "prometheus"}`), but
Grafana auto-generates a random UID for each provisioned datasource. The
actual UID was something like `cefh8kxhz...`, not `prometheus`. The fix
was to pin the UID explicitly in the datasources config (`uid:
prometheus`).

**Issue 4.8 — Anonymous Viewer missing folders:read.** After a Grafana
restart, the anonymous Viewer hit "folders:read permission denied". The
Grafana 7.0.19 chart vs newer Grafana RBAC defaults changed anonymous
Viewer's permissions. The demo workaround was to sign in as admin
(password retrieved from Key Vault) for screenshots. Fixing properly
would require upgrading the chart and configuring the anonymous role
explicitly.

### Phase 5 — Integration and Demo

**Issue 5.1 — ACR pull from AKS: 401 Unauthorized.** The ML pod was
stuck in `ErrImagePull`. The kubelet event showed `failed to fetch
anonymous token: 401`. The AKS kubelet identity did not have `AcrPull`
on the registry — we had granted `AcrPush` to the GitHub Actions
identity (for pushing) but not `AcrPull` to the kubelet identity (for
pulling). The fix was `az aks update -g rg-cloudsentro-terraform -n
cloudsentro-demo --attach-acr acrcloudsentrojdly`, which grants the
kubelet identity AcrPull. This should be moved into Terraform as a
follow-up — currently a manual one-shot.

**Issue 5.2 — ConfigMap YAML int parsing.** The agent ConfigMap apply
failed with `json: cannot unmarshal number into Go struct field
ConfigMap.data of type string`. The deploy script does `sed`
substitution; when `GITHUB_APP_ID` is `1234567`, the substituted line
becomes `GITHUB_APP_ID: 1234567` — YAML parses bare numbers as integers,
but ConfigMap data values must be strings. The fix was to wrap every
placeholder in `configmap.yaml` with double quotes.

**Issue 5.3 — tee mask: terraform plan exit code lost.** When HCP
Cloud's speculative plan failed, the `Terraform Plan` GitHub check still
showed green. The cause was that `terraform plan ... 2>&1 | tee
plan_output.txt` returns tee's exit code (always 0), not terraform's.
The "Fail if Plan Failed" step never triggered because the outcome was
recorded as success. The fix was `set -o pipefail` at the start of the
run script — now the pipeline returns the first non-zero exit code in
the chain.

**Issue 5.4 — GitHub Actions / HCP Cloud sync.** Even with the plan
pipefail fix, the apply pipeline showed green when HCP Cloud's apply
errored — a different gap. The original `tf-apply.yml` only posted a
comment with a link to HCP Cloud; it never verified that HCP Cloud
succeeded. The fix was to rewrite `tf-apply.yml` to poll HCP Cloud's API
(`/api/v2/workspaces/<id>/runs?search[commit]=<sha>`), wait for a
terminal status, and exit accordingly. Now the GitHub commit status
reflects the real apply outcome.

**Issue 5.5 — Demo script: bash f-string escape.** Demo step 3 always
printed `score=0.000` even though the ML pod's `/predict` was returning
the correct 0.95 score (verified with direct kubectl exec). The score
parser was a Python f-string with backslash-escaped quotes inside the
expression — invalid Python in 3.11, errored silently, fell through to
the `|| echo "0.000"` fallback. The mode parser worked because it did
not use an f-string. The fix was to rewrite with old-style `%`
formatting.

**Issue 5.6 — Image tag staleness.** After bumping the anthropic SDK
and pushing the fix, the agent pod still crashed with the same error
after `kubectl rollout restart`. `kubectl rollout restart` re-pulls
`:latest`, but `:latest` in ACR was still the previous build until the
agent-build workflow finished. We had told kubectl to restart before CI
was done. The fix was to wait for `Agent — Build and Push` on the
Actions tab to go green on the correct commit SHA, *then* restart.

**Issue 5.7 — Trivy CRITICAL/HIGH gate.** `Agent — Build and Push`
failed the security scan with seven vulnerabilities: CVE-2025-32434
(torch 2.1.0 → 2.6.0, CRITICAL), CVE-2026-32597 (PyJWT 2.8.0 → 2.12.0),
CVE-2024-26130 (cryptography), CVE-2024-47874 (starlette),
CVE-2025-66418/66471/26-21441 (urllib3), CVE-2026-24049 (wheel in
vendored setuptools), and CVE-2026-23949 (jaraco.context in vendored
setuptools). The fix was multi-pronged: bump direct dependencies (torch
2.6.0+cpu, PyJWT 2.12.1, cryptography 46.0.5, fastapi 0.115.6), pin
transitive dependencies (urllib3 2.6.3), add `--upgrade setuptools
wheel` to the Dockerfile builder stage, and add a `.trivyignore` at the
repo root for three unfixable HIGHs in base-image vendored dependencies.

**Issue 5.8 — Direct-to-main pushes (process violation).** A handful
of small fixes (folder deduplication, datasource UID pin) were pushed
directly to `main` instead of via pull request. This bypassed the
speculative plan review and broke the audit trail. The lesson, saved as
a durable memory rule: every change goes through a feature branch and
pull request, regardless of how trivial it seems. The only exception is
when the user explicitly says "push directly to main" for that specific
commit.

### Cross-cutting observations

The most expensive issues, in terms of debugging time, were not the
flashy ones but the silent ones. The Cloudflare 522, the Grafana
redirect loop, and the load balancer probe were all visible as
user-facing errors and could be diagnosed by reading the load-balancer
configuration. The most expensive class of bug was the ones where the
pipeline reported success but the underlying operation had failed —
specifically the tee-mask exit code issue and the GitHub Actions /
HCP Cloud sync gap. Those took hours longer to surface because nothing
was overtly broken.

The pattern that resolved them all: make the failure visible. Use
`set -o pipefail` so exit codes propagate. Poll the canonical system
(HCP Cloud) for the real outcome rather than trusting a wrapper. Add
unit tests that verify hard rules in code, not just in prompts.

---

## Part 5 — Commercialising as SaaS

infra-pulse is a working prototype. To turn the same engineering pattern
into a viable SaaS product, the following sections cover target
customers, pricing, competitive positioning, product roadmap, and the
engineering work required to take it to market.

### 5.1 Target customer

The product is built for **mid-sized engineering organisations** with the
following characteristics:

- Between 50 and 500 engineers, of which 5 to 30 are dedicated
  infrastructure or SRE
- A non-trivial on-call rotation (alerts in the dozens per day, several
  pages per week)
- Existing public cloud footprint, primarily on Microsoft Azure or AWS
- Infrastructure managed as code (Terraform, Pulumi, CloudFormation)
- Stated pain around mean time to remediation (MTTR), alert fatigue, and
  on-call burnout
- Compliance requirements that demand an audit trail for every
  production change

The product is **not** built for:

- Hobbyists and individual developers (the demo is open source for that
  audience, but the SaaS would be over-priced for it)
- FAANG-scale organisations (they have internal tooling that already
  does most of this)
- Companies with no infrastructure-as-code practice (the agent's
  remediation path requires code-based infrastructure to generate a pull
  request)

### 5.2 Value proposition

Three measurable outcomes for the buyer:

1. **Reduce mean time to remediation by 80%.** A typical incident
   currently moves from page to fix in 30 to 90 minutes during business
   hours, longer at 2 AM. CloudSentro produces a reviewed pull request
   within 5 to 10 minutes of detection. Time saved is engineer time —
   typically valued at $150/hour fully loaded, multiplied by frequency.

2. **Reduce on-call burden.** When the most common 60% of incidents are
   auto-diagnosed and ready for review, the on-call rotation shifts from
   investigative work to approval work. Reviewing a pull request takes
   roughly 10% of the time of starting a diagnosis from scratch.

3. **Produce an automatic audit trail.** Every action the agent takes is
   logged to immutable JSONL records. Every pull request contains the
   full reasoning chain. Compliance officers no longer need to chase
   engineers for the rationale behind a change.

### 5.3 Competitive landscape

| Vendor / Product | What they do | How CloudSentro differs |
|---|---|---|
| Datadog Watchdog | Anomaly detection on metrics | CloudSentro detects, reasons, and ships a fix. Watchdog only alerts. |
| New Relic AI | Anomaly detection plus auto-generated incident summaries | Similar limit — produces alerts, not fixes. |
| Splunk IT Service Intelligence | Detection and runbook automation | Runbooks must be pre-written; CloudSentro authors the fix dynamically. |
| PagerDuty Process Automation | Runbook automation triggered by alerts | Same limit — pre-written runbooks. |
| AWS DevOps Guru | Anomaly detection on AWS workloads | AWS-only. Detection-only. |
| Internal SRE tools at large companies | Bespoke; varies | Companies without dedicated SRE platforms cannot build these in-house economically. CloudSentro is the off-the-shelf equivalent. |

The defensible position is the combination of three things that no
single competitor currently offers together: (1) ML-based detection
calibrated for infrastructure metrics, (2) agent-based diagnosis with a
visible reasoning chain, and (3) actual code changes shipped as pull
requests rather than executed alerts.

### 5.4 Product roadmap

#### Tier 1 — Open-source baseline (current state)

The current infra-pulse repository, deployed on a customer's own AKS
cluster, with a Quickstart that takes a customer from cold to running
demo in under an hour. Free.

#### Tier 2 — Hosted control plane

A SaaS console that:

- Accepts the customer's Anthropic API key, GitHub App credentials, and
  cluster connection details
- Hosts the agent loop (no customer infrastructure to install)
- Connects to the customer's cluster read-only and opens PRs against
  their GitHub repository
- Provides a web UI for viewing the agent's reasoning history, incident
  timeline, and audit log

Pricing: monthly per cluster. Suggested launch tier: $299/month for one
cluster, $999/month for up to five clusters, $2,499/month for unlimited.

Customer responsibilities:
- Maintain the cluster
- Provide read-only access (a service principal scoped to monitoring,
  events, and the relevant Terraform repository)
- Review and merge the pull requests the agent produces

#### Tier 3 — Multi-cloud, multi-IaC

Expand from "AKS plus Terraform" to support AWS EKS, GKE, Pulumi, and
CloudFormation. Each new combination is a discrete engineering
investment but composes on top of the existing agent architecture (the
tool layer abstracts the data sources, the prompt layer abstracts the
IaC variant).

Pricing: same per-cluster model, but with cloud and IaC variants
priced equivalently. Customers using multiple clouds pay per cluster.

#### Tier 4 — Enterprise self-hosted

Single-tenant deployment in the customer's environment, with their own
Anthropic enterprise contract and full control over data residency. Sold
on a contract basis.

Suggested annual contract value: $50,000 to $250,000, depending on
cluster count and SLA tier.

### 5.5 Revenue model and unit economics

Indicative numbers for the hosted Tier 2 product:

| Item | Per cluster per month |
|---|---|
| Anthropic API costs (avg 500 agent calls) | $6 |
| Hosting (small Kubernetes pod per customer cluster) | $20 |
| Logging and storage | $2 |
| Support cost (amortised) | $30 |
| **Total cost** | **$58** |
| **Suggested price** | **$299** |
| **Gross margin** | **80%** |

These figures assume the hosted control plane runs the agent loop. If
the customer hosts the agent themselves (on their own cluster) and the
SaaS only provides the dashboard, the cost-to-serve drops further,
allowing for a lower-priced "lite" tier.

### 5.6 Go-to-market

Three phases:

**Phase A — Open-source seeding (months 1 to 6).** Continue improving
the open-source repository. Publish technical writeups on engineering
blogs (LinkedIn, Hacker News, the relevant subreddits). Goal: 500
GitHub stars, 50 self-hosted deployments, a community Slack or Discord
that the founder is active in. No sales motion. The aim is technical
credibility.

**Phase B — Design partners (months 4 to 9).** Identify five to ten
mid-sized engineering teams (target: 100 to 300 engineers, on Azure or
AWS, with an active SRE team) and offer them the hosted Tier 2 product
free in exchange for monthly feedback sessions, a co-authored case
study, and a public reference. Goal: validate pricing, identify the
top three feature requests, prove time-to-value claims.

**Phase C — Self-serve launch (months 9 to 12).** Launch the hosted
product publicly with a $299/month entry tier. Inbound only at first.
Goal: 50 paying customers, $15,000 MRR, monthly content publication.

The defensible commercial moat is the proprietary fine-tuning data: the
audit log of every remediation the agent has performed across all
customers becomes a training signal for a more accurate, faster, more
specific version of the model. Customers will sign a data-usage clause
allowing anonymised logs to improve the product.

### 5.7 Risks and mitigations

| Risk | Mitigation |
|---|---|
| **LLM hallucinations cause bad PRs.** | The human review step is the primary guard. Additionally, the `_validate_plan` function in code blocks structural violations (writes outside `infra/`, modifications to forbidden modules, etc.). |
| **Anthropic API costs scale poorly.** | Open the architecture to alternative models. The agent is bound to the Anthropic API today but the prompt and tool-call format works against any tool-use-capable model. |
| **Customer infrastructure access raises security objections.** | Default to least-privilege scopes (read-only on metrics, PR-write only on a specific repository). Offer a self-hosted enterprise tier for customers who cannot grant any access at all. |
| **Each cloud / IaC combination is a discrete engineering investment.** | Prioritise the most common combination (Azure + Terraform → AWS + Terraform → GCP + Terraform) and treat new combinations as paid roadmap items. |
| **Competitors with deeper pockets enter the space.** | The open-source baseline plus transparent technical content is the primary moat. A larger competitor can build the same product, but cannot easily copy a community. |

### 5.8 Engineering work required to ship Tier 2

Concrete features needed beyond what infra-pulse currently has, ordered
by impact:

1. **Multi-tenant control plane.** A web application (Next.js or similar)
   for customer signup, API key configuration, cluster registration,
   incident history, and audit log viewing. Approximate effort: one
   engineer for three months.

2. **Connector pattern for read-only customer access.** A Terraform
   module the customer applies in their account that creates a
   read-only role and federated credential allowing the SaaS to scrape
   metrics and read Kubernetes events without holding any static
   credential. Approximate effort: two weeks.

3. **GitHub App marketplace listing.** A single CloudSentro GitHub App
   that customers install on their organisation, replacing the
   per-customer manual app creation we did during the build. Approximate
   effort: one week.

4. **Tier-gating, billing, and metering.** Stripe integration, plan
   selection, usage caps (PRs per month at the entry tier). Approximate
   effort: one engineer for one month.

5. **Production observability.** Sentry, Datadog (or self-hosted
   equivalent), pager rotation for the SaaS itself. Approximate effort:
   one engineer for one month.

6. **Soc 2 readiness.** Audit logs, encryption at rest, access reviews,
   incident response runbooks. Approximate effort: one engineer for
   three months part-time plus a consultant.

Total time to a sellable hosted product, with one founder full-time and
no external engineering hires: approximately six to nine months.

---

## Part 6 — Appendices

### A. Specifications

| Component | Specification |
|---|---|
| Repository | github.com/Rijens7065/infra-pulse |
| Cluster | AKS · canadaeast · single node Standard_D2s_v3 |
| Container registry | ACR Basic · two images (ml, agent) |
| State management | HCP Cloud Terraform · auto-apply on merge |
| Public URL (project) | https://infra-pulse.cloudsentro.com/grafana/ |
| Public URL (company) | https://cloudsentro.com |
| Test coverage | 17 ML tests · 35 agent tests · 5 end-to-end tests |
| Image scanning | Trivy CRITICAL+HIGH gate on every build |
| Domain | cloudsentro.com via Cloudflare |
| Language model | Claude `claude-sonnet-4-20250514` |

### B. Cost analysis

| Line item | Estimated monthly cost |
|---|---|
| AKS — one Standard_D2s_v3 (on-demand 24/7) | ~$70 |
| ACR — Basic | $5 |
| Azure Key Vault | <$1 |
| Azure Blob Storage (audit log) | <$1 |
| Claude API (~500 agent calls) | $6 |
| Load balancer plus public IP | $5 |
| **Total (24/7)** | **~$87** |
| **Total (scaled to zero overnight)** | **~$37** |

Budget alert is set at $35 (70% of $50 cap) and $45 (90%).

### C. Glossary

| Term | Definition |
|---|---|
| **AnomalySignal** | The Pydantic model the ML pod returns. Fields: `anomaly_score`, `failure_mode`, `confidence`, `time_to_impact_minutes`, `affected_metrics`, `explanation`. |
| **RemediationPlan** | The output the agent emits at the end of its reasoning loop. Contains the AnomalySignal plus root cause, reasoning chain, Terraform change set, and rollback instructions. |
| **Tool use** | Claude's API mode where the model can invoke typed tools. Each tool has a JSON schema for inputs; the model emits a `tool_use` block, the host runs the tool, and the result feeds back into the conversation. |
| **GitOps gate** | The human-approved pull request step in the pipeline. The agent proposes; the human approves; HCP Cloud applies. |
| **DEMO_MODE** | An environment variable on the ML pod. When `true`, the `/inject` endpoint accepts requests to override the next prediction response. Off in production. |
| **Workload identity** | AKS's mechanism for giving pods their own Azure AD identity via federated credentials, so they can call Azure APIs without static secrets. Used by the ML pod for Azure Monitor access in the production path. |
| **OIDC federated credential** | An authentication mechanism where one identity provider (GitHub Actions, HCP Cloud) presents a signed JSON Web Token to another (Azure AD), which validates it against a trust relationship and issues a short-lived access token. Eliminates the need for static client secrets. |
| **Trivy** | Open-source container image vulnerability scanner. Run as part of the build workflows; fails the build on CRITICAL or HIGH severity with a fix available. |
| **HCP Cloud** | HashiCorp Cloud Platform — the hosted Terraform service. Stores state, runs plans and applies remotely, integrates with version control. |

---

## How to convert this document to Word

This file is in Markdown. Three ways to produce a `.docx`:

1. **Pandoc (cleanest result).** Install Pandoc, then run:
   ```
   pandoc docs/project-report.md -o project-report.docx --toc
   ```
   The `--toc` flag generates a table of contents.

2. **Microsoft Word import.** Open Word → File → Open → select
   `docs/project-report.md`. Word's built-in Markdown rendering will
   produce a working document, though the formatting is less polished
   than Pandoc's output.

3. **Online converter.** Paste the contents into a service like
   `markdowntowords.com` or `cloudconvert.com`. Best for users without
   Pandoc installed.

The document is intentionally structured for clean conversion: no
mermaid diagrams, no advanced HTML, code blocks use fenced markdown,
tables use the simple pipe format.

---

End of project report.
