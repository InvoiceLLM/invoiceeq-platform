# Project Development Workflow

This document defines the process for implementing, tracking, and reviewing features in the Invoice LLM project.

## 1. Feature Progress Tracking
We manage implementation status using the respective tracker files:
* **Backend Features:** `Document/be_features/be_features_tracker.md`
* **Frontend Features:** `Document/fe_features/fe_features_tracker.md`
* **Website Features:** `Document/website_features/website_features_tracker.md`

### Feature Lifecycle:
1. Mark feature as in-progress `[/]` in the tracker file.
2. Complete checklist items inside the feature's markdown file (e.g., `feature_1_auth.md`).
3. Mark feature as complete `[x]` in the tracker file.

## 2. Iterative Implementation Workflow
To ensure high code quality, we implement changes **one file at a time**:
1. **File Draft:** The AI assistant drafts the file content and explains the changes.
2. **Review & Approval:** The user reviews the code. **No other files are edited, and no terminal commands are executed until this file is approved.**
3. **Execution/Apply:** Once approved, the changes are written to disk, and necessary environment updates (like `uv sync`) are executed.
4. **Repeat:** Move to the next file.

## 3. Local Verification & Review Gate
Before code is pushed:
* Run automated tests locally using `uv run pytest`.
* Run code style check using `ruff check`.
* **Local Code Review:** The AI assistant will perform a CodeRabbit-style review in the chat, highlighting potential performance issues, edge cases, or security bugs before marking the task complete.

## 4. Git & CodeRabbit Integration
1. Push the completed feature branch to the remote repository.
2. Create a Pull Request (PR) on GitHub.
3. CodeRabbit (GitHub App integration) will automatically perform a cloud-based review on the PR.
4. Merge only after resolving CodeRabbit comments and obtaining user approval.
