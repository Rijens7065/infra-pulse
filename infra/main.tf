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
  source              = "./modules/keyvault"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tenant_id           = var.tenant_id
  environment         = var.environment
  project             = var.project

  depends_on = [module.resource_group]
}

module "budget" {
  source            = "./modules/budget"
  resource_group_id = module.resource_group.id
  alert_email       = var.alert_email

  depends_on = [module.resource_group]
}

module "identity" {
  source            = "./modules/identity"
  resource_group_id = module.resource_group.id
  aks_id            = module.aks.id
  keyvault_id       = module.keyvault.id
  oidc_issuer_url   = module.aks.oidc_issuer_url

  depends_on = [module.aks, module.keyvault]
}
