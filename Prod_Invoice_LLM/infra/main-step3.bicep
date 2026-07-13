targetScope = 'resourceGroup'

// ================= Parameters =================
@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'


@description('Storage account name from step1')
param storageAccountName string

@description('Storage account key from step1')
@secure()
param storageAccountKey string

// ================= Variables =================
var caeName = 'cae-${namingPrefix}-${environment}'
var vnetName = 'vnet-${namingPrefix}-${environment}'

// Get VNet outputs from existing deployment
module network './modules/network/vnet.bicep' = {
  name: 'network-reference'
  params: {
    location: location
    vnetName: vnetName
  }
}

// ================= 1. Container Apps Environment =================
module containerEnv './modules/compute/container-env.bicep' = {
  name: 'container-env-deploy'
  params: {
    location: location
    caeName: caeName
    subnetId: network.outputs.acaSubnetId
  }
}

// ================= 2. Vector Database (ChromaDB Container) =================
module chromadb './modules/data/chromadb.bicep' = {
  name: 'chromadb-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-chromadb-${environment}'
    storageAccountName: storageAccountName
    storageAccountKey: storageAccountKey
  }
}



// ================= Outputs =================
output caeId string = containerEnv.outputs.caeId
output chromaDbFqdn string = chromadb.outputs.internalFqdn
