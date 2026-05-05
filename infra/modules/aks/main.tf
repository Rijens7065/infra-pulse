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

resource "azurerm_kubernetes_cluster" "main" {
  name                = "cloudsentro-demo"
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = "cloudsentro-demo"

  default_node_pool {
    name                 = "default"
    vm_size              = "Standard_B2s"
    auto_scaling_enabled = true
    min_count            = 1
    max_count            = 2

    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  network_profile {
    network_plugin = "kubenet"
  }

  sku_tier = "Free"

  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}
