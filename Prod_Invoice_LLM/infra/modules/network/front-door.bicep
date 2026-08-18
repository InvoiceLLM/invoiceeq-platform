// Azure Front Door (Standard) + WAF, sitting in front of invoice-website's
// Container App. Documented as Layer 1 of the security architecture in
// Cloud_Architecture_Document.md section 12 (DDoS protection, geo-filtering,
// WAF) but never actually built -- this module closes that gap.
//
// Deployed only when `customDomainName` is non-empty (see 08-apps.bicep) --
// this whole module is a safe no-op until a real domain is supplied.
//
// Standard tier chosen over Premium: Premium's extra features (managed WAF
// rule sets beyond the Default Rule Set, private-link-to-origin) aren't
// needed here -- the origin (invoice-website's Container App) is already
// publicly reachable at its CAE FQDN, and this repo has no other Front-Door-
// fronted origin that would justify Premium's managed bot-protection ruleset.
// Revisit if that changes. Cost: ~$35/mo base (Standard) vs ~$330/mo (Premium)
// before usage -- see Cloud_Architecture_Document.md 14.1's $50-100/mo Front
// Door + WAF line, which assumes Standard.

@description('Azure region for resource provisioning. Front Door itself is a global resource (location is always "global" per Azure API), but this param is kept for consistency with every other module in this repo and to satisfy linters that expect a location param.')
param location string = 'global'

@description('Prefix for resource naming, matching the rest of this environment.')
param namingPrefix string

@description('Deployment environment (dev, uat, prod).')
param environment string

@description('The real custom domain to bind (e.g. "invoiceeq.app" or "www.invoiceeq.app"). Required -- this module is only ever deployed conditionally when this is non-empty; see 08-apps.bicep.')
param customDomainName string

@description('The origin Front Door forwards traffic to -- invoice-website Container App\'s existing CAE-domain FQDN (NOT the custom domain itself).')
param originHostName string

@description('Front Door SKU. Standard is sufficient for this app today (see module header); switch to Premium_AzureFrontDoor if managed bot protection or private-link origins become a requirement.')
@allowed(['Standard_AzureFrontDoor', 'Premium_AzureFrontDoor'])
param skuName string = 'Standard_AzureFrontDoor'

@description('Requests per minute allowed per client IP before the WAF rate-limits it, scoped to the public support-contact endpoint (BE Gap 249 -- this is the edge-level mitigation for that gap\'s "no rate limiting" finding; the endpoint itself still has no app-level limiter, so this WAF rule is the only protection until/unless one is added in code too).')
param contactEndpointRateLimitThreshold int = 20

@description('Duration (seconds) a client IP stays blocked after exceeding the contact-endpoint rate limit.')
param contactEndpointRateLimitDurationSeconds int = 300

var profileName = 'afd-${namingPrefix}-${environment}'
var endpointName = 'afd-endpoint-${namingPrefix}-${environment}'
var originGroupName = 'og-website'
var originName = 'origin-website'
var routeName = 'route-website'
var wafPolicyName = replace('waf${namingPrefix}${environment}', '-', '') // WAF policy names must be alphanumeric only, no hyphens
var securityPolicyName = 'secpol-${namingPrefix}-${environment}'
var customDomainResourceName = replace(customDomainName, '.', '-')

resource frontDoorProfile 'Microsoft.Cdn/profiles@2024-02-01' = {
  name: profileName
  location: location
  sku: {
    name: skuName
  }
}

resource frontDoorEndpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-02-01' = {
  parent: frontDoorProfile
  name: endpointName
  location: location
  properties: {
    enabledState: 'Enabled'
  }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-02-01' = {
  parent: frontDoorProfile
  name: originGroupName
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
    healthProbeSettings: {
      probePath: '/'
      probeRequestType: 'HEAD'
      probeProtocol: 'Https'
      probeIntervalInSeconds: 60
    }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-02-01' = {
  parent: originGroup
  name: originName
  properties: {
    hostName: originHostName
    httpPort: 80
    httpsPort: 443
    originHostHeader: originHostName
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
  }
}

resource customDomain 'Microsoft.Cdn/profiles/customDomains@2024-02-01' = {
  parent: frontDoorProfile
  name: customDomainResourceName
  properties: {
    hostName: customDomainName
    tlsSettings: {
      // Front Door's own auto-issued/auto-renewed managed certificate --
      // unrelated to Microsoft.App/managedEnvironments/(managed)certificates,
      // which are irrelevant now that the Container App no longer terminates
      // this domain's TLS itself.
      certificateType: 'ManagedCertificate'
      minimumTlsVersion: 'TLS12'
    }
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-02-01' = {
  parent: frontDoorEndpoint
  name: routeName
  dependsOn: [
    origin
  ]
  properties: {
    originGroup: {
      id: originGroup.id
    }
    customDomains: [
      {
        id: customDomain.id
      }
    ]
    supportedProtocols: [
      'Https'
    ]
    patternsToMatch: [
      '/*'
    ]
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled' // keep the *.azurefd.net endpoint reachable too, useful while DNS/cert propagate before cutover
    httpsRedirect: 'Enabled'
  }
}

// `az bicep build` warns BCP081 here (no type schema available for this
// resource type in the Bicep type index as of CLI 0.44.1) -- confirmed
// non-blocking, does not fail the build or block deployment, just means
// property names below aren't statically validated. Re-check if a future
// `az bicep upgrade` picks up types for this provider.
resource wafPolicy 'Microsoft.Network/frontdoorwafpolicies@2022-05-01' = {
  name: wafPolicyName
  location: 'global'
  sku: {
    name: skuName
  }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      mode: 'Prevention'
    }
    managedRules: {
      managedRuleSets: [
        {
          ruleSetType: 'Microsoft_DefaultRuleSet'
          ruleSetVersion: '2.1'
          ruleSetAction: 'Block'
        }
      ]
    }
    customRules: {
      rules: [
        {
          name: 'RateLimitSupportContact'
          priority: 1
          enabledState: 'Enabled'
          ruleType: 'RateLimitRule'
          rateLimitThreshold: contactEndpointRateLimitThreshold
          rateLimitDurationInMinutes: contactEndpointRateLimitDurationSeconds / 60
          matchConditions: [
            {
              matchVariable: 'RequestUri'
              operator: 'Contains'
              matchValue: [
                '/api/contact'
                '/api/v1/support/contact'
              ]
            }
          ]
          action: 'Block'
        }
      ]
    }
  }
}

resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2024-02-01' = {
  parent: frontDoorProfile
  name: securityPolicyName
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: {
        id: wafPolicy.id
      }
      associations: [
        {
          domains: [
            {
              id: customDomain.id
            }
            {
              id: frontDoorEndpoint.id
            }
          ]
          patternsToMatch: [
            '/*'
          ]
        }
      ]
    }
  }
}

@description('The DNS validation token GoDaddy needs as a TXT record on `_dnsauth.<customDomainName>` before Front Door will issue the managed certificate. Read this output after deployment and hand it to the manual DNS step.')
output domainValidationToken string = customDomain.properties.validationProperties.validationToken

@description('Front Door endpoint hostname. GoDaddy CNAME for `customDomainName` must point here, not at the Container App.')
output frontDoorEndpointHostName string = frontDoorEndpoint.properties.hostName

output frontDoorProfileName string = frontDoorProfile.name
output wafPolicyName string = wafPolicy.name
