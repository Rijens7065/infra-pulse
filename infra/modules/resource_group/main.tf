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

import {
  to = azurerm_resource_group.main
  id = "/subscriptions/2b73c588-cd58-4fc1-bb65-687bb7c3c66e/resourceGroups/rg-cloudsentro-terraform"
}

resource "azurerm_resource_group" "main" {
  name     = "rg-cloudsentro-terraform"
  location = var.location

  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}
