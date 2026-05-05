# Architectural Decisions

## Why these choices were made — do not change without good reason.

---

### Auth: OIDC Federated Credentials (not Service Principal + secret)
No client secret exists anywhere. GitHub Actions exchanges an OIDC token for a short-lived Azure token. AKS pods use Workload Identity Federation. This eliminates credential rotation and secret leakage risk.

### Terraform runs: HCP Cloud remote (not local)
Terraform state is stored encrypted in HCP Cloud. Runs happen remotely. Apply method is manual — nothing deploys without human approval. This is the GitOps gate.

### AKS nodes: Standard_B2s Spot
Reduces cost to ~$10/mo vs ~$70/mo for on-demand. Acceptable for a prototype. If a node is evicted, AKS reschedules pods automatically. Not suitable for production.

### ML model: LSTM Autoencoder + Isolation Forest (not just LLM)
Raw metrics fed directly to an LLM produce noisy, expensive results. The ML model pre-classifies the failure mode with a confidence score. Claude then reasons from a structured signal — cheaper, faster, more accurate.

### ML model: CPU-only PyTorch
Standard_B2s has no GPU. Use torch==2.1.0+cpu build. Model must stay under 100MB. Inference must complete in under 200ms.

### Agent: tool_use loop (not single prompt)
Claude needs to gather context from multiple sources (Azure Monitor, kubectl, GitHub history) before reasoning. Tool use allows multi-step investigation. Max 10 turns to prevent infinite loops.

### GitHub PRs: GitHub App (not PAT)
Personal Access Tokens are tied to a user account and expire. A GitHub App authenticates as an installation with 1-hour tokens scoped to the repo. PRs appear from `cloudsentro-bot` not a personal account.

### DNS + TLS: Cloudflare (not Azure DNS + cert-manager)
Cloudflare provides free automatic TLS, DDoS protection, and hides the AKS public IP. No cert-manager needed on AKS. NSG only allows Cloudflare IP ranges inbound.

### Grafana: anonymous read-only access
This is a public prototype demo. Anonymous Viewer access lets clients see the dashboard without logging in. Admin access requires the password stored in Key Vault.

### Budget: $50/month hard limit
Azure Budget alert at 70% ($35 warn) and 90% ($45 critical). Spot nodes, Basic ACR, free AKS control plane, and CPU-only ML keep costs under $40/mo normally.
