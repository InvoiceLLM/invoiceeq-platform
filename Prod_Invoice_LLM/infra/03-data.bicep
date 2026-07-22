targetScope = 'resourceGroup'

// ================= Stage 3: Data Services =================
// Postgres, Redis Enterprise, Storage (blob + single queue private
// endpoint), ACR. Depends on Stage 1 only (subnets + DNS zones).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Admin login name for PostgreSQL')
param dbAdminLogin string = 'dbadmin'

@description('Secure admin password for PostgreSQL')
@secure()
param dbAdminPassword string

@description('Whether to deploy Redis (skip if it already exists and is Running — Redis Enterprise cannot be redeployed in place once created)')
param deployRedis bool = true

var vnetName = 'vnet-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var acrName = 'acr${replace(namingPrefix, '-', '')}${environment}'

var postgresSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-postgres')
var peSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-pe')
var postgresDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.postgres.database.azure.com')
var redisDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.redisenterprise.cache.azure.net')
var storageDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.blob.core.windows.net')
var queueDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.queue.core.windows.net')
var acrDnsZoneId = resourceId('Microsoft.Network/privateDnsZones', 'privatelink.azurecr.io')

module postgresql './modules/data/postgresql.bicep' = {
  name: 'postgresql-deploy'
  params: {
    location: location
    serverName: 'psql-${namingPrefix}-${environment}'
    adminLogin: dbAdminLogin
    adminPassword: dbAdminPassword
    subnetId: postgresSubnetId
    privateDnsZoneId: postgresDnsZoneId
  }
}

module redis './modules/data/redis.bicep' = if (deployRedis) {
  name: 'redis-deploy'
  params: {
    location: location
    redisName: 'redis-${namingPrefix}-${environment}'
    subnetId: peSubnetId
    privateDnsZoneId: redisDnsZoneId
  }
}

module storage './modules/data/storage.bicep' = {
  name: 'storage-deploy'
  params: {
    location: location
    storageAccountName: storageAccountName
    subnetId: peSubnetId
    privateDnsZoneId: storageDnsZoneId
    queueDnsZoneId: queueDnsZoneId
  }
}

module acr './modules/data/acr.bicep' = {
  name: 'acr-deploy'
  params: {
    location: location
    acrName: acrName
    subnetId: peSubnetId
    privateDnsZoneId: acrDnsZoneId
  }
}

// ================= Outputs =================
output storageAccountName string = storageAccountName
output acrName string = acrName
output postgresFqdn string = postgresql.outputs.fqdn
