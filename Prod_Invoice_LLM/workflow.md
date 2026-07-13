# Project Feature Implementation Workflow

For every Backend, Frontend, or Website feature task, the AI agent must strictly follow this sequential workflow:

## 1. Feature Tracks & Tracking Files

Identify the track and locate the corresponding files:
* **Backend (BE)**:
  * Tracker: [be_features_tracker.md](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-be/be_features/be_features_tracker.md)
  * Feature Files: `apps/invoice-be/be_features/feature_*.md`
* **Frontend (FE)**:
  * Tracker: [fe_features_tracker.md](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_LLM/apps/invoice-fe/fe_features/fe_features_tracker.md)
  * Feature Files: `apps/invoice-fe/fe_features/feature_*.md`
* **Website**:
  * Tracker: [website_features_tracker.md](file:///c:/Users/S%20Banerjee/Desktop/Invoice_LLM/Prod_Invoice_website/website_features/website_features_tracker.md)
  * Feature Files: `apps/invoice-website/website_features/feature_*.md`

---

## 2. Sequential Workflow Steps

1. **Read Feature Specification**: Read the target feature specification file (e.g., `feature_1_auth.md`).
2. **Analyze Current Code & Define Changes**: Analyze the existing codebase to determine what additions or modifications are needed.
3. **Verify Against Tracker**: Check the progress tracker file (e.g., `be_features_tracker.md`, `fe_features_tracker.md`, or `website_features_tracker.md`) to verify if any related gaps or missing items exist.
4. **Iterate One File at a Time**:
   - Propose code changes for exactly **one file** at a time.
   - Present the changes to the user (via code diffs or explanation) and **explicitly wait for user approval** on the lines changed.
   - Do **NOT** modify other files or run terminal commands until approval is received.
   - Write the changes to disk once approved.
5. **Update Tracker**: Mark the corresponding gap/task as completed in the progress tracker file before moving to the next task.
