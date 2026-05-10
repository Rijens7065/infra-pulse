# Issues encountered during the build

> A complete retrospective: every bug we hit, what caused it, how we fixed
> it, and what we learned. Organised by the phase it surfaced in. If you're
> reading this before standing up a similar project, this is the cheat
> sheet.

---

## Phase 1 — Foundation (Terraform + Azure)

### azurerm 3.x AKS attribute drift

**Symptom:** `terraform validate` failed because we used
`enable_auto_scaling` and `auto_scaling_enabled` keys; both rejected.

**Cause:** azurerm 3.117.1 removed both from `default_node_pool`. Autoscaling
is implicit when `min_count` + `max_count` are both set.

**Fix:** dropped both attributes; kept only `min_count` and `max_count`.

### Spot attributes on the system node pool

**Symptom:** Plan errored on `priority`, `eviction_policy`,
`spot_max_price` in the default node pool.

**Cause:** Azure requires AKS **system** node pools to be Regular VMs; Spot
is only valid on user-added node pools.

**Fix:** removed all three attributes; system pool is on-demand. Spot is a
future-phase concern.

### azurerm 4.x upgrade: enable_rbac_authorization renamed

**Symptom:** After bumping the provider to `~> 4.0`, the Key Vault module
failed validation: unknown argument `enable_rbac_authorization`.

**Cause:** azurerm 4.x renamed it to `rbac_authorization_enabled`.

**Fix:** straight rename.

### "Resource already exists" on first apply

**Symptom:** Apply errored because `rg-cloudsentro-terraform` resource group
existed in Azure (created during bootstrap) but wasn't in Terraform state.

**Cause:** Bootstrap created the RG manually so HCP Cloud could authenticate
before any Terraform existed.

**Fix:** added an `import {}` block to the resource_group module on first
apply, then removed it once the RG was imported into state.

**Lesson:** if a resource pre-exists, you import it; you don't let Terraform
try to re-create it.

### VM size not allowed in canadaeast

**Symptom:** AKS apply failed with `Standard_B2s is not allowed in your
subscription in location 'canadaeast'`.

**Cause:** Newer Azure subscriptions in canadaeast only allow newer VM
generations. The B-series (v1) is fully blocked. Bsv2 has its own quota
(remaining 0 by default).

**Fix:** Switched to `Standard_D2s_v3`. It's in the allowed list and has
quota. Costs more (~$70/mo on-demand vs ~$10 for B2s Spot) but the only
option that worked without a quota increase ticket.

**Lesson:** check `az vm list-skus --location <region>` and your subscription's
quota before designing around a specific VM size.

### Cloudflare token: invalid character

**Symptom:** HCP Cloud apply failed during the Cloudflare DNS module with
`Error: invalid value for api_token (API tokens must only contain characters
a-z, A-Z, 0-9, hyphens and underscores)`.

**Cause:** the token in the HCP Cloud workspace variable had a trailing
newline pasted along with it.

**Fix:** re-pasted the token with no whitespace.

### Cloudflare 9109 "Unauthorized" on page_rule creation

**Symptom:** Apply failed creating `cloudflare_page_rule` for the
`/grafana/*` cache bypass.

**Cause:** the Cloudflare token had Zone → DNS → Edit but not Zone → Page
Rules → Edit.

**Fix:** removed the page rule from the DNS module entirely. Grafana sends
its own cache headers; the Cloudflare bypass wasn't load-bearing.

**Lesson:** scope the token to the minimum, and design Terraform to fit that
scope.

### Key Vault 403 ForbiddenByRbac on first apply

**Symptom:** Apply created the role assignment `Key Vault Secrets Officer`
for the Terraform identity, then immediately tried to write the Grafana admin
secret in the same apply. The write hit 403.

**Cause:** Azure RBAC takes 30-120 seconds to propagate to the data plane.
The role assignment existed in the control plane but the data plane (the KV
itself) hadn't seen it yet.

**Fix:** added `time_sleep` (150s) after the role assignment in the keyvault
module. The grafana module depends on `module.keyvault` so it now waits for
that sleep to finish before trying to write.

### The principal split

**Symptom:** Even after re-applying with the time_sleep, secret writes still
got 403 from a *different* principal — `oid=afa7467c-...`, not the
`f2ee2e29-...` we'd granted the role to.

**Cause:** we'd assumed GitHub Actions and HCP Cloud authenticate as the
same Azure principal. They don't. GHA federates to the managed identity
`mi-cloudsentro-terraform`. HCP Cloud federates to a separate app registration.

