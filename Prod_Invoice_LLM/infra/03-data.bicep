targetScope = 'resourceGroup'

// ================= Stage 3: Data Services =================
// Postgres, Redis Enterprise, Storage (blob + single queue private
// endpoint), ACR. Depends on Stage 1 only (subnets + DNS zones).
//
// ACR is a SHARED resource across dev and prod (one registry, both
// environments pull from it -- see deployAcr/sharedAcrName/
// sharedAcrResourceGroup below). Everything else in this stage (Postgres,
// Redis, Storage) is per-environment and always deploys.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Whether to provision private networking for Postgres/Redis/Storage. false = public/key-auth access (dev); true = VNet-injected/private-endpoint-only (prod).')
param networkIsolation bool = false

@description('Admin login name for PostgreSQL')
param dbAdminLogin string = 'dbadmin'

@description('Secure admin password for PostgreSQL')
@secure()
param dbAdminPassword string

@description('Whether to deploy Redis (skip if it already exists and is Running — Redis Enterprise cannot be redeployed in place once created)')
param deployRedis bool = true

@description('Postgres Flexible Server compute SKU name.')
param postgresSkuName string = 'Standard_B2s'

@description('Postgres Flexible Server compute SKU tier.')
param postgresSkuTier string = 'Burstable'

@description('Postgres allocated storage in GB.')
param postgresStorageSizeGB int = 32

@description('Postgres backup retention window in days.')
param postgresBackupRetentionDays int = 7

@description('Postgres geo-redundant backup setting.')
param postgresGeoRedundantBackup string = 'Disabled'

@description('Postgres high-availability mode. Left Disabled for both envs for now -- zone-redundant HA is a real recurring cost add, deferred until there are paying customers.')
param postgresHighAvailabilityMode string = 'Disabled'

@description('Storage account replication SKU. Standard_LRS (dev) is cheapest; Standard_ZRS is recommended for prod (invoice PDFs have no other copy) but costs ~25% more -- a conscious choice, not a silent upgrade.')
param storageSkuName string = 'Standard_LRS'

@description('Storage account public network access. Only meaningful when networkIsolation=false.')
param storagePublicNetworkAccess string = 'Enabled'

@description('Whether this deployment owns/creates the shared ACR resource. true for whichever environment is designated the ACR owner (dev, today); false for environments that only consume it (prod) -- those pull sharedAcrName/sharedAcrResourceGroup instead of deploying a second registry.')
param deployAcr bool = true

@description('Name of the shared ACR registry. Defaults to this environment\'s own computed name (used when deployAcr=true, i.e. this deployment owns it). Environments that do not own it (deployAcr=false) must set this explicitly to the owning environment\'s registry name.')
param sharedAcrName string = 'acr${replace(namingPrefix, '-', '')}${environment}'

@description('Resource group that owns the shared ACR registry. Defaults to this deployment\'s own resource group (used when deployAcr=true). Environments that do not own it (deployAcr=false) must set this explicitly to the owning environment\'s resource group name.')
param sharedAcrResourceGroup string = resourceGroup().name

var vnetName = 'vnet-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'

var postgresSubnetId = networkIsolation ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-postgres') : ''
var peSubnetId = networkIsolation ? resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-pe') : ''
var postgresDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.postgres.database.azure.com') : ''
var redisDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.redisenterprise.cache.azure.net') : ''
var storageDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.blob.core.windows.net') : ''
var queueDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.queue.core.windows.net') : ''
var acrDnsZoneId = networkIsolation ? resourceId('Microsoft.Network/privateDnsZones', 'privatelink.azurecr.io') : ''

module postgresql './modules/data/postgresql.bicep' = {
  name: 'postgresql-deploy'
  params: {
    location: location
    serverName: 'psql-${namingPrefix}-${environment}'
    adminLogin: dbAdminLogin
    adminPassword: dbAdminPassword
    networkIsolation: networkIsolation
    subnetId: postgresSubnetId
    privateDnsZoneId: postgresDnsZoneId
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    storageSizeGB: postgresStorageSizeGB
    backupRetentionDays: postgresBackupRetentionDays
    geoRedundantBackup: postgresGeoRedundantBackup
    highAvailabilityMode: postgresHighAvailabilityMode
  }
}

module redis './modules/data/redis.bicep' = if (deployRedis) {
  name: 'redis-deploy'
  params: {
    location: location
    redisName: 'redis-${namingPrefix}-${environment}'
    networkIsolation: networkIsolation
    subnetId: peSubnetId
    privateDnsZoneId: redisDnsZoneId
  }
}

module storage './modules/data/storage.bicep' = {
  name: 'storage-deploy'
  params: {
    location: location
    storageAccountName: storageAccountName
    networkIsolation: networkIsolation
    subnetId: peSubnetId
    privateDnsZoneId: storageDnsZoneId
    queueDnsZoneId: queueDnsZoneId
    skuName: storageSkuName
    publicNetworkAccess: storagePublicNetworkAccess
  }
}

// Shared ACR: only actually created when this deployment is the designated
// owner (deployAcr=true). deploy-all.ps1 scopes every deployment to a
// single resource group per run (-ResourceGroup), so "shared across
// environments" cannot mean "create it once and reference it from a module
// living in the other RG's deployment" -- there is no cross-RG module
// invocation that also *creates* a resource in a foreign RG from this
// template. Instead: the owning environment (today, dev) deploys it here
// as normal; the non-owning environment (prod) sets deployAcr=false and
// points sharedAcrName/sharedAcrResourceGroup at dev's registry, and every
// downstream consumer (07-rbac.bicep's cross-RG AcrPull, 08-apps.bicep's
// image references) reads those params instead of a local Stage 3 output.
module acr './modules/data/acr.bicep' = if (deployAcr) {
  name: 'acr-deploy'
  params: {
    location: location
    acrName: sharedAcrName
    subnetId: peSubnetId
    privateDnsZoneId: acrDnsZoneId
    deployPrivateEndpoint: networkIsolation
  }
}

// ================= Outputs =================
output storageAccountName string = storageAccountName
output acrName string = sharedAcrName
output acrResourceGroup string = sharedAcrResourceGroup
output postgresFqdn string = postgresql.outputs.fqdn
