variable "resource_group_name" {
  type        = string
  description = "Resource group to deploy into."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "tenant_id" {
  type        = string
  sensitive   = true
  description = "Azure tenant ID — required by Key Vault."
}

variable "environment" {
  type        = string
  default     = "demo"
  description = "Environment name for tagging."
}

variable "project" {
  type        = string
  default     = "cloudsentro"
  description = "Project name for tagging."
}

variable "secrets_writer_principal_id" {
  type        = string
  sensitive   = true
  description = "Principal ID granted Key Vault Secrets Officer — needed for Terraform to write secrets (e.g. Grafana admin password)."
}

resource "random_string" "suffix" {
  length  = 4
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_key_vault" "main" {
  name                = "kv-cloudsentro-${random_string.suffix.result}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  sku_name            = "standard"

  soft_delete_retention_days = 7
  purge_protection_enabled   = true
  rbac_authorization_enabled = true

  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}

# Allows the managed identity that runs Terraform to read/write secrets
# in the data plane (RBAC mode is enabled, so Contributor at the control
# plane is not enough).
resource "azurerm_role_assignment" "secrets_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.secrets_writer_principal_id
}
