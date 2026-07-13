param location string
param serverName string
param adminLogin string
@secure()
param adminPassword string
param subnetId string
param privateDnsZoneId string

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: serverName
  location: location
  sku: {
    name: 'Standard_B2s' // Burstable tier for Dev
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    network: {
      delegatedSubnetResourceId: subnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
    }
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
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
