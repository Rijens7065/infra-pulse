# infra/ — Terraform Context

> Read this before touching any file in infra/

## What this module does
Provisions all Azure infrastructure for CloudSentro using Terraform.
Runs remotely on HCP Cloud. Apply is manual — nothing deploys without approval.

## Critical rules
- Provider must use `use_oidc = true` — never use client_secret
- All resource names with global uniqueness requirement get a random 4-char suffix
- Everything goes in `rg-cloudsentro-terraform` — never create resources outside this RG
- Budget module must never be modified after creation
- Never hardcode subscription ID, tenant ID, or client ID — use variables

## Provider authentication
```hcl
provider "azurerm" {
  features {}
  use_oidc        = true
  client_id       = var.client_id
  tenant_id       = var.tenant_id
  subscription_id = var.subscription_id
}
```

## HCP Cloud backend
```hcl
terraform {
  cloud {
    organization = "cloudsentro"
    workspaces {
      name = "infra-pulse"
    }
  }
}
```

## Module dependency order
```
resource_group
      ↓
acr → aks → keyvault → budget
                ↓
            identity (needs aks.oidc_issuer_url)
                ↓
Phase 4: ingress → prometheus → grafana → nsg → dns
```

## Module inputs/outputs

### resource_group
- outputs: id, name, location

### acr
- inputs: resource_group_name, location
- outputs: login_server, id, name

### aks
- inputs: resource_group_name, location
- outputs: cluster_name, kube_config, oidc_issuer_url, node_resource_group

### keyvault
- inputs: resource_group_name, location, tenant_id
- outputs: vault_uri, id, name

### budget
- inputs: resource_group_id, alert_email
- outputs: budget_id

### identity
- inputs: resource_group_id, aks_id, keyvault_id, oidc_issuer_url
- outputs: ml_sp_client_id, agent_sp_client_id

## Files in this module
```
infra/
├── main.tf          ← calls all modules
├── providers.tf     ← azurerm, azuread, cloudflare, helm, kubernetes
├── variables.tf     ← all input variables
├── outputs.tf       ← key values exposed after apply
└── modules/
    ├── resource_group/
    ├── acr/
    ├── aks/
    ├── keyvault/
    ├── budget/
    ├── identity/
    ├── ingress/     ← Phase 4
    ├── prometheus/  ← Phase 4
    ├── grafana/     ← Phase 4
    ├── nsg/         ← Phase 4
    └── dns/         ← Phase 4
```

## What NOT to touch
- Never edit budget module after it is applied
- Never change oidc_issuer_url — it breaks workload identity
- Never add client_secret to the provider block
- Never use count or for_each on AKS module
