param location string
param namingPrefix string = 'invoice-llm'
param environment string = 'dev'

@description('IANA/Windows timezone name for the schedule, e.g. India Standard Time')
param scheduleTimezone string = 'India Standard Time'

@description('Hour (0-23) to scale UP to business-hours replica counts')
param scaleUpHour int = 9

@description('Hour (0-23) to scale DOWN to minimal/zero replica counts')
param scaleDownHour int = 20

@description('Replica counts to use during business hours: [minReplicas, maxReplicas]')
param businessHoursScale object = {
  backend: { min: 1, max: 5 }
  worker: { min: 1, max: 3 }
  frontend: { min: 1, max: 2 }
}

@description('Replica counts to use outside business hours')
param offHoursScale object = {
  backend: { min: 0, max: 1 }
  worker: { min: 0, max: 1 }
  frontend: { min: 0, max: 1 }
}

var backendAppName = 'ca-invoice-be-${environment}'
var workerAppName = 'ca-celery-worker-${environment}'
var frontendAppName = 'ca-invoice-fe-${environment}'
var containerAppsApiVersion = '2024-03-01'

// Container Apps Contributor - confirmed built-in role ID
var containerAppsContributorRoleId = '358470bc-b998-42bd-ab17-a7e34c199c0f'

resource scaleUpIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-scheduler-scaleup-${namingPrefix}-${environment}'
  location: location
}

resource scaleDownIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-scheduler-scaledown-${namingPrefix}-${environment}'
  location: location
}

resource scaleUpRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, scaleUpIdentity.id, containerAppsContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', containerAppsContributorRoleId)
    principalId: scaleUpIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource scaleDownRbac 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, scaleDownIdentity.id, containerAppsContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', containerAppsContributorRoleId)
    principalId: scaleDownIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// -------- Scale UP workflow (fires once daily at scaleUpHour) --------
resource scaleUpLogicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-scaleup-${namingPrefix}-${environment}'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${scaleUpIdentity.id}': {}
    }
  }
  dependsOn: [
    scaleUpRbac
  ]
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: {
        DailyScaleUp: {
          type: 'Recurrence'
          recurrence: {
            frequency: 'Day'
            interval: 1
            timeZone: scheduleTimezone
            schedule: {
              hours: [ string(scaleUpHour) ]
              minutes: [ 0 ]
            }
          }
        }
      }
      actions: {
        PatchBackend: {
          type: 'Http'
          inputs: {
            method: 'PATCH'
            uri: 'https://management.azure.com/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.App/containerApps/${backendAppName}?api-version=${containerAppsApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: scaleUpIdentity.id
            }
            body: {
              properties: {
                template: {
                  scale: {
                    minReplicas: businessHoursScale.backend.min
                    maxReplicas: businessHoursScale.backend.max
                  }
                }
              }
            }
          }
        }
        PatchWorker: {
          type: 'Http'
          inputs: {
            method: 'PATCH'
            uri: 'https://management.azure.com/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.App/containerApps/${workerAppName}?api-version=${containerAppsApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: scaleUpIdentity.id
            }
            body: {
              properties: {
                template: {
                  scale: {
                    minReplicas: businessHoursScale.worker.min
                    maxReplicas: businessHoursScale.worker.max
                  }
                }
              }
            }
          }
        }
        PatchFrontend: {
          type: 'Http'
          inputs: {
            method: 'PATCH'
            uri: 'https://management.azure.com/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.App/containerApps/${frontendAppName}?api-version=${containerAppsApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: scaleUpIdentity.id
            }
            body: {
              properties: {
                template: {
                  scale: {
                    minReplicas: businessHoursScale.frontend.min
                    maxReplicas: businessHoursScale.frontend.max
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

// -------- Scale DOWN workflow (fires once daily at scaleDownHour) --------
resource scaleDownLogicApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-scaledown-${namingPrefix}-${environment}'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${scaleDownIdentity.id}': {}
    }
  }
  dependsOn: [
    scaleDownRbac
  ]
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: {
        DailyScaleDown: {
          type: 'Recurrence'
          recurrence: {
            frequency: 'Day'
            interval: 1
            timeZone: scheduleTimezone
            schedule: {
              hours: [ string(scaleDownHour) ]
              minutes: [ 0 ]
            }
          }
        }
      }
      actions: {
        PatchBackend: {
          type: 'Http'
          inputs: {
            method: 'PATCH'
            uri: 'https://management.azure.com/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.App/containerApps/${backendAppName}?api-version=${containerAppsApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: scaleDownIdentity.id
            }
            body: {
              properties: {
                template: {
                  scale: {
                    minReplicas: offHoursScale.backend.min
                    maxReplicas: offHoursScale.backend.max
                  }
                }
              }
            }
          }
        }
        PatchWorker: {
          type: 'Http'
          inputs: {
            method: 'PATCH'
            uri: 'https://management.azure.com/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.App/containerApps/${workerAppName}?api-version=${containerAppsApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: scaleDownIdentity.id
            }
            body: {
              properties: {
                template: {
                  scale: {
                    minReplicas: offHoursScale.worker.min
                    maxReplicas: offHoursScale.worker.max
                  }
                }
              }
            }
          }
        }
        PatchFrontend: {
          type: 'Http'
          inputs: {
            method: 'PATCH'
            uri: 'https://management.azure.com/subscriptions/${subscription().subscriptionId}/resourceGroups/${resourceGroup().name}/providers/Microsoft.App/containerApps/${frontendAppName}?api-version=${containerAppsApiVersion}'
            authentication: {
              type: 'ManagedServiceIdentity'
              identity: scaleDownIdentity.id
            }
            body: {
              properties: {
                template: {
                  scale: {
                    minReplicas: offHoursScale.frontend.min
                    maxReplicas: offHoursScale.frontend.max
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

output scaleUpLogicAppId string = scaleUpLogicApp.id
output scaleDownLogicAppId string = scaleDownLogicApp.id
