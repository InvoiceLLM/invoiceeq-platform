targetScope = 'resourceGroup'

// ================= Stage 10: Cost / Finance Alerting =================
// A monthly Consumption Budget scoped to this resource group, with
// notifications at 50/75/95% actual spend, routed to the same action group
// Stage 9 created (plus a direct email as a backstop).
//
// Gap 295 (2026-08-23): the previous version of this budget (amount: 150,
// notifications at 80% actual / 100% forecasted) was silently non-functional
// -- it assumed USD, but this billing account bills in INR, so real spend
// (~16,600 INR MTD, ~23,880 INR forecasted for the month) was already
// ~10,000% over "budget" and both notifications had permanently fired.
// Founder set the real number 2026-08-23 based on the Cost Management API
// integration's actual live breakdown (Container Apps 51%, Postgres 19%,
// Container Registry 17% -- the latter on an over-provisioned Premium SKU
// worth revisiting separately) against a ~23,880 INR/month forecast.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Prefix for resource naming. NOTE: the real live resource group uses "invoicellm" (no hyphen) despite params.dev.json defaulting namingPrefix to "invoice-llm" -- deploying with the wrong prefix creates an orphaned duplicate budget instead of updating the real one. Pass namingPrefix=invoicellm explicitly for this environment.')
param namingPrefix string = 'invoice-llm'

@description('Monthly budget amount, in the billing account currency (INR for this subscription -- verify per-subscription, not assumed).')
param monthlyBudgetAmount int = 20000

@description('Email address to receive budget threshold notifications')
param alertEmail string

@description('Budget start date - must be the first of a month. Defaults to the first of the current month.')
param budgetStartDate string = '${utcNow('yyyy-MM')}-01T00:00:00Z'

var actionGroupName = 'ag-${namingPrefix}-${environment}'

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' existing = {
  name: actionGroupName
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: 'budget-${namingPrefix}-${environment}'
  properties: {
    category: 'Cost'
    amount: monthlyBudgetAmount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      actual_50_percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroup.id
        ]
      }
      actual_75_percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 75
        thresholdType: 'Actual'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroup.id
        ]
      }
      actual_95_percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 95
        thresholdType: 'Actual'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroup.id
        ]
      }
    }
  }
}

output budgetId string = budget.id
