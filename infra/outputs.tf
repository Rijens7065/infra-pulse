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
