output "acr_login_server" {
  value       = module.acr.login_server
  description = "ACR login server URL for docker push/pull."
}

output "aks_cluster_name" {
  value       = module.aks.cluster_name
  description = "AKS cluster name for kubectl and GitHub Actions."
}

output "aks_oidc_issuer_url" {
  value       = module.aks.oidc_issuer_url
  description = "AKS OIDC issuer URL used by workload identity federated credentials."
}

output "key_vault_uri" {
  value       = module.keyvault.vault_uri
  description = "Key Vault URI for reading secrets at runtime."
}

# ml_sp_client_id and agent_sp_client_id outputs deferred to Phase 2/3 with identity module

output "public_url" {
  value       = module.dns.url
  description = "Public URL of the CloudSentro dashboard."
}

output "ingress_public_ip" {
  value       = module.ingress.public_ip
  description = "Public IP of the NGINX ingress LoadBalancer."
}

output "grafana_admin_secret" {
  value       = module.grafana.admin_password_secret_name
  description = "Key Vault secret name holding the Grafana admin password."
  sensitive   = true
}
