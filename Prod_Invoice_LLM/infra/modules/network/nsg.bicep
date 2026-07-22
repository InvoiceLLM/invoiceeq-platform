param location string
param namingPrefix string
param environment string

// Three trust boundaries, matching Cloud_Architecture_Document.md §3.2:
// - aca-subnet: the only subnet allowed to receive traffic from the internet (frontend ingress)
// - data + postgres subnets: only reachable from aca-subnet (Postgres, Redis, Storage, ACR private endpoints)
// - ai subnet: only reachable from aca-subnet (OpenAI, Doc Intelligence private endpoints)
var acaSubnetCidr = '10.0.1.0/24'

resource nsgAca 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-aca-${namingPrefix}-${environment}'
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowHttpsInbound'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource nsgData 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-data-${namingPrefix}-${environment}'
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowFromAcaSubnet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: acaSubnetCidr
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource nsgAi 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-ai-${namingPrefix}-${environment}'
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowFromAcaSubnet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: acaSubnetCidr
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

output nsgAcaId string = nsgAca.id
output nsgDataId string = nsgData.id
output nsgAiId string = nsgAi.id