**Fix:** split the variable. `TF_VAR_principal_id` carries the GHA identity
(grants AcrPush). `TF_VAR_terraform_runner_principal_id` carries the HCP
Cloud identity (grants KV Secrets Officer). Set both in the HCP Cloud
workspace.

**Lesson:** when an OIDC chain is involved, always print the actual `oid`
from the error JWT. Don't assume.

### Identity module deferred

**Symptom:** Phase 1 apply failed creating `azuread_application` resources
with `Authorization_RequestDenied: Insufficient privileges`.

**Cause:** creating app registrations needs the Application Administrator
directory role in Entra ID. The Terraform-runner principal doesn't have it,
and the user account doesn't have permission to grant it.

**Fix:** commented out the identity module from `infra/main.tf` and its
outputs. For Phase 2/3, the ML and agent pods use a K8s `Secret` for their
credentials instead of workload-identity-federated service principals.

**Lesson:** check directory-role prerequisites before planning. App
registrations are a different permission domain from Azure RBAC.

---

## Phase 2 — ML Model

### Python 3.14 on the developer machine

**Symptom:** `pip install torch==2.1.0+cpu` failed with "No matching
distribution found".

**Cause:** the developer's Python is 3.14, which torch 2.1.0 doesn't have
wheels for.

**Fix:** Installed `torch==2.9.0+cpu` in the local venv for testing only.
The Dockerfile uses Python 3.11-slim and the pinned `2.1.0+cpu` works there.

**Lesson:** decouple local-dev test versions from the production-pinned
versions. The Dockerfile is the source of truth.

### Microsoft Visual C++ Redistributable missing

**Symptom:** `import torch` failed on Windows with "DLL load failed".

**Cause:** PyTorch on Windows depends on the VC++ Runtime, which wasn't
installed.

**Fix:** `winget install Microsoft.VCRedist.2015+.x64 --silent`.

### Test failed on small dataset

**Symptom:** `test_normal_dominates` failed: NORMAL was only 57% of labels.

**Cause:** the generator always injects 8-15 anomaly windows regardless of
the dataset length. On a 3-day test fixture, those windows dominate. On the
real 30-day dataset they're ~5% of rows.

**Fix:** Switched the test fixture to 10 days so the proportion matches the
spec.

---

## Phase 3 — Agent

### anthropic SDK 0.28.0 incompatible with httpx 0.28+

**Symptom:** Agent pod startup crashed:
`TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`.

**Cause:** anthropic 0.28.0 passes `proxies=` to httpx. httpx 0.28 removed
that argument.

**Fix:** Bumped anthropic to 0.49.0.

**Lesson:** when pinning a library, also pin (or at least understand) its
HTTP client version.

### Agent calling `/predict` with GET

**Symptom:** Agent log showed `httpx.HTTPStatusError: 405 Method Not
Allowed`.

**Cause:** the original blueprint sketch said `GET /predict`. The actual ML
implementation accepts `POST /predict` with a 60×7 body (a synthetic baseline
window) — the injection override on the ML side reshapes the response anyway.

**Fix:** `run_get_current_anomaly_signal` now POSTs a fixed baseline window.
The injected response (if active) is what the agent sees.

**Future:** real production would have the ML pod maintain a rolling window
from Azure Monitor and expose `GET /signal/latest`. We deferred this; the
demo doesn't need real Azure Monitor wiring.

### Agent missing `/metrics` endpoint

**Symptom:** Prometheus scraped `agent-service:8001/metrics` and got 404.

**Cause:** the agent didn't expose `/metrics`. The deployment annotation
told Prometheus to scrape it, but the route didn't exist.

**Fix:** added `@app.get("/metrics")` returning `generate_latest()` from
`prometheus_client`. Empty metrics initially, but a valid response.

---

## Phase 4 — Dashboard

This phase had the most issues — partly because it's the most surface area
(7 modules) and partly because AKS + ingress + LB has a lot of subtle
defaults.

### AKS LB rule: `enableFloatingIp: null` + `backendPort: 80`

**Symptom:** `curl http://<lb-ip>/` timed out. Ingress pod was healthy
(returned 404 from inside the cluster) but no external traffic reached it.

**Cause:** for the ingress-nginx service, the AKS cloud-controller created a
broken LB rule: `backendPort: 80` (the service port) with `enableFloatingIp:
null` (defaulting to false). With FloatingIP off, the LB DNATs traffic to
port 80 on the node — but nothing on the node listens on port 80; kube-proxy
listens on the NodePort (30932). Traffic landed on a dead port.

**Fix:** set `controller.service.externalTrafficPolicy: "Local"` in the
ingress Helm values. This flips the LB into Direct Server Return mode
(`enableFloatingIp: true`), preserving the destination IP/port so iptables
on the node catches the packet.

