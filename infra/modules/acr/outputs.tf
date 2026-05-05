output "login_server" {
  value       = azurerm_container_registry.main.login_server
  description = "ACR login server URL."
}

output "id" {
  value       = azurerm_container_registry.main.id
  description = "ACR resource ID."
}

output "name" {
  value       = azurerm_container_registry.main.name
  description = "ACR name."
}
