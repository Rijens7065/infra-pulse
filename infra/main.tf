module "resource_group" {
  source      = "./modules/resource_group"
  location    = var.location
  environment = var.environment
  project     = var.project
}

module "acr" {
  source              = "./modules/acr"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  environment         = var.environment
  project             = var.project
  pusher_principal_id = var.principal_id

  depends_on = [module.resource_group]
}

module "aks" {
  source              = "./modules/aks"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  environment         = var.environment
  project             = var.project

  depends_on = [module.resource_group]
}

module "keyvault" {
  source                      = "./modules/keyvault"
  resource_group_name         = module.resource_group.name
  location                    = module.resource_group.location
  tenant_id                   = var.tenant_id
  environment                 = var.environment
  project                     = var.project
  secrets_writer_principal_id = var.terraform_runner_principal_id

  depends_on = [module.resource_group]
}

module "budget" {
  source            = "./modules/budget"
  resource_group_id = module.resource_group.id
  alert_email       = var.alert_email

  depends_on = [module.resource_group]
}

# identity module deferred to Phase 2/3 — requires Global Administrator
# to grant Application.ReadWrite.All to the managed identity in Entra ID

# ── Phase 4: dashboard layer ───────────────────────────────────────────────

module "ingress" {
  source = "./modules/ingress"

  depends_on = [module.aks]
}

module "prometheus" {
  source = "./modules/prometheus"

  depends_on = [module.aks]
}

module "grafana" {
  source             = "./modules/grafana"
  namespace          = module.prometheus.namespace
  ingress_class_name = module.ingress.ingress_class_name
  key_vault_id       = module.keyvault.id
  prometheus_url     = module.prometheus.service_url
  public_hostname    = "${var.subdomain}.${var.domain}"
  dashboard_json     = file("${path.module}/../dashboard/grafana/cloudsentro-dashboard.json")

  depends_on = [
    module.prometheus,
    module.ingress,
    module.keyvault,
  ]
}

module "nsg" {
  source              = "./modules/nsg"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  node_resource_group = module.aks.node_resource_group
  admin_ip            = var.admin_ip
  environment         = var.environment
  project             = var.project

  depends_on = [module.aks]
}

module "dns" {
  source            = "./modules/dns"
  zone_id           = var.cloudflare_zone_id
  subdomain         = var.subdomain
  ingress_public_ip = module.ingress.public_ip

  depends_on = [module.ingress]
}
