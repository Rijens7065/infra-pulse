variable "location" {
  type        = string
  default     = "canadaeast"
  description = "Azure region for all resources."
}

variable "environment" {
  type        = string
  default     = "demo"
  description = "Environment name used for tagging."
}

variable "project" {
  type        = string
  default     = "cloudsentro"
  description = "Project name used for tagging."
}

variable "alert_email" {
  type        = string
  description = "Email address for budget alerts and notifications."
}

variable "admin_ip" {
  type        = string
  description = "Admin IP address allowed through NSG (Phase 4)."
}

variable "cloudflare_zone_id" {
  type        = string
  sensitive   = true
  description = "Cloudflare zone ID for cloudsentro.com."
}

variable "cloudflare_api_token" {
  type        = string
  sensitive   = true
  description = "Cloudflare API token with DNS edit permissions."
}

variable "client_id" {
  type        = string
  sensitive   = true
  description = "Azure managed identity client ID used for OIDC authentication."
}

variable "tenant_id" {
  type        = string
  sensitive   = true
  description = "Azure Active Directory tenant ID."
}

variable "subscription_id" {
  type        = string
  sensitive   = true
  description = "Azure subscription ID."
}
