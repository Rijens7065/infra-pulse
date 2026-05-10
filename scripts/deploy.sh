#!/usr/bin/env bash
# Deploy ML and Agent to AKS — substitutes the placeholders in k8s/ manifests
# with the real values from Terraform outputs and applies them.
#
# Required env / args:
#   ACR_LOGIN_SERVER       e.g. acrcloudsentrojdly.azurecr.io
#   AKS_RESOURCE_ID        full Azure resource ID for the AKS cluster
#   GITHUB_REPO_OWNER      e.g. Rijens7065
#   ANTHROPIC_API_KEY      Anthropic API key (sk-ant-…)
#   GITHUB_APP_ID          numeric app id from GitHub
#   GITHUB_INSTALLATION_ID numeric installation id
#   GITHUB_APP_PEM_FILE    path to the GitHub App private key .pem
#
# Usage:  bash scripts/deploy.sh [--ml-only|--agent-only]

set -euo pipefail

REQUIRED_ENV=(
  ACR_LOGIN_SERVER
  AKS_RESOURCE_ID
  GITHUB_REPO_OWNER
)

DEPLOY_ML=true
DEPLOY_AGENT=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ml-only)    DEPLOY_AGENT=false; shift ;;
    --agent-only) DEPLOY_ML=false;    shift ;;
    -h|--help)    sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 64 ;;
  esac
done

for var in "${REQUIRED_ENV[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "missing required env: $var" >&2; exit 1
  fi
done

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
NAMESPACE=cloudsentro

# ── namespace ─────────────────────────────────────────────────────────────
echo "==> ensuring namespace: $NAMESPACE"
kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE"

# ── helper: render manifest with envsubst-style placeholder swaps ─────────
render() {
  local file="$1"
  sed \
    -e "s|PLACEHOLDER_ACR|${ACR_LOGIN_SERVER}|g" \
    -e "s|PLACEHOLDER_AKS_RESOURCE_ID|${AKS_RESOURCE_ID}|g" \
    -e "s|PLACEHOLDER_GITHUB_OWNER|${GITHUB_REPO_OWNER}|g" \
    -e "s|PLACEHOLDER_GITHUB_APP_ID|${GITHUB_APP_ID:-0}|g" \
    -e "s|PLACEHOLDER_GITHUB_INSTALLATION_ID|${GITHUB_INSTALLATION_ID:-0}|g" \
    -e "s|PLACEHOLDER_TENANT_ID|${ARM_TENANT_ID:-}|g" \
    -e "s|PLACEHOLDER_AGENT_SP_CLIENT_ID|${ARM_CLIENT_ID:-}|g" \
    -e "s|PLACEHOLDER_KEYVAULT_URI|${KEYVAULT_URI:-}|g" \
    -e "s|PLACEHOLDER_SUBSCRIPTION_ID|${ARM_SUBSCRIPTION_ID:-}|g" \
    -e "s|PLACEHOLDER_STORAGE_ACCOUNT_URL|${STORAGE_ACCOUNT_URL:-}|g" \
    -e "s|PLACEHOLDER_ML_SP_CLIENT_ID|${ARM_CLIENT_ID:-}|g" \
    "$file"
}

# ── ML ────────────────────────────────────────────────────────────────────
if [[ "$DEPLOY_ML" == true ]]; then
  echo "==> deploying ML"
  for f in namespace serviceaccount service deployment; do
    render "$REPO_ROOT/ml/k8s/${f}.yaml" | kubectl apply -f -
  done
  kubectl rollout status -n "$NAMESPACE" deploy/ml-service --timeout=180s
  echo "ML ready."
fi

# ── Agent secrets ─────────────────────────────────────────────────────────
if [[ "$DEPLOY_AGENT" == true ]]; then
  if [[ -n "${ANTHROPIC_API_KEY:-}" && -n "${GITHUB_APP_PEM_FILE:-}" ]]; then
    if [[ ! -f "$GITHUB_APP_PEM_FILE" ]]; then
      echo "GITHUB_APP_PEM_FILE not found: $GITHUB_APP_PEM_FILE" >&2; exit 1
    fi
    echo "==> creating agent-secrets in $NAMESPACE"
    kubectl create secret generic agent-secrets \
      -n "$NAMESPACE" \
      --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
      --from-file=GITHUB_APP_PRIVATE_KEY="$GITHUB_APP_PEM_FILE" \
      --dry-run=client -o yaml | kubectl apply -f -
  else
    echo "==> ANTHROPIC_API_KEY / GITHUB_APP_PEM_FILE not set — skipping agent-secrets"
    echo "    (the agent will fall back to Key Vault, which requires workload identity)"
  fi

  echo "==> deploying Agent"
  for f in namespace serviceaccount configmap service deployment; do
    render "$REPO_ROOT/agent/k8s/${f}.yaml" | kubectl apply -f -
  done
  kubectl rollout status -n "$NAMESPACE" deploy/agent-service --timeout=180s
  echo "Agent ready."
fi

echo
kubectl get pods -n "$NAMESPACE"
