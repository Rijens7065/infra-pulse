# agent/ — Claude Agent Context

> Read this before touching any file in agent/

## What this module does
A Claude-powered reasoning agent that polls the ML model, investigates
anomalies using tool calls, and opens GitHub PRs with Terraform fixes.
Runs as a pod in AKS namespace `cloudsentro`, polls every 300 seconds.

## Critical rules
- Claude API key comes from Key Vault at startup — never in env vars or code
- GitHub authentication uses GitHub App (not PAT) — tokens are 1-hour, auto-refreshed
- Max 10 tool_use turns per reasoning loop — never allow infinite loops
- Only open a PR if confidence > 0.75
- SECURITY_DRIFT anomaly → log only, never open PR, flag for human review
- Never delete Azure resources, never modify RBAC, never touch budget module
- All actions must be logged to Azure Blob Storage audit trail

## Model used
```
claude-sonnet-4-20250514
```

## The 7 tools (never rename these)
```
get_current_anomaly_signal     → GET ml-service:8000/predict
get_azure_monitor_metrics      → azure-monitor-query
get_recent_infra_changes       → GitHub commits on infra/ path
get_kubernetes_events          → kubectl Warning events
read_terraform_file            → GitHub contents API
create_remediation_pr          → opens real GitHub PR
log_audit_event                → Azure Blob append JSONL
```

## PR format — all 5 sections required
```markdown
## Anomaly Report
## Root Cause
## Reasoning Chain  (in <details> collapsible)
## Proposed Changes
## Rollback Instructions
```

## PR branch naming
```
fix/agent-{YYYYMMDD-HHmm}-{failure_mode_lowercase}
```

## PR labels
```
agent-remediation, terraform, {failure_mode_lowercase}
```

## Audit log location
```
Azure Blob Storage
Container: agent-audit-log
Blob: audit/{YYYY-MM-DD}.jsonl
```

## Files in this module
```
agent/
├── agent.py                  ← main loop + health endpoint
├── tools.py                  ← 7 tool definitions + implementations
├── prompts.py                ← system prompt + user message template
├── models.py                 ← Pydantic models
├── actions/
│   └── github_app_auth.py   ← GitHub App JWT + installation token
├── k8s/
│   ├── namespace.yaml
│   ├── serviceaccount.yaml
│   ├── configmap.yaml        ← non-secret env vars
│   ├── deployment.yaml
│   └── service.yaml
├── tests/
│   └── test_agent.py        ← all mocked, no real API calls
├── Dockerfile
└── requirements.txt
```

## Kubernetes identity
```
ServiceAccount: agent-service-account
Namespace: cloudsentro
Annotation: azure.workload.identity/client-id: <terraform output agent_sp_client_id>
Label on pod: azure.workload.identity/use: "true"
RBAC:
  - Monitoring Reader on rg-cloudsentro-terraform
  - AKS Cluster User on AKS cluster
  - Key Vault Secrets User on Key Vault
```

## Key Vault secrets the agent reads at startup
```
claude-api-key              → Anthropic API key
github-app-private-key      → GitHub App PEM private key
```

## Environment variables (non-secret, from ConfigMap)
```
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_KEYVAULT_URL
AZURE_AKS_RESOURCE_ID
GITHUB_REPO_OWNER           = <your GitHub username>
GITHUB_REPO_NAME            = infra-pulse
GITHUB_APP_ID               = <GitHub App ID — set after creating the App>
AZURE_SUBSCRIPTION_ID       = <set in HCP Cloud: ARM_SUBSCRIPTION_ID>
AZURE_RESOURCE_GROUP        = rg-cloudsentro-terraform
```

## Health endpoint
```
GET /health → {status, last_run_at, last_anomaly_score, uptime_seconds}
Port: 8001
```

## What NOT to touch
- Never change tool names — prompts.py references them by name
- Never change AnomalySignal field names — matches ml/ contract
- Never store Claude API key anywhere except Key Vault
- Never use PAT for GitHub — always GitHub App
- Never remove the 10-turn limit on the tool_use loop
- Never skip logging to audit trail — every action must be logged