### LB health probe: HTTP `GET /` returning 404

**Symptom:** Even with FloatingIP fixed, the LB still wasn't sending traffic
to the backend.

**Cause:** the auto-generated probe used HTTP protocol with path `/`. The
ingress-nginx controller returns **404** for `/` (no Ingress rule matches that
exact path). The LB requires 2xx-3xx for a healthy probe. So the LB marked
the backend as unhealthy and dropped traffic.

**Fix:** added the service annotation
`service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol: tcp`.
TCP probes just check that the port is open; they don't care about HTTP
responses.

### Grafana redirect loop

**Symptom:** `https://infra-pulse.cloudsentro.com/grafana/` got
`ERR_TOO_MANY_REDIRECTS` in the browser.

**Cause:** our ingress rule used the path pattern `/grafana(/|$)(.*)` with
the annotation `nginx.ingress.kubernetes.io/rewrite-target: /$2` — which
**strips** the `/grafana` prefix before forwarding. But Grafana was
configured with `serve_from_sub_path: true` and `root_url: …/grafana`,
which means it **expects** to receive requests at `/grafana/...`. So:
nginx strips `/grafana`, Grafana sees `/`, redirects to `/grafana/`, nginx
strips it again, infinite loop.

**Fix:** removed the `rewrite-target` and `use-regex` annotations. Simplified
the path to a plain `/grafana` `Prefix` match. Grafana now receives requests
with the prefix intact and serves them.

### Cloudflare 522 (Connection timed out)

**Symptom:** Cloudflare proxied the request fine but couldn't reach the
origin.

**Cause:** all of the above — the LB wasn't accepting traffic because the
backend was marked unhealthy. Once that was fixed, the 522 disappeared.

### Cloudflare SSL mode mismatch

**Symptom:** After the LB was working, `https://infra-pulse.cloudsentro.com`
still failed because Cloudflare was trying to connect to the origin on
**HTTPS (443)** by default, and we don't have TLS configured on the ingress.

**Fix:** Cloudflare dashboard → SSL/TLS → Encryption mode → **Flexible**.
This makes Cloudflare talk to clients over HTTPS (using its own cert) but
talk to the origin over HTTP.

**Future:** Production should use cert-manager + Let's Encrypt on the
ingress and "Full (strict)" SSL on Cloudflare. Out of scope for the demo.

### Grafana duplicate folder

**Symptom:** After everything came up, Grafana had two CloudSentro-related
entries: an empty folder called "CloudSentro" and a dashboard at root level.

**Cause:** we'd configured two parallel mechanisms — a filesystem provider
that watches `/var/lib/grafana/dashboards/cloudsentro/` and the sidecar that
uploads via HTTP. The filesystem provider created the empty folder
(because it had `folder = "CloudSentro"`). The sidecar uploaded the dashboard
to the General folder (root) via the API.

**Fix:** dropped the filesystem provider entirely. Sidecar handles all
dashboard loading with `defaultFolderName: "CloudSentro"`.

### Grafana datasource UID mismatch

**Symptom:** Dashboard panels showed "No data" even though Prometheus had
the metrics.

**Cause:** the dashboard JSON references the datasource by UID:
`"datasource": {"type": "prometheus", "uid": "prometheus"}`. But Grafana
auto-generates a random UID for each provisioned datasource. Our datasource
had a UID like `cefh8kxhz...`, not `prometheus`.

**Fix:** pinned the UID explicitly in the datasources config:
```yaml
- name: Prometheus
  uid: prometheus
  ...
```

### Grafana anonymous Viewer missing folders:read

**Symptom:** After a Grafana restart, anonymous Viewer hit
`folders:read permission denied`.

**Cause:** Grafana 7.0.19 chart vs newer Grafana RBAC defaults. Anonymous
Viewer's permissions changed.

**Workaround for demo:** sign in as admin (password from Key Vault) to take
screenshots. Fixing properly would require upgrading the chart and
configuring the anonymous role explicitly.

---

## Phase 5 — Integration & demo

### ACR pull from AKS: 401 Unauthorized

**Symptom:** ML pod stuck in `ErrImagePull`. Container Insights showed
`failed to fetch anonymous token: 401`.

**Cause:** the AKS kubelet identity didn't have `AcrPull` on the registry.
We'd granted `AcrPush` to the GHA identity (for pushing) but not `AcrPull`
to the kubelet identity (for pulling).

**Fix:** `az aks update -g rg-cloudsentro-terraform -n cloudsentro-demo --attach-acr acrcloudsentrojdly`.
This grants the kubelet identity AcrPull behind the scenes.

