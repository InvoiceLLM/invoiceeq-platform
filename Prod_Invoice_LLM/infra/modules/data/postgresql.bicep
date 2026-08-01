param location string
param serverName string
param adminLogin string
@secure()
param adminPassword string
param subnetId string
param privateDnsZoneId string

@description('Whether to provision private networking. VNet-injected (delegated subnet) and public-access server modes are mutually exclusive on Postgres Flexible Server -- this flips the whole network{} block, not just a toggle. false = public network access + AllowAllAzureIPs firewall rule (dev); true = VNet-injected, no public access (prod).')
param networkIsolation bool = false

@description('Postgres Flexible Server compute SKU name. Dev default is Burstable/cheap; prod should move to a General Purpose tier.')
param skuName string = 'Standard_B2s'

@description('Postgres Flexible Server compute SKU tier.')
param skuTier string = 'Burstable'

@description('Allocated storage in GB.')
param storageSizeGB int = 32

@description('Backup retention window in days.')
param backupRetentionDays int = 7

@description('Whether backups are geo-redundant. Off by default (dev); recommended on for prod.')
param geoRedundantBackup string = 'Disabled'

@description('High-availability mode. Left Disabled for both dev and prod for now -- zone-redundant HA is a real recurring cost add and this stack is pre-customer/minimum-expense; revisit once there are paying customers to justify it.')
param highAvailabilityMode string = 'Disabled'

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: serverName
  location: location
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    version: '16'
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    network: networkIsolation ? {
      delegatedSubnetResourceId: subnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
    } : {
      publicNetworkAccess: 'Enabled'
    }
    storage: {
      storageSizeGB: storageSizeGB
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup
    }
    highAvailability: {
      mode: highAvailabilityMode
    }
  }
}

// Only meaningful (and only created) when the server is in public-access mode --
// VNet-injected servers reject all public traffic by definition, so this rule
// would be a no-op there. Azure's documented "magic" range for allowing all
// Azure-hosted callers (incl. Container Apps' outbound IPs, which are dynamic
// and not otherwise enumerable) through the Postgres firewall.
resource allowAllAzureIps 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = if (!networkIsolation) {
  parent: postgresServer
  name: 'AllowAllAzureIPs'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgresServer
  name: 'invoice_db'
  properties: {
    charset: 'utf8'
    collation: 'en_US.utf8'
  }
}

output serverId string = postgresServer.id
output fqdn string = postgresServer.properties.fullyQualifiedDomainName
