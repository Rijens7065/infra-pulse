variable "resource_group_id" {
  type        = string
  description = "Resource group ID for Monitoring Reader role scope."
}

variable "aks_id" {
  type        = string
  description = "AKS cluster resource ID for AKS Cluster User role scope."
}

variable "keyvault_id" {
  type        = string
  description = "Key Vault resource ID for Key Vault Secrets User role scope."
}

variable "oidc_issuer_url" {
  type        = string
  description = "AKS OIDC issuer URL used as the federated credential issuer."
}

# ── ML service principal ────────────────────────────────────────────────────

resource "azuread_application" "ml" {
  display_name = "cloudsentro-ml-sp"
}

resource "azuread_service_principal" "ml" {
  client_id = azuread_application.ml.client_id
}

resource "azuread_application_federated_identity_credential" "ml" {
  application_id = azuread_application.ml.id
  display_name   = "cloudsentro-ml-aks-federated"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = var.oidc_issuer_url
  subject        = "system:serviceaccount:cloudsentro:ml-service-account"
}

# ── Agent service principal ─────────────────────────────────────────────────

resource "azuread_application" "agent" {
  display_name = "cloudsentro-agent-sp"
}

resource "azuread_service_principal" "agent" {
  client_id = azuread_application.agent.client_id
}

resource "azuread_application_federated_identity_credential" "agent" {
  application_id = azuread_application.agent.id
  display_name   = "cloudsentro-agent-aks-federated"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = var.oidc_issuer_url
  subject        = "system:serviceaccount:cloudsentro:agent-service-account"
}

# ── RBAC: ML SP ─────────────────────────────────────────────────────────────

resource "azurerm_role_assignment" "ml_monitoring_reader" {
  scope                = var.resource_group_id
  role_definition_name = "Monitoring Reader"
  principal_id         = azuread_service_principal.ml.object_id
}

# ── RBAC: Agent SP ──────────────────────────────────────────────────────────

resource "azurerm_role_assignment" "agent_monitoring_reader" {
  scope                = var.resource_group_id
  role_definition_name = "Monitoring Reader"
  principal_id         = azuread_service_principal.agent.object_id
}

resource "azurerm_role_assignment" "agent_aks_cluster_user" {
  scope                = var.aks_id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = azuread_service_principal.agent.object_id
}

resource "azurerm_role_assignment" "agent_keyvault_secrets_user" {
  scope                = var.keyvault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azuread_service_principal.agent.object_id
}
