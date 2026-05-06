variable "resource_group_name" {
  type        = string
  description = "Resource group to deploy into."
}

variable "location" {
  type        = string
  description = "Azure region."
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

variable "pusher_principal_id" {
  type        = string
  sensitive   = true
  description = "Principal ID granted AcrPush — the managed identity used by GitHub Actions OIDC."
}

resource "random_string" "suffix" {
  length  = 4
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_container_registry" "main" {
  name                = "acrcloudsentro${random_string.suffix.result}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false

  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}

# Allows GitHub Actions (OIDC-authenticated as the managed identity) to
# push container images into this registry.
import {
  to = azurerm_role_assignment.acr_push
  id = "${azurerm_container_registry.main.id}/providers/Microsoft.Authorization/roleAssignments/814a2483-effd-4392-971a-6154a8a360f2"
}

resource "azurerm_role_assignment" "acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = var.pusher_principal_id
}
