# dashboard/ — Dashboard Context

> Read this before touching any file in dashboard/

## What this module does
Two things:
1. Grafana dashboard at https://infra-pulse.cloudsentro.com/grafana (live anomaly data)
2. Static landing page at https://infra-pulse.cloudsentro.com (Cloudflare Pages)

## Critical rules
- Grafana anonymous access is intentional — this is a public demo
- Never enable Grafana auth for demo purposes
- Landing page must be a single HTML file — no frameworks, no CDN dependencies
- Landing page must be under 20KB total
- Dashboard JSON must be valid Grafana JSON — test before committing
- Cache bypass must be set for /grafana/* in Cloudflare page rules

## Grafana access
```
URL:      https://infra-pulse.cloudsentro.com/grafana
Auth:     Anonymous Viewer (read-only, no login needed)
Admin:    password stored in Key Vault secret "grafana-admin-password"
Refresh:  30 seconds
Default:  last 6 hours
Theme:    dark
```

## Grafana datasources (provisioned automatically)
```
Prometheus   → http://prometheus-server.cloudsentro:80  (default)
Azure Monitor → MSI auth (workload identity)
```

## Dashboard panels — 4 rows
```
Row 1: Live Anomaly Detection
  - Stat: cloudsentra_anomaly_score (thresholds: green/yellow/red)
  - Stat: failure_mode classification
  - Time series: anomaly_score last 24h

Row 2: AKS Health
  - Time series: cpu_usage_percent
  - Time series: memory_rss_bytes
  - Stat: time_to_impact_minutes

Row 3: Agent Activity
  - Stat: total predictions
  - Stat: anomalous predictions
  - Time series: prediction_duration_seconds

Row 4: Cost
  - Time series: azure_cost_per_hour_usd (7 days)
  - Stat: estimated monthly cost
  - Gauge: budget utilization %
```

## Prometheus metrics to scrape
```
ml-service.cloudsentro:8000/metrics    every 15s
agent-service.cloudsentro:8001/metrics every 30s
```

## Ingress path
```
/grafana(/|$)(.*)  → Grafana service port 3000
rewrite-target: /$2
host: infra-pulse.cloudsentro.com
```

## Landing page content
```
dashboard/static/index.html
  - Hero: "Autonomous Infrastructure Intelligence"
  - CTA: "View Live Dashboard" → /grafana
  - 3 feature cards: ML Detection, Claude Reasoning, GitOps Remediation
  - Tech stack bar
  - No JS required, mobile responsive

dashboard/static/_redirects  (Cloudflare Pages)
  /grafana* → https://infra-pulse.cloudsentro.com/grafana/:splat 301
```

## Files in this module
```
dashboard/
├── grafana/
│   └── cloudsentro-dashboard.json   ← complete Grafana dashboard JSON
└── static/
    ├── index.html                   ← single-file landing page
    └── _redirects                   ← Cloudflare Pages redirects
```

## Deployment
```
Grafana:      deployed via Helm in infra/modules/grafana/
Landing page: deployed to Cloudflare Pages via git push
DNS:          managed by infra/modules/dns/ in Terraform
```

## What NOT to touch
- Never enable authentication on Grafana — demo must be publicly accessible
- Never add external CDN dependencies to index.html
- Never exceed 20KB on index.html
- Never hardcode the AKS ingress IP — Terraform manages it via Cloudflare DNS
