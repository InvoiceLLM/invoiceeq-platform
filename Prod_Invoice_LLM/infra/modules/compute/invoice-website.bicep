// invoice-website Container App (marketing site + SSO auth pages)
//
// Spec: Cloud_Architecture_Document.md section 4.2 -- External ingress (443),
// 0/3 replicas, 0.5 vCPU / 1Gi. Section 4.3 -- scale to zero when idle.

param location string
param caeId string
param appName string
param userAssignedIdentityId string
param userAssignedIdentityClientId string
param keyVaultName string

// App configurations
@description('Backend Container App FQDN. Used server-side only (internal ingress).')
param backendApiUrl string

@description('Frontend (invoice-fe) Container App FQDN. Used server-side only (internal ingress) to reverse-proxy FE pages -- Gap 12 Multi-Zone fix.')
param frontendApiUrl string

// Gap 172: set as a runtime env var below, in addition to the Docker
// build-arg deploy-dev.yml passes for the browser bundle. Clerk's
// server-side SDK (auth()/getToken(), used e.g. in pages/api/auth/provision.js)
// separately reads this same variable name from process.env at runtime.
@description('Clerk SSO Publishable Client Key -- baked into the client bundle via Docker build-arg AND set as a runtime env var for the server-side Clerk SDK (Gap 172).')
param nextPublicClerkPublishableKey string = ''

param acrName string
param image string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Application Insights Connection String for OpenTelemetry APM tracing')
param appInsightsConnectionString string = ''

@description('vCPU allocation, e.g. \'0.5\'.')
param cpu string = '0.5'

@description('Memory allocation, e.g. \'1.0Gi\'.')
param memory string = '1.0Gi'

@description('Minimum replica count. Dev default is 0 (scale-to-zero, per section 4.3). Prod should be >=1 -- this is the public marketing/login entry point, and scale-from-zero cold starts are user-visible there in a way they are not for internal-only apps.')
param minReplicas int = 0

@description('Maximum replica count.')
param maxReplicas int = 3

var keyVaultUrl = 'https://${keyVaultName}${environment().suffixes.keyvaultDns}'

resource websiteApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: userAssignedIdentityId
        }
      ]
      ingress: {
        external: true // Public marketing site + login/signup entry point
        targetPort: 3000
        transport: 'http'
      }
      secrets: [
        {
          name: 'clerk-secret-secret'
          keyVaultUrl: '${keyVaultUrl}/secrets/CLERK-SECRET-KEY'
          identity: userAssignedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'invoice-website'
          image: image
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            {
              // Server-side only, used by pages/api/auth/provision.js.
              // Gap 172: Container Apps ingress enforces HTTPS (allowInsecure:
              // false) even for internal, same-VNet traffic -- a plain http://
              // call gets a 301 to https:// on the identical host, and
              // fetch()/undici strips the Authorization header on that
              // scheme-change redirect per the Fetch spec's cross-origin rule.
              name: 'BACKEND_API_URL'
              value: 'https://${backendApiUrl}'
            }
            {
              // Gap 172: Clerk's server-side SDK reads this same variable
              // name from process.env at runtime -- the Docker build-arg
              // only covers the browser bundle, not this.
              name: 'NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY'
              value: nextPublicClerkPublishableKey
            }
            {
              name: 'CLERK_SECRET_KEY'
              secretRef: 'clerk-secret-secret'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: userAssignedIdentityClientId
            }
            {
              // Gap 12: turns on next.config.js's rewrites() so invoice-website
              // transparently reverse-proxies FE's pages server-side, avoiding the
              // cross-subdomain Clerk cookie handshake (PSL rejects
              // Set-Cookie Domain=azurecontainerapps.io).
              name: 'ENABLE_FE_PROXY'
              value: 'true'
            }
            {
              // Server-side only, read by next.config.js's rewrites().
              // Gap 172: Container Apps ingress enforces HTTPS (allowInsecure:
              // false) even for internal, same-VNet traffic -- a plain http://
              // call gets a 301 to https:// on the identical host, and
              // fetch()/undici strips the Authorization header on that
              // scheme-change redirect per the Fetch spec's cross-origin rule.
              name: 'FE_INTERNAL_URL'
              value: 'https://${frontendApiUrl}'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            // Gap 6: NEXT_PUBLIC_FE_URL is deliberately NOT set here -- it has
            // no server-side reader, unlike NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
            // above (Gap 172). Next.js still inlines both into the client
            // bundle during `next build` via the Docker build-args passed in
            // .github/workflows/deploy-dev.yml.
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 15
              periodSeconds: 20
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              failureThreshold: 3
              timeoutSeconds: 5
            }
            {
              type: 'Startup'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 5
              periodSeconds: 5
              failureThreshold: 12
              timeoutSeconds: 5
            }
          ]
        }
      ]
      scale: {
        // Section 4.3: scale to zero when idle (marketing site, bursty
        // traffic) -- dev default only; prod overrides minReplicas to >=1.
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            // HTTP concurrent-request trigger: marketing/login site serves
            // mostly static Next.js pages — lightest of all containers.
            // Threshold of 50 gives generous headroom per replica while still
            // protecting against sudden marketing-campaign traffic spikes
            // (e.g. 500 visitors at once from a social media post).
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = websiteApp.properties.configuration.ingress.fqdn
