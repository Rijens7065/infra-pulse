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

# identity module deferred to Phase 2/3 — requires Global Administrator
# to grant Application.ReadWrite.All to the managed identity in Entra ID