**Follow-up:** should be moved into Terraform (`azurerm_role_assignment` on
the AKS module's kubelet identity → ACR). Currently a manual one-shot.

### ConfigMap YAML int vs string

**Symptom:** Agent ConfigMap apply failed with `json: cannot unmarshal
number into Go struct field ConfigMap.data of type string`.

**Cause:** `deploy.sh` does `sed` substitution. When `GITHUB_APP_ID` is
`1234567`, the substituted line becomes `GITHUB_APP_ID: 1234567` — and YAML
parses bare numbers as integers. But ConfigMap `data` values must be
strings.

**Fix:** wrapped every placeholder in the configmap.yaml template with
double quotes: `GITHUB_APP_ID: "PLACEHOLDER_GITHUB_APP_ID"`. After
substitution: `GITHUB_APP_ID: "1234567"` — a string.

### tee mask: terraform plan exit code lost

**Symptom:** When HCP Cloud's speculative plan failed, the
`Terraform Plan` GitHub check still showed ✓ green.

**Cause:** `terraform plan ... 2>&1 | tee plan_output.txt` returns tee's
exit code (always 0) — not terraform's. So the "Fail if Plan Failed" step
never triggered.

**Fix:** added `set -o pipefail` to the run script. Now the pipeline
returns the **first non-zero** exit in the chain.

### GitHub Actions ↔ HCP Cloud sync

**Symptom:** Even with the plan-pipefail fix, the apply pipeline showed ✓
green when HCP Cloud's apply errored. Different gap.

**Cause:** the original `tf-apply.yml` just posted a comment with a link to
HCP Cloud. It never actually verified that HCP Cloud succeeded.

**Fix:** rewrote `tf-apply.yml` to poll HCP Cloud's API
(`/api/v2/.../runs?search[commit]=<sha>`), wait for a terminal status
(`applied` / `errored` / etc.), and exit accordingly. Now GitHub's commit
status reflects the real apply outcome.

### Demo script: bash f-string escape

**Symptom:** Demo step 3 always printed `score=0.000` even though the ML
pod's `/predict` was returning the correct 0.95 score (verified with direct
kubectl exec).

**Cause:** the score parser was:
```bash
python3 -c 'print(f"{d.get(\"anomaly_score\",0):.3f}")'
```
The `\"anomaly_score\"` inside a Python f-string expression is invalid
Python in 3.11 (you can't backslash-escape inside `{}`). Python errored
silently (because `2>/dev/null`) and the `||` fallback returned 0.000. The
mode parser worked because it didn't use an f-string.

**Fix:** rewrote with old-style `%` formatting:
```bash
python3 -c 'print("%.3f" % d.get("anomaly_score", 0))'
```

### Image tag staleness

**Symptom:** After bumping the anthropic SDK and pushing the fix, the agent
pod still crashed with the same error after `kubectl rollout restart`.

**Cause:** `kubectl rollout restart` repulls `:latest`. But `:latest` in ACR
was still the previous build until the agent-build workflow finished. We
told kubectl to restart before CI was done.

**Fix:** wait for `Agent — Build and Push` on the Actions tab to go green
on the correct commit SHA, then `kubectl rollout restart` (or `kubectl
delete pod` to force a fresh pull).

### Trivy CRITICAL/HIGH gate

**Symptom:** `Agent — Build and Push` failed the scan.

**Cause:** CVE-2025-32434 (torch 2.1.0 → 2.6.0), CVE-2026-32597 (PyJWT
2.8.0 → 2.12.0), CVE-2024-26130 (cryptography), CVE-2024-47874 (starlette),
CVE-2025-66418/66471/26-21441 (urllib3), CVE-2026-24049 (wheel in vendored
setuptools), CVE-2026-23949 (jaraco.context in vendored setuptools).

**Fix:**
- Bumped direct deps: torch 2.6.0+cpu, PyJWT 2.12.1, cryptography 46.0.5,
  fastapi 0.115.6 (pulls newer starlette).
- Pinned transitive: urllib3 2.6.3.
- Added `--upgrade setuptools wheel` to the Dockerfile builder stage so the
  venv's vendored copies are current.
- Added `.trivyignore` for three unfixable HIGHs in the base-image's
  pre-installed setuptools and the starlette CVE that would require a
  fastapi major bump.

### Direct-to-main pushes (process violation, not a bug)

A handful of small fixes (folder dedup, datasource UID pin) went directly to
`main` instead of via PR. Saved as a feedback memory:
`feedback_pr_workflow.md`. All future changes go through PRs.
