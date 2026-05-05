output "ml_sp_client_id" {
  value       = azuread_application.ml.client_id
  description = "ML service principal client ID — annotate the ml-service-account with this value."
}

output "agent_sp_client_id" {
  value       = azuread_application.agent.client_id
  description = "Agent service principal client ID — annotate the agent-service-account with this value."
}
