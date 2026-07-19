# Automated Cleanup of Stuck Processing Records

## Overview
This automated cleanup system removes invoice records that have been stuck in `PROCESSING` status for more than 30 minutes, along with their corresponding PDF files from Azure Blob Storage.

## Components

### 1. Python Script: `cleanup_stuck_records.py`
- Finds records in `PROCESSING` status older than specified threshold (default: 30 minutes)
- Deletes database records and corresponding PDF files from storage
- Supports dry-run mode for testing
- Provides detailed logging

### 2. GitHub Actions Workflow: `.github/workflows/cleanup_stuck_records.yml`
- Runs automatically every hour via cron schedule
- Can be manually triggered via `workflow_dispatch`
- Runs cleanup script with proper environment variables

## Setup Instructions

### 1. GitHub Secrets Configuration
Add the following secrets to your GitHub repository (Settings → Secrets and variables → Actions):

- `AZURE_DATABASE_URL`: Your PostgreSQL connection string
  - Format: `postgresql://postgres:password@server.postgres.database.azure.com:5432/invoice_db`
- `AZURE_STORAGE_CONNECTION_STRING`: Your Azure Storage connection string

### 2. Local Testing
Test the cleanup script locally before enabling the automated workflow:

```bash
cd apps/invoice-be

# Dry run (no actual deletions)
python cleanup_stuck_records.py --minutes 30 --dry-run

# Actual cleanup
python cleanup_stuck_records.py --minutes 30
```

### 3. Manual Workflow Trigger
To manually trigger the cleanup workflow:
1. Go to GitHub Actions tab in your repository
2. Select "Cleanup Stuck Records" workflow
3. Click "Run workflow" button
4. Select branch and click "Run workflow"

### 4. Customize Threshold
To change the time threshold from 30 minutes to another value:

**In the script:**
```bash
python cleanup_stuck_records.py --minutes 60  # 1 hour threshold
```

**In the workflow file:**
Edit the `--minutes` parameter in `.github/workflows/cleanup_stuck_records.yml`

**In the schedule:**
Edit the cron expression in the workflow file to change frequency

## Usage Examples

### Local Usage
```bash
# Check what would be deleted (dry run)
python cleanup_stuck_records.py --dry-run

# Delete records stuck for more than 1 hour
python cleanup_stuck_records.py --minutes 60

# Delete records stuck for more than 15 minutes
python cleanup_stuck_records.py --minutes 15
```

### CI/CD Integration
The workflow automatically:
1. Checks out the code
2. Sets up Python environment
3. Installs dependencies
4. Runs the cleanup script with environment variables
5. Logs all actions and errors

## Safety Features

- **Dry-run mode**: Test before actual deletion
- **Logging**: Detailed logs of all actions
- **Error handling**: Continues on individual record failures
- **Transaction safety**: Database rollback on errors
- **Storage cleanup**: Attempts to delete PDF files even if database deletion fails

## Monitoring

Check the GitHub Actions logs to monitor:
- Number of records found and deleted
- Any storage deletion errors
- Execution time and success/failure status

## Notes

- The script only affects records with `status = 'PROCESSING'`
- Records are considered stuck if `created_at` is older than the threshold
- Both database records and storage files are deleted
- The workflow runs in the GitHub Actions environment with access to Azure resources
