# Project Development Workflow

This document defines the process for implementing, tracking, and reviewing features in the Invoice LLM project.

## 1. Feature Progress Tracking
We manage implementation status using the respective tracker files:
* **Backend Features:** `apps/invoice-be/docs/be_features_tracker.md`
* **Frontend Features:** `apps/invoice-fe/docs/fe_features_tracker.md`
* **Website Features:** `apps/invoice-website/website_features/website_features_tracker.md`

### Feature Lifecycle:
1. Mark feature as in-progress `[/]` in the tracker file.
2. Complete checklist items inside the feature's markdown file (e.g., `feature_1_auth.md`).
3. Mark feature as complete `[x]` in the tracker file.

### Gap Analysis Integration
Before implementing features, reference the "Missing Critical Features" section in each tracker, and the "Recommended Enhancements"/"Reconciliation Notes" sections inside individual feature files (added 2026-07-12, code-verified — more precise than the old standalone gap-analysis docs, which have been retired):
* **Backend Gaps:** `apps/invoice-be/docs/be_features_tracker.md` — "Missing Critical Features" + "Recommended Architecture Enhancements" sections
* **Frontend Gaps:** `apps/invoice-fe/docs/fe_features_tracker.md` — "Missing Critical Features" section

**Critical Gaps to Address:**
- Backend: LangGraph nodes (4), Trainer workflow (4), Core modules (2), Chat enhancements (2), API endpoints (1)
- Frontend: Directory watcher, Live terminal feed, Production selector
- Website: Clerk Auth Gateway, Landing Page, Pricing integration

## 2. Iterative Implementation Workflow
To ensure high code quality, we implement changes **one file at a time**:
1. **File Draft:** The AI assistant drafts the file content and explains the changes.
2. **Review & Approval:** The user reviews the code. **No other files are edited, and no terminal commands are executed until this file is approved.**
3. **Execution/Apply:** Once approved, the changes are written to disk, and necessary environment updates (like `uv sync`) are executed.
4. **Repeat:** Move to the next file.

### Gap-Aware Implementation Priority
When selecting features to implement, prioritize based on gap analysis:
1. **Critical Infrastructure:** Clerk Auth Gateway, domain-based tenant provisioning
2. **AI Processing Gaps:** LangGraph nodes (Complexity Classification, Evaluator Router, Critic Node, Dynamic QA)
3. **Core Modules:** Two-layer duplicate detection, complexity classification engine
4. **Frontend Critical Gaps:** Directory watcher, live terminal feed, production selector
5. **Enhanced Features:** Trainer session management, chat learning registry

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
