targetScope = 'resourceGroup'

// ================= Stage 10: Cost / Finance Alerting =================
// A monthly Consumption Budget scoped to this resource group, with
// notifications at 80% actual and 100% forecasted spend, routed to the
// same action group Stage 9 created (plus a direct email as a backstop).

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Monthly budget amount in the billing account currency (USD)')
param monthlyBudgetAmount int = 150

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
      actual_80_percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [
          alertEmail
        ]
        contactGroups: [
          actionGroup.id
        ]
      }
      forecasted_100_percent: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
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
