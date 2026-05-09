variable "namespace" {
  type        = string
  default     = "monitoring"
  description = "Kubernetes namespace for Prometheus and Grafana."
}

variable "retention_days" {
  type        = number
  default     = 7
  description = "Prometheus retention window."
}

resource "kubernetes_namespace" "monitoring" {
  metadata {
    name = var.namespace
    labels = {
      "managed-by" = "terraform"
      "component"  = "observability"
    }
  }
}

resource "helm_release" "prometheus" {
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus"
  version    = "25.8.0"
  namespace  = kubernetes_namespace.monitoring.metadata[0].name

  set {
    name  = "server.retention"
    value = "${var.retention_days}d"
  }

  set {
    name  = "server.persistentVolume.size"
    value = "2Gi"
  }

  set {
    name  = "server.resources.requests.cpu"
    value = "100m"
  }

  set {
    name  = "server.resources.requests.memory"
    value = "128Mi"
  }

  set {
    name  = "server.resources.limits.memory"
    value = "384Mi"
  }

  # Disable the heavy default exporters — we only need scrape from app pods.
  set {
    name  = "alertmanager.enabled"
    value = "false"
  }

  set {
    name  = "kube-state-metrics.enabled"
    value = "false"
  }

  set {
    name  = "prometheus-node-exporter.enabled"
    value = "false"
  }

  set {
    name  = "prometheus-pushgateway.enabled"
    value = "false"
  }

  # Scrape cloudsentro pods that opt in via prometheus.io/* annotations.
  values = [yamlencode({
    extraScrapeConfigs = <<-EOT
      - job_name: 'ml-service'
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names: ['cloudsentro']
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            action: keep
            regex: ml-service
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
            target_label: __metrics_path__
            regex: (.+)
          - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            regex: ([^:]+)(?::\d+)?;(\d+)
            replacement: $1:$2
            target_label: __address__
        scrape_interval: 15s
      - job_name: 'agent-service'
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names: ['cloudsentro']
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            action: keep
            regex: agent-service
          - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            regex: ([^:]+)(?::\d+)?;(\d+)
            replacement: $1:$2
            target_label: __address__
        scrape_interval: 30s
    EOT
  })]

  timeout = 600
  wait    = true
}

output "namespace" {
  value       = kubernetes_namespace.monitoring.metadata[0].name
  description = "Namespace where monitoring components live."
}

output "service_url" {
  value       = "http://prometheus-server.${kubernetes_namespace.monitoring.metadata[0].name}.svc.cluster.local"
  description = "Cluster-internal Prometheus URL — used by the Grafana datasource."
}
