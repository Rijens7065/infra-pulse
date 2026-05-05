output "budget_id" {
  value       = azurerm_consumption_budget_resource_group.main.id
  description = "Budget resource ID."
}
