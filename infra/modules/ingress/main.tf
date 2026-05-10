variable "namespace" {
  type        = string
  default     = "ingress-nginx"
  description = "Kubernetes namespace for the ingress controller."
}

resource "kubernetes_namespace" "ingress" {
  metadata {
    name = var.namespace
    labels = {
      "managed-by" = "terraform"
      "component"  = "ingress"
    }
  }
}

resource "helm_release" "nginx" {
  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  version    = "4.8.3"
  namespace  = kubernetes_namespace.ingress.metadata[0].name

  # Light footprint for B2s budget. Single replica, conservative resources.
  set {
    name  = "controller.replicaCount"
    value = "1"
  }

  set {
    name  = "controller.service.type"
    value = "LoadBalancer"
  }

  # Local externalTrafficPolicy avoids an AKS quirk where the cloud-controller
  # creates an LB rule with backendPort=80 + enableFloatingIp=null, which makes
  # the LB DNAT to a port nothing on the node listens on. With "Local" the LB
  # uses Direct Server Return (enableFloatingIp=true) and traffic flows.
  set {
    name  = "controller.service.externalTrafficPolicy"
    value = "Local"
  }

  # Force TCP health probe instead of HTTP GET / (which the controller
  # answers with 404 by default — failing the probe and dropping the backend).
  set {
    name  = "controller.service.annotations.service\\.beta\\.kubernetes\\.io/azure-load-balancer-health-probe-protocol"
    value = "tcp"
  }

  # Cloudflare proxy compatibility — preserve real client IP through CF.
  set {
    name  = "controller.config.use-forwarded-headers"
    value = "true"
  }

  set {
    name  = "controller.config.compute-full-forwarded-for"
    value = "true"
  }

  set {
    name  = "controller.resources.requests.cpu"
    value = "50m"
  }

  set {
    name  = "controller.resources.requests.memory"
    value = "64Mi"
  }

  set {
    name  = "controller.resources.limits.cpu"
    value = "200m"
  }

  set {
    name  = "controller.resources.limits.memory"
    value = "192Mi"
  }

  set {
    name  = "controller.admissionWebhooks.enabled"
    value = "false"
  }

  timeout = 600
  wait    = true
}

# Azure assigns the LoadBalancer IP asynchronously; helm_release returns
# before the IP is ready. This data source polls until it's populated.
data "kubernetes_service" "ingress_lb" {
  metadata {
    name      = "${helm_release.nginx.name}-controller"
    namespace = kubernetes_namespace.ingress.metadata[0].name
  }
  depends_on = [helm_release.nginx]
}

locals {
  ingress_ip = try(
    data.kubernetes_service.ingress_lb.status[0].load_balancer[0].ingress[0].ip,
    ""
  )
}

output "namespace" {
  value       = kubernetes_namespace.ingress.metadata[0].name
  description = "Namespace where the ingress controller is installed."
}

output "ingress_class_name" {
  value       = "nginx"
  description = "ingressClassName to set on Ingress resources."
}

output "public_ip" {
  value       = local.ingress_ip
  description = "Public IP of the ingress controller's LoadBalancer service."
}
