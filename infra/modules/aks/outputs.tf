output "cluster_name" {
  value       = azurerm_kubernetes_cluster.main.name
  description = "AKS cluster name."
}

output "id" {
  value       = azurerm_kubernetes_cluster.main.id
  description = "AKS cluster resource ID."
}

output "kube_config" {
  value       = azurerm_kubernetes_cluster.main.kube_config
  sensitive   = true
  description = "AKS kubeconfig block (sensitive). Used by helm and kubernetes providers in Phase 4."
}

output "kube_config_raw" {
  value       = azurerm_kubernetes_cluster.main.kube_config_raw
  sensitive   = true
  description = "AKS kubeconfig in raw YAML format."
}

output "oidc_issuer_url" {
  value       = azurerm_kubernetes_cluster.main.oidc_issuer_url
  description = "AKS OIDC issuer URL for workload identity federated credentials."
}

output "node_resource_group" {
  value       = azurerm_kubernetes_cluster.main.node_resource_group
  description = "Auto-created resource group that holds AKS node VMs."
}
