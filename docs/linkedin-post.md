# LinkedIn post — CloudSentro

> Suggested when posting: pin a top comment with the live demo link
> https://infra-pulse.cloudsentro.com so the algorithm doesn't penalise
> external links in the body.

---

It's 2:47 a.m. You're on call. PagerDuty just woke you up.

A pod in production is leaking memory. Latency is climbing. The runbook
says: SSH in, read logs, write a Terraform patch, get a review at 3 a.m.,
deploy. Forty minutes from page to fix, on a good day.

I built **CloudSentro** — a system that does steps 1–4 by itself, runs
on $37/month of Azure infrastructure, and only wakes you up so you can
click "Approve" on a pull request.

**🔗 Live demo:** https://infra-pulse.cloudsentro.com

Here's what's underneath, in plain English:

🧠 **An ML model watches metrics.** A PyTorch LSTM autoencoder learns
what your AKS cluster looks like when it's healthy. Every minute it
reconstructs the last hour of CPU, memory, network, latency, restart
counts, and cost. The reconstruction error is the anomaly score. A
two-stage classifier (Isolation Forest gate + Random Forest) labels
the deviation as one of six failure modes: `OOM_LEAK`, `CPU_THROTTLE`,
`NETWORK_DEGRADATION`, `COST_SPIKE`, `SECURITY_DRIFT`, or `NORMAL`.
Test accuracy: 99%. Inference: <200 ms.

🤖 **A Claude agent reasons about it.** When confidence exceeds 75%,
a Claude `claude-sonnet-4-20250514` agent runs a tool-use loop —
seven typed tools that let it pull Azure Monitor metrics, read recent
infra commits, list Kubernetes events, and read the actual Terraform
file it's about to change. It builds a step-by-step reasoning trail
(visible in every PR), proposes a fix, and stops if it isn't sure.

📦 **The fix arrives as a real GitHub PR.** Branch name encodes the
failure mode and timestamp. The body has five required sections:
Anomaly Report, Root Cause, Reasoning Chain (collapsible), Proposed
Terraform Changes, and Rollback Instructions. Labels: `agent-remediation`,
`terraform`, and the failure mode. A human reviews. HCP Cloud applies
on merge.

A few specific choices that mattered:

- **Zero static credentials anywhere.** GitHub Actions and HCP Cloud
  authenticate to Azure via OIDC federated credentials. No client
  secrets in CI, no service-account keys in pods. The only secrets
  in the system are the Anthropic API key and the GitHub App private
  key, both in Azure Key Vault.

- **Two principals, two trust domains.** GitHub Actions has AcrPush
  on the registry, nothing else. HCP Cloud's identity has the broader
  Terraform-managed scope. They are not the same — wiring them as one
  identity is a common mistake and a real production risk.

- **Hard rules around the agent.** Six things it cannot do, ever:
  delete resources, modify IAM, touch the budget module, write outside
  `infra/`, open PRs above a 10-tool-call budget, or open PRs at all
  for `SECURITY_DRIFT` (those go to a logged audit trail for human
  review). Enforced both in the system prompt AND in code, with unit
  tests.

- **Human in the loop, always.** The agent never applies anything
  itself. Every fix passes through a human-approved PR and HCP Cloud
  before it touches infrastructure. "Autonomous" doesn't mean
  unsupervised — it means the system does the cognitive work and asks
  you to confirm.

The whole stack: Terraform + HCP Cloud + Azure AKS + ACR + Key Vault
+ NGINX ingress + Prometheus + Grafana + Cloudflare DNS + GitHub
Actions OIDC + GitHub Apps + Claude API. Built incrementally over
five phases, each phase tested in isolation, every change reviewed
through a real PR pipeline.

A few questions I'm thinking about, and would love your take on:

1. Where does the human stay in the loop as agents get more capable —
   approving PRs, or just approving the *kinds* of PRs an agent can
   open?
2. The agent reads its own diff before proposing a change. How far does
   that pattern extend — agents that test their own code before opening
   PRs? Run their own canaries?
3. Cost: $37/month makes this an interesting hobby project. What's the
   inflection point where this becomes obviously worth it for a real
   engineering team?

If you build platforms or write infrastructure, I'd love to hear what
you'd add — or what you'd take out.

🔗 **Live:** https://infra-pulse.cloudsentro.com
🔗 **Code:** https://github.com/Rijens7065/infra-pulse

#MLOps #AzureCloud #DevOps #AIEngineering #Terraform #GitOps #CloudNative #LLM
