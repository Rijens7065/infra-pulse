# Phase Status

> Update this file as each phase completes.
> Claude Code reads this to know what has been built and what hasn't.

---

## Current status

| Phase | Status | Started | Completed |
|---|---|---|---|
| Phase 1 — Foundation | ✅ Complete (pending first push) | 2026-05-03 | 2026-05-03 |
| Phase 2 — ML Model | ⏳ Not started | | |
| Phase 3 — Agent | ⏳ Not started | | |
| Phase 4 — Dashboard | ⏳ Not started | | |
| Phase 5 — Integration | ⏳ Not started | | |

---

## Phase 1 — Foundation
**Goal:** git push → HCP plan → approve → Azure deploys

### Checklist
- [x] infra/providers.tf
- [x] infra/variables.tf
- [x] infra/main.tf
- [x] infra/outputs.tf
- [x] infra/modules/resource_group/
- [x] infra/modules/acr/
- [x] infra/modules/aks/
- [x] infra/modules/keyvault/
- [x] infra/modules/budget/
- [x] infra/modules/identity/
- [x] .github/workflows/tf-plan.yml
- [x] .github/workflows/tf-apply.yml
- [x] .github/workflows/ml-build.yml
- [x] .github/workflows/agent-build.yml
- [x] terraform validate passes
- [ ] First git push triggers HCP plan
- [ ] First apply succeeds

### Notes
- azurerm 3.117.1: `auto_scaling_enabled` / `enable_auto_scaling` removed from `default_node_pool`; autoscaling is implicit when `min_count` + `max_count` are set.
- azurerm 3.117.1: Spot instance attributes (`priority`, `eviction_policy`, `spot_max_price`) removed from `default_node_pool` because Azure requires system node pools to use Regular VMs. A spot user node pool will be added in Phase 4.
- kubernetes/helm providers use `~/.kube/config` placeholder in Phase 1; updated to AKS data source in Phase 4.
- `terraform validate` passes locally with `terraform init -backend=false`.

---

## Phase 2 — ML Model
**Goal:** Model trained >85% accuracy, Docker image builds

### Checklist
- [ ] ml/data/generator.py (synthetic data)
- [ ] ml/model/lstm_autoencoder.py
- [ ] ml/model/failure_classifier.py
- [ ] ml/train.py (accuracy >85%)
- [ ] ml/serving/app.py (FastAPI)
- [ ] ml/serving/azure_monitor_client.py
- [ ] ml/k8s/ manifests
- [ ] ml/Dockerfile builds successfully
- [ ] ml/tests/ all green
- [ ] ml/model/artifacts/ saved

### Notes
_Add notes here as phase progresses_

---

## Phase 3 — Agent
**Goal:** Agent pod opens real GitHub PR for detected anomaly

### Checklist
- [ ] agent/models.py
- [ ] agent/tools.py (7 tools)
- [ ] agent/prompts.py (system prompt)
- [ ] agent/agent.py (main loop)
- [ ] agent/actions/github_app_auth.py
- [ ] agent/k8s/ manifests
- [ ] agent/Dockerfile builds successfully
- [ ] agent/tests/ all green
- [ ] GitHub App created and installed

### Notes
_Add notes here as phase progresses_

---

## Phase 4 — Dashboard
**Goal:** https://infra-pulse.cloudsentro.com shows live Grafana

### Checklist
- [ ] infra/modules/ingress/
- [ ] infra/modules/prometheus/
- [ ] infra/modules/grafana/
- [ ] infra/modules/nsg/
- [ ] infra/modules/dns/
- [ ] dashboard/grafana/cloudsentro-dashboard.json
- [ ] dashboard/static/index.html
- [ ] infra-pulse.cloudsentro.com loads
- [ ] Grafana shows live anomaly_score

### Notes
_Add notes here as phase progresses_

---

## Phase 5 — Integration
**Goal:** 5-min demo works end-to-end, LinkedIn post ready

### Checklist
- [ ] scripts/inject_anomaly.py
- [ ] scripts/demo.sh
- [ ] tests/e2e/test_pipeline.py all green
- [ ] Security hardening applied
- [ ] docs/architecture.md final
- [ ] README.md final
- [ ] docs/linkedin-post.md written
- [ ] Loom recording done

### Notes
_Add notes here as phase progresses_
