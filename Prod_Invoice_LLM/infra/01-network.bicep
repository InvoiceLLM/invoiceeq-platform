targetScope = 'resourceGroup'

// ================= Stage 1: Network =================
// VNet, 4 subnets, 7 private DNS zones + VNet links, and 3 NSGs
// (Cloud_Architecture_Document.md §3). Nothing else in this stack depends
// on anything upstream of this stage, so it always runs first.
//
// networkIsolation=false (dev): this entire stage is a no-op -- no VNet,
// no NSGs, no private DNS zones are created. Every downstream stage that
// would otherwise reference this stage's subnet/DNS-zone IDs receives
// empty strings instead and switches its resources to public/key-auth
// access (see 02-security.bicep/03-data.bicep/04-ai.bicep/06-compute-env.bicep).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Whether to provision private networking (VNet, subnets, private DNS zones, NSGs). false = no-op stage (dev); true = full private network (prod).')
param networkIsolation bool = false

var vnetName = 'vnet-${namingPrefix}-${environment}'

module nsg './modules/network/nsg.bicep' = if (networkIsolation) {
  name: 'nsg-deploy'
  params: {
    location: location
    namingPrefix: namingPrefix
    environment: environment
  }
}

module network './modules/network/vnet.bicep' = if (networkIsolation) {
  name: 'network-deploy'
  params: {
    location: location
    vnetName: vnetName
    nsgAcaId: nsg.?outputs.?nsgAcaId ?? ''
    nsgDataId: nsg.?outputs.?nsgDataId ?? ''
    nsgAiId: nsg.?outputs.?nsgAiId ?? ''
  }
}

// ================= Outputs =================
output vnetName string = vnetName
