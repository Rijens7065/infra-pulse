# CLAUDE.md — CloudSentro Project Context

> This file is read automatically by Claude Code on every session.
> Do not delete it. Keep it updated as the project evolves.

---

## What this project is

CloudSentro is an Autonomous Infrastructure Intelligence Platform.
It trains an ML model on AKS metrics, uses Claude AI to reason about
failures, and fixes them by opening real Terraform PRs through a
zero-secret GitOps pipeline. The live dashboard runs at
infra-pulse.cloudsentro.com.

---

## Key project values — use these everywhere

```
PROJECT_NAME     = cloudsentro
REPO_NAME        = infra-pulse
AZURE_REGION     = canadaeast
RESOURCE_GROUP   = rg-cloudsentro-terraform
BOOTSTRAP_RG     = rg-cloudsentro-bootstrap
TF_ORG           = cloudsentro
TF_WORKSPACE     = infra-pulse
PUBLIC_URL       = infra-pulse.cloudsentro.com
DOMAIN           = cloudsentro.com
SUBDOMAIN        = infra-pulse
AKS_VM_SIZE      = Standard_D2s_v3 (Spot)
BUDGET_LIMIT     = $50 USD/month
CLAUDE_MODEL     = claude-sonnet-4-20250514
```

---

## Azure identity values

> These are set as HCP Cloud workspace variables and GitHub secrets — never commit real values here.

```
SUBSCRIPTION_ID  = <set in HCP Cloud: ARM_SUBSCRIPTION_ID>
TENANT_ID        = <set in HCP Cloud: ARM_TENANT_ID>
CLIENT_ID        = <set in HCP Cloud: ARM_CLIENT_ID>
PRINCIPAL_ID     = <object ID of mi-cloudsentro-terraform — find in Azure portal>
MANAGED_IDENTITY = mi-cloudsentro-terraform
```

---

## Security rules — never break these

- No client secrets anywhere — auth is OIDC federated credentials only
- No hardcoded credentials in any file
- All sensitive values come from HCP Cloud workspace variables or GitHub secrets
- GitHub Actions workflows must have: `permissions: id-token: write, contents: read`
- The azurerm provider must use `use_oidc = true` — never use client_secret
- All Kubernetes pods run as non-root, read-only filesystem, drop ALL capabilities
- AKS Workload Identity Federation for ML and Agent pods — no secrets in env vars
- Only secret in the system: Claude API key and GitHub App private key in Key Vault

---

## Tech stack

| Layer | Technology |
|---|---|
| IaC | Terraform + HCP Cloud (remote runs, manual apply) |
| CI/CD | GitHub Actions |
| Auth | OIDC Federated Credentials + AKS Workload Identity |
| Containers | Docker → ACR → AKS (Standard_B2s Spot) |
| ML | PyTorch LSTM + scikit-learn Isolation Forest (CPU only) |
| Agent | Claude claude-sonnet-4-20250514 with tool_use |
| DNS | Cloudflare (proxied, free TLS) |
| Dashboard | Grafana + Prometheus on AKS |
| Domain | cloudsentro.com |

---

## Repo structure

```
infra-pulse/
├── CLAUDE.md                      ← you are here
├── cloudsentro-blueprint.md       ← full project blueprint
├── README.md
├── .gitignore
├── .env.example
├── infra/                         ← all Terraform code
│   ├── main.tf
│   ├── providers.tf
│   ├── variables.tf
│   ├── outputs.tf
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
├── ml/                            ← ML anomaly detection model
│   ├── data/
│   ├── model/
│   ├── serving/
│   ├── k8s/
│   ├── train.py
│   ├── Dockerfile
│   └── requirements.txt
├── agent/                         ← Claude reasoning agent
│   ├── agent.py
│   ├── tools.py
│   ├── prompts.py
│   ├── models.py
│   ├── actions/
│   ├── k8s/
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/
│   ├── grafana/
│   └── static/
├── scripts/
│   ├── inject_anomaly.py
│   └── demo.sh
├── tests/
│   └── e2e/
└── .github/
    └── workflows/
        ├── tf-plan.yml
        ├── tf-apply.yml
        ├── ml-build.yml
        └── agent-build.yml
```

