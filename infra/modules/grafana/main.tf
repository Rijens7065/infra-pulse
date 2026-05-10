variable "namespace" {
  type        = string
  description = "Kubernetes namespace shared with Prometheus."
}

variable "ingress_class_name" {
  type        = string
  description = "Ingress class to use for the Grafana Ingress resource."
}

variable "key_vault_id" {
  type        = string
  description = "Key Vault to store the generated Grafana admin password."
}

variable "prometheus_url" {
  type        = string
  description = "Cluster-internal Prometheus URL for the default datasource."
}

variable "public_hostname" {
  type        = string
  description = "Public hostname Grafana is served from (used in root_url)."
}

variable "dashboard_json" {
  type        = string
  description = "Grafana dashboard JSON content, mounted as a ConfigMap."
}

resource "random_password" "grafana_admin" {
  length           = 24
  special          = true
  min_special      = 2
  override_special = "!@#%^&*-_=+"
}

resource "azurerm_key_vault_secret" "grafana_admin" {
  name         = "grafana-admin-password"
  value        = random_password.grafana_admin.result
  key_vault_id = var.key_vault_id
}

resource "kubernetes_secret" "grafana_admin" {
  metadata {
    name      = "grafana-admin"
    namespace = var.namespace
  }
  data = {
    "admin-user"     = "admin"
    "admin-password" = random_password.grafana_admin.result
  }
  type = "Opaque"
}

resource "kubernetes_config_map" "dashboard" {
  metadata {
    name      = "grafana-dashboard-cloudsentro"
    namespace = var.namespace
    labels = {
      grafana_dashboard = "1"
    }
  }
  data = {
    "cloudsentro.json" = var.dashboard_json
  }
}

resource "helm_release" "grafana" {
  name       = "grafana"
  repository = "https://grafana.github.io/helm-charts"
  chart      = "grafana"
  version    = "7.0.19"
  namespace  = var.namespace

  set {
    name  = "admin.existingSecret"
    value = kubernetes_secret.grafana_admin.metadata[0].name
  }

  set {
    name  = "admin.userKey"
    value = "admin-user"
  }

  set {
    name  = "admin.passwordKey"
    value = "admin-password"
  }

  set {
    name  = "persistence.enabled"
    value = "false"
  }

  set {
    name  = "resources.requests.cpu"
    value = "50m"
  }

  set {
    name  = "resources.requests.memory"
    value = "96Mi"
  }

  set {
    name  = "resources.limits.memory"
    value = "256Mi"
  }

  values = [yamlencode({
    "grafana.ini" = {
      server = {
        root_url            = "https://${var.public_hostname}/grafana"
        serve_from_sub_path = true
      }
      "auth.anonymous" = {
        enabled  = true
        org_role = "Viewer"
      }
      security = {
        allow_embedding = true
      }
      analytics = {
        check_for_updates = false
        reporting_enabled = false
      }
    }
    datasources = {
      "datasources.yaml" = {
        apiVersion = 1
        datasources = [
          {
            name      = "Prometheus"
            type      = "prometheus"
            url       = var.prometheus_url
            access    = "proxy"
            isDefault = true
          }
        ]
      }
    }
    # Dashboards are loaded exclusively via the sidecar — it watches
    # ConfigMaps with label grafana_dashboard=1 and uploads them via
    # Grafana's HTTP API. defaultFolderName puts every imported dashboard
    # into the "CloudSentro" folder so we don't end up with two folders
    # (one from the provider config, one from the API import).
    sidecar = {
      dashboards = {
        enabled           = true
        searchNamespace   = var.namespace
        label             = "grafana_dashboard"
        labelValue        = "1"
        folder            = "/tmp/dashboards"
        defaultFolderName = "CloudSentro"
        provider = {
          allowUiUpdates = false
          foldersFromFilesStructure = false
        }
      }
    }
  })]

  timeout = 600
  wait    = true

  depends_on = [
    kubernetes_secret.grafana_admin,
    kubernetes_config_map.dashboard,
  ]
}

resource "kubernetes_ingress_v1" "grafana" {
  metadata {
    name      = "grafana"
    namespace = var.namespace
  }

  # No rewrite annotation — Grafana is configured with serve_from_sub_path=true
  # and root_url=https://.../grafana, so it expects to receive requests at
  # /grafana/... directly. Stripping the prefix with a rewrite annotation
  # creates an infinite redirect loop (Grafana redirects / → /grafana → /).
  spec {
    ingress_class_name = var.ingress_class_name
    rule {
      host = var.public_hostname
      http {
        path {
          path      = "/grafana"
          path_type = "Prefix"
          backend {
            service {
              name = "grafana"
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }

  depends_on = [helm_release.grafana]
}

output "service_name" {
  value       = "grafana"
  description = "Cluster-internal Grafana service name."
}

output "admin_password_secret_name" {
  value       = azurerm_key_vault_secret.grafana_admin.name
  description = "Key Vault secret name for the generated Grafana admin password."
  sensitive   = true
}
