# CloudSentro — Autonomous Infrastructure Intelligence

> An AI system that watches your Azure infrastructure, predicts failures using ML, and fixes them autonomously through a zero-secret GitOps pipeline.

[![Terraform](https://img.shields.io/badge/Terraform-1.6+-7B42BC?logo=terraform&logoColor=white)](https://www.terraform.io)
[![Azure](https://img.shields.io/badge/Azure-AKS-0089D0?logo=microsoft-azure&logoColor=white)](https://azure.microsoft.com)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Claude AI](https://img.shields.io/badge/Claude-claude--sonnet--4--20250514-FF6B35)](https://anthropic.com)
[![License](https://img.shields.io/badge/License-MIT-22c55e)](LICENSE)

**Live demo:** https://infra-pulse.cloudsentro.com/grafana/
**Company site:** https://cloudsentro.com

> **New here?** Start with the [**handbook**](docs/handbook.md) — the
> as-built, end-to-end guide. Or jump to the [project
> retrospective](docs/issues-encountered.md) if you want the war stories
> first.

---

## How it works

1. **Collect** — An Azure Monitor client polls AKS metrics every 60 seconds across 7 channels: CPU, memory, network I/O, pod restarts, HTTP latency, and hourly cost.
2. **Detect** — A PyTorch LSTM autoencoder reconstructs the signal; an Isolation Forest + Random Forest classifier labels it as one of 6 failure modes with a confidence score.
3. **Reason** — When confidence exceeds 75%, a Claude claude-sonnet-4-20250514 agent runs a tool-use loop to gather context from Azure Monitor, Kubernetes events, and recent Terraform commits.
4. **Fix** — The agent opens a GitHub PR containing a Terraform change, rollback instructions, and a full step-by-step reasoning chain — no human writes any code.
5. **Deploy** — A human approves the PR in HCP Cloud, `terraform apply` runs remotely, and the infrastructure heals itself.

---

## What makes this different

- **Zero secrets** — Authentication uses AKS Workload Identity Federation (OIDC); no keys, passwords, or tokens appear anywhere in the codebase or CI environment variables.
- **Explainable AI** — Every remediation PR includes a collapsible `<details>` block showing exactly what Claude observed, inferred, and decided — full audit trail in Git.
- **Budget-safe** — Hard-coded $50/month ceiling with alerts at 70% and 90%; the entire stack runs on B2s Spot instances and Azure free-tier services for ~$37/month.
- **Human in the loop** — The agent never applies infrastructure changes autonomously; every fix requires a human to approve the Terraform plan in HCP Cloud UI.

---

## Failure modes detected

| Class | Signal |
|---|---|
| `NORMAL` | Healthy baseline |
| `OOM_LEAK` | Memory RSS grows linearly toward pod limit |
| `CPU_THROTTLE` | CPU jumps to 95–100%, latency multiplies 3–5× |
| `NETWORK_DEGRADATION` | Throughput drops 60–80%, latency +200–400% |
| `COST_SPIKE` | Spend exceeds 7-day rolling average by >40% |
| `SECURITY_DRIFT` | Abnormal API patterns, new outbound IPs — logged only, no PR opened |

---

## Tech stack

| Tool | Purpose | Why |
|---|---|---|
| Terraform + HCP Cloud | Infrastructure as code, remote runs | Version-controlled infra with full audit trail and manual apply gate |
| Azure Kubernetes Service | Container orchestration | Managed K8s with native Workload Identity Federation support |
| Azure Container Registry | Docker image storage | Private registry co-located with AKS; no credentials needed with OIDC |
| Azure Key Vault | Secret storage at runtime | Only place secrets exist; read via workload identity at pod startup |
| PyTorch LSTM | Anomaly detection autoencoder | Learns normal diurnal patterns on CPU; flags deviations in <200ms |
| scikit-learn | Multi-class failure classifier | Fast Isolation Forest + Random Forest inference on Standard_B2s |
| FastAPI | ML serving + agent health | Async, lightweight, Prometheus `/metrics` endpoint built in |
| Claude claude-sonnet-4-20250514 | Reasoning + tool use | Best-in-class structured agentic reasoning with typed tool calls |
| GitHub Actions | CI/CD pipelines | Native OIDC federation with Azure; no secrets stored in GitHub |
| Cloudflare | DNS + TLS proxy | Free CDN, shields AKS public IP, automatic HTTPS certificates |
| Grafana + Prometheus | Observability dashboard | Live anomaly score, AKS health, cost tracking in one view |

---

## GitOps pipeline

```
PR opened  →  GitHub Actions runs terraform plan  →  plan posted as PR comment
     ↓
Merged to main  →  HCP Cloud auto-triggers terraform apply
     ↓
GitHub Actions posts commit comment with link to HCP Cloud run
```

Authentication is OIDC end-to-end — no client secrets, no service principal keys, no stored tokens.

---

## Quick start

```bash
# 1. Clone and copy the environment template
git clone https://github.com/cloudsentro/infra-pulse.git && cd infra-pulse && cp .env.example .env

# 2. Open a PR — GitHub Actions triggers a Terraform plan posted as a PR comment
git checkout -b feature/my-change && git push origin feature/my-change

# 3. Merge the PR — HCP Cloud auto-applies, GitHub Actions posts a run link
# Review the apply at:
open https://app.terraform.io/app/cloudsentro/workspaces/infra-pulse
```

---

## Phase progress

- [ ] **Phase 1** — Foundation (Terraform modules, GitHub Actions, repo structure)
- [ ] **Phase 2** — ML Model (synthetic data, LSTM autoencoder, FastAPI serving)
- [ ] **Phase 3** — Claude Agent (tool use, reasoning, GitHub PR creation)
- [ ] **Phase 4** — Dashboard (Grafana, NGINX ingress, DNS, landing page)
- [ ] **Phase 5** — Integration (E2E tests, demo script, security hardening)

---

## Repository structure

```
infra-pulse/
├── infra/                  Terraform modules (AKS, ACR, Key Vault, identity)
├── ml/                     PyTorch LSTM anomaly detector + FastAPI server
├── agent/                  Claude reasoning agent + GitHub PR tools
├── dashboard/              Grafana dashboards and static landing page
├── scripts/                Anomaly injection + demo automation
├── tests/e2e/              End-to-end test suite
└── .github/workflows/      tf-plan, tf-apply, ml-build, agent-build
```

---

## Security posture

- OIDC federated credentials — zero long-lived secrets in CI or code
- AKS pods run non-root, read-only filesystem, drop ALL Linux capabilities
- Workload Identity Federation — ML and Agent pods authenticate to Azure without env var secrets
- Only two secrets in the entire system: Claude API key and GitHub App private key, stored in Azure Key Vault
- Agent hard rules: never deletes resources, never modifies IAM, never opens a PR on `SECURITY_DRIFT`

---


