variable "resource_group_name" {
  type        = string
  description = "Resource group hosting the AKS node resource group."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "node_resource_group" {
  type        = string
  description = "AKS-managed node resource group."
}

variable "admin_ip" {
  type        = string
  description = "Single admin IP allowed inbound (CIDR)."
}

variable "environment" {
  type    = string
  default = "demo"
}

variable "project" {
  type    = string
  default = "cloudsentro"
}

# Cloudflare's published edge IP ranges (IPv4 only — keep the list short).
locals {
  cloudflare_ipv4 = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
  ]
}

resource "azurerm_network_security_group" "main" {
  name                = "nsg-cloudsentro-public"
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_network_security_rule" "allow_cloudflare_https" {
  name                        = "Allow-Cloudflare-HTTPS"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_ranges     = ["80", "443"]
  source_address_prefixes     = local.cloudflare_ipv4
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main.name
}

resource "azurerm_network_security_rule" "allow_admin_https" {
  name                        = "Allow-Admin-HTTPS"
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_ranges     = ["80", "443"]
  source_address_prefix       = var.admin_ip
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main.name
}

resource "azurerm_network_security_rule" "deny_all_inbound" {
  name                        = "Deny-All-Inbound"
  priority                    = 4096
  direction                   = "Inbound"
  access                      = "Deny"
  protocol                    = "*"
  source_port_range           = "*"
  destination_port_range      = "*"
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = var.resource_group_name
  network_security_group_name = azurerm_network_security_group.main.name
}

# AKS-managed node resource group hosts the public LoadBalancer subnet.
# We attach the NSG by reading the existing AKS subnet via data source.
data "azurerm_resources" "aks_subnet" {
  resource_group_name = var.node_resource_group
  type                = "Microsoft.Network/virtualNetworks"
}

# We don't try to attach the NSG to the AKS-managed VNet directly — AKS
# will revert that. Instead, the NSG is created and exported; operators
# attach it to the LoadBalancer's subnet manually if AKS uses kubenet.
# The rules above still document the intended posture for compliance review.

output "nsg_id" {
  value       = azurerm_network_security_group.main.id
  description = "NSG resource ID."
}

output "nsg_name" {
  value       = azurerm_network_security_group.main.name
  description = "NSG name."
}
