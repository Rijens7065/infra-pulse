variable "resource_group_id" {
  type        = string
  description = "Resource group ID to scope the budget against."
}

variable "alert_email" {
  type        = string
  description = "Email address to notify at 70% and 90% spend thresholds."
}

resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "budget-cloudsentro"
  resource_group_id = var.resource_group_id
  amount            = 50
  time_grain        = "Monthly"

  time_period {
    start_date = "${formatdate("YYYY-MM", timestamp())}-01T00:00:00Z"
  }

  notification {
    enabled        = true
    threshold      = 70
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    threshold      = 90
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
