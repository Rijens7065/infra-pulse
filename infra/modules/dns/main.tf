variable "zone_id" {
  type        = string
  sensitive   = true
  description = "Cloudflare zone ID for cloudsentro.com."
}

variable "subdomain" {
  type        = string
  default     = "infra-pulse"
  description = "Subdomain to create (results in <subdomain>.cloudsentro.com)."
}

variable "ingress_public_ip" {
  type        = string
  description = "Public IP address of the AKS NGINX ingress LoadBalancer."
}

resource "cloudflare_record" "primary" {
  zone_id = var.zone_id
  name    = var.subdomain
  type    = "A"
  content = var.ingress_public_ip
  ttl     = 1 # auto when proxied
  proxied = true
  comment = "CloudSentro public entrypoint — managed by Terraform"
}

resource "cloudflare_record" "www" {
  zone_id = var.zone_id
  name    = "www.${var.subdomain}"
  type    = "CNAME"
  content = "${var.subdomain}.cloudsentro.com"
  ttl     = 1
  proxied = true
  comment = "www alias for CloudSentro — managed by Terraform"
}

resource "cloudflare_page_rule" "grafana_bypass_cache" {
  zone_id  = var.zone_id
  target   = "${var.subdomain}.cloudsentro.com/grafana/*"
  priority = 1
  status   = "active"

  actions {
    cache_level = "bypass"
  }
}

output "fqdn" {
  value       = "${var.subdomain}.cloudsentro.com"
  description = "Public FQDN."
}

output "url" {
  value       = "https://${var.subdomain}.cloudsentro.com"
  description = "Public URL."
}
