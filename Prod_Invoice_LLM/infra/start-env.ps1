# Wake up the Database
# Name is psql-invoice-llm-dev-v2, not psql-invoice-llm-dev -- the original
# server was deleted and manually recreated under this "-v2" name at some
# point outside of bicep; this script (and 03-data.bicep/05-secrets.bicep's
# postgresServerName override) were reconciled to match on 2026-08-03.
az postgres flexible-server start --name psql-invoice-llm-dev-v2 --resource-group invoice-llm-dev

Write-Host "Database Online! The containers will automatically wake up when you visit the website."
