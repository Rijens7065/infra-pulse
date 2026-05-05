output "vault_uri" {
  value       = azurerm_key_vault.main.vault_uri
  description = "Key Vault URI used by pods to read secrets at runtime."
}

output "id" {
  value       = azurerm_key_vault.main.id
  description = "Key Vault resource ID."
}

output "name" {
  value       = azurerm_key_vault.main.name
  description = "Key Vault name."
}
