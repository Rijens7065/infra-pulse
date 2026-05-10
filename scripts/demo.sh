#!/usr/bin/env bash
# CloudSentro 5-minute demo orchestration.
#
#   ┌──────────────┐    ┌────────┐    ┌────────┐    ┌──────────┐    ┌─────────┐
#   │ inject       │───▶│ ML     │───▶│ Agent  │───▶│ GitHub   │───▶│ HCP     │
#   │ anomaly      │    │ score  │    │ reason │    │ PR       │    │ Cloud   │
#   └──────────────┘    └────────┘    └────────┘    └──────────┘    └─────────┘
#
# Usage:  bash scripts/demo.sh [--mode OOM_LEAK] [--intensity high]

set -euo pipefail

# ── colours ───────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  BOLD=$(tput bold)
  GREEN=$(tput setaf 2)
  YELLOW=$(tput setaf 3)
  CYAN=$(tput setaf 6)
  DIM=$(tput dim)
  RESET=$(tput sgr0)
else
  BOLD=""; GREEN=""; YELLOW=""; CYAN=""; DIM=""; RESET=""
fi

step() { printf "\n%s%s== %s ==%s\n" "$BOLD" "$CYAN" "$1" "$RESET"; }
ok()   { printf "%s✓%s %s\n" "$GREEN" "$RESET" "$1"; }
warn() { printf "%s!%s %s\n" "$YELLOW" "$RESET" "$1"; }
pause(){ read -r -p "  ${DIM}press Enter to continue…${RESET}" _; }

# ── args ──────────────────────────────────────────────────────────────────
MODE="OOM_LEAK"
INTENSITY="high"
DURATION=10
DASHBOARD_URL="${DASHBOARD_URL:-https://infra-pulse.cloudsentro.com/grafana/}"
GH_REPO="${GH_REPO:-Rijens7065/infra-pulse}"
NAMESPACE="${NAMESPACE:-cloudsentro}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)        MODE="$2"; shift 2 ;;
    --intensity)   INTENSITY="$2"; shift 2 ;;
    --duration)    DURATION="$2"; shift 2 ;;
    --dashboard)   DASHBOARD_URL="$2"; shift 2 ;;
    --repo)        GH_REPO="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *)
      echo "unknown flag: $1" >&2; exit 64 ;;
  esac
done

# ── prereqs ───────────────────────────────────────────────────────────────
for bin in kubectl python3 curl; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "${YELLOW}missing binary:${RESET} $bin" >&2; exit 1
  fi
done

# ── 1. dashboard ──────────────────────────────────────────────────────────
step "1/5  Verifying public dashboard"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "$DASHBOARD_URL" || echo "000")
if [[ "$HTTP_CODE" =~ ^(200|302)$ ]]; then
  ok "Grafana reachable at $DASHBOARD_URL  ($HTTP_CODE)"
else
  warn "Grafana check returned $HTTP_CODE — proceeding anyway"
fi
echo "  open it in your browser:  $BOLD$DASHBOARD_URL$RESET"
pause

# ── 2. inject anomaly ─────────────────────────────────────────────────────
step "2/5  Injecting $MODE (intensity=$INTENSITY, duration=${DURATION}m)"
INJECT_T0=$(date +%s)
python3 "$(dirname "$0")/inject_anomaly.py" \
  --mode "$MODE" \
  --intensity "$INTENSITY" \
  --duration "$DURATION" \
  --watch-url "$DASHBOARD_URL"
ok "injection accepted"
pause

# ── 3. detection ──────────────────────────────────────────────────────────
step "3/5  Watching ML model — looking for anomaly_score > 0.70"

# port-forward in background
LOCAL_PORT=18001
kubectl port-forward -n "$NAMESPACE" svc/ml-service "${LOCAL_PORT}:8000" >/dev/null 2>&1 &
PF_PID=$!
trap 'kill -TERM $PF_PID 2>/dev/null || true' EXIT
sleep 3

DETECTED=""
DETECT_T0=$(date +%s)
for attempt in $(seq 1 30); do
  PAYLOAD=$(curl -s --max-time 5 "http://127.0.0.1:${LOCAL_PORT}/predict" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c 'import json; print(json.dumps({"metrics": [[40,2.5e8,0,100,2.5e6,2e6,0.12]]*60}))')" \
    || echo "{}")
  SCORE=$(echo "$PAYLOAD" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("%.3f" % d.get("anomaly_score", 0))' 2>/dev/null || echo "0.000")
  MODE_OBSERVED=$(echo "$PAYLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("failure_mode","?"))' 2>/dev/null || echo "?")
  ELAPSED=$(( $(date +%s) - DETECT_T0 ))

  if (( $(awk -v s="$SCORE" 'BEGIN{print (s>0.70)}') )); then
    printf "  ${BOLD}${GREEN}t+%2ds  score=%s  mode=%s  ✓ DETECTED${RESET}\n" "$ELAPSED" "$SCORE" "$MODE_OBSERVED"
    DETECTED="$ELAPSED"
    break
  fi
  printf "  t+%2ds  score=%s  mode=%s\n" "$ELAPSED" "$SCORE" "$MODE_OBSERVED"
  sleep 10
done
kill -TERM $PF_PID 2>/dev/null || true

if [[ -z "$DETECTED" ]]; then
  warn "did not exceed threshold within 5 minutes"
fi
pause

# ── 4. GitHub PR ──────────────────────────────────────────────────────────
step "4/5  Watching GitHub for an agent-remediation PR"
PR_T0=$(date +%s)
PR_URL=""
for attempt in $(seq 1 32); do
  ELAPSED=$(( $(date +%s) - PR_T0 ))
  PR_URL=$(curl -s --max-time 8 \
    "https://api.github.com/repos/${GH_REPO}/pulls?state=open&sort=created&direction=desc&per_page=10" \
    | python3 -c 'import json,sys
data=json.load(sys.stdin)
for pr in data:
    labels={l["name"] for l in pr.get("labels",[])}
    if "agent-remediation" in labels:
        print(pr["html_url"]); break' 2>/dev/null) || true

  if [[ -n "$PR_URL" ]]; then
    printf "  ${BOLD}${GREEN}t+%2ds  ✓ %s${RESET}\n" "$ELAPSED" "$PR_URL"
    break
  fi
  printf "  t+%2ds  no PR yet…\n" "$ELAPSED"
  sleep 15
done

if [[ -z "$PR_URL" ]]; then
  warn "no PR appeared in 8 minutes — check agent pod logs:  kubectl logs -n $NAMESPACE -l app=agent-service"
fi
pause

# ── 5. summary ────────────────────────────────────────────────────────────
step "5/5  Summary"
INJECT_TO_DETECT=${DETECTED:-N/A}
INJECT_TO_PR_RAW=$(( $(date +%s) - INJECT_T0 ))
INJECT_TO_PR=${PR_URL:+$INJECT_TO_PR_RAW}
INJECT_TO_PR=${INJECT_TO_PR:-N/A}

printf "  %-30s %s\n" "anomaly mode"            "$MODE"
printf "  %-30s %s\n" "intensity"               "$INTENSITY"
printf "  %-30s %ss\n" "injection → detection"  "$INJECT_TO_DETECT"
printf "  %-30s %s\n" "injection → PR opened"   "$INJECT_TO_PR"
printf "  %-30s %s\n" "PR URL"                  "${PR_URL:-N/A}"
echo
ok "demo complete — open the dashboard and the PR side-by-side"
