# Phase Status

> Update this file as each phase completes.
> Claude Code reads this to know what has been built and what hasn't.

---

## Current status

| Phase | Status | Started | Completed |
|---|---|---|---|
| Phase 1 — Foundation | ✅ Complete | 2026-05-03 | 2026-05-03 |
| Phase 2 — ML Model | ✅ Complete | 2026-05-04 | 2026-05-04 |
| Phase 3 — Agent | ✅ Complete | 2026-05-05 | 2026-05-05 |
| Phase 4 — Dashboard | ✅ Complete | 2026-05-08 | 2026-05-09 |
| Phase 5 — Integration | ✅ Complete | 2026-05-09 | 2026-05-10 |

The full end-to-end demo works:
- ML pod served at `ml-service.cloudsentro:8000`
- Agent pod polls every 300s, opens real GitHub PRs
- Grafana dashboard live at `https://infra-pulse.cloudsentro.com/grafana/`
- Prometheus scraping both `ml-service` and `agent-service` pods
- Two demo PRs opened by the agent: #17 and #18 (the second one explicitly noted the first remediation was insufficient and escalated)

---

## Phase 1 — Foundation
**Goal:** git push → HCP plan → approve → Azure deploys

### Checklist
- [x] infra/providers.tf
- [x] infra/variables.tf (`principal_id` + `terraform_runner_principal_id` split — see decisions.md)
- [x] infra/main.tf
- [x] infra/outputs.tf
- [x] infra/modules/resource_group/
- [x] infra/modules/acr/ (+ AcrPush role assignment for GHA identity)
- [x] infra/modules/aks/
- [x] infra/modules/keyvault/ (+ KV Secrets Officer for HCP Cloud identity + time_sleep for RBAC propagation)
- [x] infra/modules/budget/
- [x] infra/modules/identity/ — **deferred**, requires Application Administrator role in Entra ID
- [x] .github/workflows/tf-plan.yml (pipefail fix for accurate exit codes)
- [x] .github/workflows/tf-apply.yml (polls HCP Cloud for the real apply outcome)
- [x] .github/workflows/ml-build.yml (with Trivy scan)
- [x] .github/workflows/agent-build.yml (with Trivy scan)
- [x] First push to main triggers HCP Cloud plan and apply
- [x] All resources visible in Azure portal

### Notes
- azurerm 4.x quirks documented in docs/decisions.md
- VM size: `Standard_B2s` is not in our subscription's allowed SKU list for canadaeast; `Standard_B2s_v2` has 0 vCPU quota. Switched to `Standard_D2s_v3`.
- LB rule + probe quirks: AKS cloud-controller created the LB with `backendPort=80` + `enableFloatingIp=null` and an HTTP probe on `/` that returned 404 from the ingress controller. Fixed in `ingress` module: `externalTrafficPolicy: Local` + `service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol: tcp`.

---

## Phase 2 — ML Model
**Goal:** Model trained >85% accuracy, Docker image builds

### Checklist
- [x] ml/data/generator.py (30-day synthetic, 7 channels, 8-15 anomaly windows)
- [x] ml/model/lstm_autoencoder.py
- [x] ml/model/failure_classifier.py (IsolationForest + RandomForest + AnomalySignal)
- [x] ml/train.py — **99.23% test accuracy** (target >85%)
- [x] ml/serving/app.py (FastAPI, /health /predict /metrics /inject)
- [x] ml/serving/azure_monitor_client.py
- [x] ml/k8s/ manifests (non-root, read-only fs, drop ALL caps)
- [x] ml/Dockerfile (multi-stage, model trained inside the build)
- [x] ml/tests/ — 17 tests, all green

### Notes
- Training runs inside the Docker build (Stage 2 = trainer) — artifacts are baked into the runtime image, not committed to git
- The `/inject` endpoint is DEMO_MODE-gated and overrides the next response with a specified failure mode + intensity

---

## Phase 3 — Agent
**Goal:** Agent pod opens real GitHub PR for detected anomaly

### Checklist
- [x] agent/models.py (Pydantic v2: AnomalySignal, TerraformChange, RemediationPlan, AgentAction)
- [x] agent/tools.py (7 tools with input schemas and runtime dispatch)
- [x] agent/prompts.py (system prompt enforces hard rules)
- [x] agent/agent.py (run_loop, FastAPI /health and /metrics)
- [x] agent/actions/github_app_auth.py (JWT RS256, 1h installation tokens, auto-refresh)
- [x] agent/k8s/ manifests (workload identity-ready, non-root, read-only fs)
- [x] agent/Dockerfile (multi-stage, Python 3.11-slim)
- [x] agent/tests/ — 35 tests, all green
- [x] GitHub App created and installed on the repo
- [x] First agent-opened PR observed (PR #17 OOM_LEAK remediation)

### Notes
- Agent uses anthropic SDK 0.49.0 (older versions break with httpx 0.28+)
- Secrets loading: ENV vars first (demo path with K8s secret), Key Vault fallback (production path with workload identity)
- The agent showed temporal reasoning on PR #18: noted the previous PR was insufficient and escalated the fix

---

## Phase 4 — Dashboard
**Goal:** https://infra-pulse.cloudsentro.com shows live Grafana

### Checklist
- [x] infra/modules/ingress/ (NGINX 4.8.3, Cloudflare-aware headers, TCP probe annotation)
- [x] infra/modules/prometheus/ (server-only, 7d retention, custom scrape configs)
- [x] infra/modules/grafana/ (7.0.19, anonymous Viewer, pinned datasource UID = "prometheus")
- [x] infra/modules/nsg/ (Cloudflare-only ingress + admin IP)
- [x] infra/modules/dns/ (A record + www CNAME, proxied)
- [x] dashboard/grafana/cloudsentro-dashboard.json (10 panels across 4 rows)
- [x] dashboard/static/ landing page
- [x] infra-pulse.cloudsentro.com loads and TLS works via Cloudflare
- [x] Grafana shows live `cloudsentro_anomaly_score` and the predictions counter

### Notes
- Grafana dashboards load via sidecar only (not filesystem provider) — `defaultFolderName: "CloudSentro"` puts them in one folder
- Prometheus datasource UID pinned to `prometheus` so dashboard JSON references resolve

---

## Phase 5 — Integration
**Goal:** 5-min demo works end-to-end, LinkedIn post ready

### Checklist
- [x] scripts/inject_anomaly.py (kubectl port-forward + POST /inject)
- [x] scripts/deploy.sh (renders k8s manifests with env values, applies, waits for rollout)
- [x] scripts/demo.sh (5-step orchestrated demo)
- [x] tests/e2e/test_pipeline.py (5 sequential tests, auto-skip without kubectl)
- [x] Trivy CRITICAL+HIGH scan on both build workflows
- [x] docs/architecture.md, docs/decisions.md
- [x] docs/handbook.md (full project handbook)
- [x] docs/issues-encountered.md (project retrospective)
- [x] docs/linkedin-post.md
- [x] dashboard/static/ multi-page site for cloudsentro.com

### Notes
- AcrPull for kubelet was wired manually via `az aks update --attach-acr`; should be added to Terraform in a follow-up
- One agent loop iteration through Claude takes ~30-60s wall clock
