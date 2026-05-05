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
