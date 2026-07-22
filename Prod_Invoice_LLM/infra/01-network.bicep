targetScope = 'resourceGroup'

// ================= Stage 1: Network =================
// VNet, 4 subnets, 7 private DNS zones + VNet links, and 3 NSGs
// (Cloud_Architecture_Document.md §3). Nothing else in this stack depends
// on anything upstream of this stage, so it always runs first.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

var vnetName = 'vnet-${namingPrefix}-${environment}'

module nsg './modules/network/nsg.bicep' = {
  name: 'nsg-deploy'
  params: {
    location: location
    namingPrefix: namingPrefix
    environment: environment
  }
}

module network './modules/network/vnet.bicep' = {
  name: 'network-deploy'
  params: {
    location: location
    vnetName: vnetName
    nsgAcaId: nsg.outputs.nsgAcaId
    nsgDataId: nsg.outputs.nsgDataId
    nsgAiId: nsg.outputs.nsgAiId
  }
}

// ================= Outputs =================
output vnetName string = vnetName
