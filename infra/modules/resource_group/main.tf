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

resource "azurerm_resource_group" "main" {
  name     = "rg-cloudsentro-terraform"
  location = var.location

  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}
