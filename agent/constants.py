"""Shared constants for the CloudSentro agent."""

CLAUDE_MODEL = "claude-sonnet-4-20250514"

CONFIDENCE_THRESHOLD = 0.75
MAX_TOOL_TURNS = 10
POLL_INTERVAL_SECONDS = 300
MAX_BACKOFF_SECONDS = 600
INITIAL_BACKOFF_SECONDS = 30

KEY_VAULT_SECRET_CLAUDE = "claude-api-key"
KEY_VAULT_SECRET_GITHUB = "github-app-private-key"

AUDIT_CONTAINER = "agent-audit-log"

PR_LABELS_BASE = ["agent-remediation", "terraform"]

FORBIDDEN_FAILURE_MODES_FOR_PR = ["SECURITY_DRIFT"]

FORBIDDEN_TERRAFORM_PATHS = [
    "infra/modules/budget/",
    "infra/modules/identity/",
]
