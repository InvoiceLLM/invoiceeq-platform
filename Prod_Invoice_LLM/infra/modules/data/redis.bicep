param location string
param redisName string
param subnetId string
param privateDnsZoneId string

@description('Whether to provision private networking. false = public network access, key-auth reachable (dev -- load-bearing for SSE progress + OAuth PKCE state, no PE); true = private-endpoint-only (prod).')
param networkIsolation bool = false

@description('Public network access for the Redis Enterprise cluster. Only meaningful when networkIsolation=false -- ignored/irrelevant once a private endpoint is the only path in. Verified against the Microsoft.Cache/redisEnterprise@2025-07-01 API (the first stable version whose ClusterProperties actually exposes this field -- 2025-04-01, used elsewhere in this stack for `existing` references, does not have it).')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

// Azure Managed Redis (Redis Enterprise) — replaces the retiring
// Microsoft.Cache/Redis (Basic/Standard/Premium) SKU.
// Balanced_B0 is the smallest Redis Enterprise SKU, roughly comparable
// to a Standard C1 cache. Adjust sku.name/capacity for your workload.
//
// API version bumped 2025-04-01 -> 2025-07-01 (first stable version with
// ClusterProperties.publicNetworkAccess; confirmed via `az bicep build`
// against both versions -- 2025-04-01's ClusterProperties only permits
// encryption/highAvailability/minimumTlsVersion).
resource redisEnterpriseCache 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: redisName
  location: location
  sku: {
    name: 'Balanced_B0'
  }
  properties: {
    minimumTlsVersion: '1.2'
    highAvailability: 'Enabled'
    publicNetworkAccess: networkIsolation ? 'Disabled' : publicNetworkAccess
  }
}

// Default database — required child resource; Redis Enterprise
// doesn't function without at least one database defined.
resource redisEnterpriseDatabase 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  name: 'default'
  parent: redisEnterpriseCache
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    clusteringPolicy: 'OSSCluster'
    evictionPolicy: 'NoEviction'
    accessKeysAuthentication: 'Enabled' // keep access-key auth on for the connection-string pattern main.bicep already uses
  }
}

// Private Endpoint for Redis Enterprise
// NOTE groupIds is 'redisEnterprise', NOT 'redisCache' (that group is only for the old Microsoft.Cache/Redis resource type)
resource redisPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = if (networkIsolation) {
  name: '${redisName}-pe'
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${redisName}-connection'
        properties: {
          privateLinkServiceId: redisEnterpriseCache.id
          groupIds: [
            'redisEnterprise'
          ]
        }
      }
    ]
  }
}

// Private DNS Group Zone Config for Private Endpoint
resource redisPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = if (networkIsolation) {
  parent: redisPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis-config'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

output redisId string = redisEnterpriseCache.id
output host string = redisEnterpriseCache.properties.hostName
output port int = redisEnterpriseDatabase.properties.port
output primaryKey string = redisEnterpriseDatabase.listKeys().primaryKey
