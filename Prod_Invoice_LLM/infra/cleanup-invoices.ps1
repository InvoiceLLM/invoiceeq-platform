# Deletes all rows from the `invoice` and `audit_logs` tables in the dev Postgres DB
# (psql-invoice-llm-dev). Postgres is private-endpoint-only, so this runs the delete
# from inside the invoice-be container itself (via `az containerapp exec`), using its
# own SQLAlchemy engine rather than a direct psql connection from this machine.

$resourceGroup = "invoice-llm-dev"
$appName = "ca-invoice-be-dev"

# invoice-be scales to zero when idle; `exec` needs an active replica to attach to.
$replicaCount = (az containerapp replica list --name $appName --resource-group $resourceGroup --query "[].name" -o tsv | Measure-Object -Line).Lines
if ($replicaCount -eq 0) {
    Write-Host "No active replica — temporarily setting min-replicas=1 to start one..."
    az containerapp update --name $appName --resource-group $resourceGroup --min-replicas 1 | Out-Null

    $attempts = 0
    do {
        Start-Sleep -Seconds 10
        $replicaCount = (az containerapp replica list --name $appName --resource-group $resourceGroup --query "[].name" -o tsv | Measure-Object -Line).Lines
        $attempts++
    } while ($replicaCount -eq 0 -and $attempts -lt 6)

    if ($replicaCount -eq 0) {
        Write-Error "Timed out waiting for a replica to start. Aborting."
        exit 1
    }
    Write-Host "Replica is up. Remember to set min-replicas back to 0 afterward to restore scale-to-zero (az containerapp update --name $appName --resource-group $resourceGroup --min-replicas 0)."
}

$pythonCmd = 'from database import engine; from sqlalchemy import text; c=engine.connect(); c.execute(text(''DELETE FROM audit_logs'')); result=c.execute(text(''DELETE FROM invoice'')); c.commit(); print(result.rowcount, ''invoice rows deleted''); c.close()'
$fullCmd = "python3 -c `"$pythonCmd`""

az containerapp exec --name $appName --resource-group $resourceGroup --command $fullCmd