---

## ML model — 6 failure classes

| Class | Signal |
|---|---|
| NORMAL | Healthy baseline |
| OOM_LEAK | Memory RSS grows linearly toward pod limit |
| CPU_THROTTLE | CPU jumps to 95-100%, latency multiplies 3-5x |
| NETWORK_DEGRADATION | Throughput drops 60-80%, latency +200-400% |
| COST_SPIKE | Spend exceeds 7-day rolling average by >40% |
| SECURITY_DRIFT | Abnormal API patterns, new outbound IPs |

---

## Agent hard rules — never break these

- Never delete Azure resources or Kubernetes namespaces
- Never modify IAM, RBAC, or identity configurations
- Never touch the budget alert Terraform module
- SECURITY_DRIFT anomaly → log only, never open a PR
- Only open a GitHub PR if confidence > 75%
- Always read the current Terraform file before proposing changes
- Always include rollback instructions in every PR

---

## GitHub Actions — how authentication works

```yaml
permissions:
  id-token: write    # required for OIDC
  contents: read

steps:
  - uses: azure/login@v2
    with:
      client-id: ${{ secrets.AZURE_CLIENT_ID }}
      tenant-id: ${{ secrets.AZURE_TENANT_ID }}
      subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      # No client-secret — OIDC is used automatically
```

---

## Terraform provider — how authentication works

```hcl
provider "azurerm" {
  features {}
  use_oidc        = true
  client_id       = var.client_id
  tenant_id       = var.tenant_id
  subscription_id = var.subscription_id
  # No client_secret — OIDC token used automatically
}
```

---

## HCP Cloud workspace variables set

| Key | Type | Sensitive |
|---|---|---|
| ARM_CLIENT_ID | env | yes |
| ARM_TENANT_ID | env | yes |
| ARM_SUBSCRIPTION_ID | env | yes |
| ARM_USE_OIDC | env | no |
| TF_VAR_alert_email | env | no |
| TF_VAR_admin_ip | env | no |
| TF_VAR_cloudflare_zone_id | env | yes |
| TF_VAR_cloudflare_api_token | env | yes |

---

## GitHub repository secrets set

| Secret | Purpose |
|---|---|
| TF_CLOUD_TOKEN | HCP Cloud API token for GitHub Actions |
| AZURE_CLIENT_ID | Managed identity client ID |
| AZURE_TENANT_ID | Azure tenant ID |
| AZURE_SUBSCRIPTION_ID | Azure subscription ID |

---

## Build phases

| Phase | Status | What gets built |
|---|---|---|
| Phase 1 | ⏳ | Terraform modules, GitHub Actions, repo structure |
| Phase 2 | ⏳ | ML model — synthetic data, LSTM, FastAPI |
| Phase 3 | ⏳ | Claude agent — reasoning, tool calls, GitHub PRs |
| Phase 4 | ⏳ | Grafana, NGINX ingress, DNS, landing page |
| Phase 5 | ⏳ | E2E tests, demo script, security hardening |

---

## Important notes for Claude Code

- Always read this file and cloudsentro-blueprint.md before starting any task
- Execute one phase at a time — do not jump ahead
- After each phase ask for confirmation before proceeding
- If a resource name needs to be globally unique in Azure, add a random 4-char suffix
- Terraform modules go in infra/modules/ — one folder per resource type
- All Docker images must be CPU-only (no GPU on Standard_B2s)
- PyTorch must use the CPU-only build: torch==2.1.0+cpu
- Never use WidthType.PERCENTAGE in any Terraform table configurations
- Budget is $50/month — always choose free tiers and spot instances
