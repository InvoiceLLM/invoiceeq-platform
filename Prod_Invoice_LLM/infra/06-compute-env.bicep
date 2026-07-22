targetScope = 'resourceGroup'

// ================= Stage 6: Container Apps Environment + ChromaDB =================
// Depends on Stage 1 (aca subnet) and Stage 3 (storage account for the
// ChromaDB file share).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

var vnetName = 'vnet-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var acaSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-aca')

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

module containerEnv './modules/compute/container-env.bicep' = {
  name: 'container-env-deploy'
  params: {
    location: location
    caeName: caeName
    subnetId: acaSubnetId
  }
}

module chromadb './modules/data/chromadb.bicep' = {
  name: 'chromadb-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-chromadb-${environment}'
    storageAccountName: storageAccountName
    storageAccountKey: storageAccount.listKeys().keys[0].value
  }
}

// ================= Outputs =================
output caeId string = containerEnv.outputs.caeId
output chromaDbFqdn string = chromadb.outputs.internalFqdn
