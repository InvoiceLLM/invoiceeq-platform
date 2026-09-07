# Documentation Reading Guide

What every top-level doc in this repo is for and the order to read them in. Renamed from `application_doc_summary.txt` on 2026-09-07.

Here's the reading order, grouped by what each phase builds toward:

Last reconciled 2026-09-07: every path below was checked to exist, and README.md + System_Journey_User_Admin_Guide.md were brought in line with the application as of that date. For build status, the three *_features_tracker.md files (steps 7, 9, 11) are the single source of truth — everything else describes design or a dated snapshot.

1. Big picture (10 min)

	README.md — repo structure, tech stack, headline feature list per app with links to the trackers, roles, what was removed, quick start
	docs/architecture/Technical_Architecture_Document.md — the core architecture doc, describing the target system end-to-end
	docs/architecture/Cloud_Architecture_Document.md — Azure infra picture
	docs/architecture/System_Journey_Developer_Guide.md — one narrative walkthrough of how an invoice actually moves through this codebase, module by module ([LIVE] vs [PLANNED] marked throughout)
	docs/guides/System_Journey_User_Admin_Guide.md — the same journey in plain language from the Admin/Auditor/Trainer side, no code or file names (Today vs Planned marked throughout; Viewer role retired 2026-08-28)

2. Data & API contracts (source of truth for anything code-level)

	3. docs/architecture/Database_Schema_Document.md — full relational + vector schema
	4. apps/invoice-be/Backend_Code_Layout_Document.md — endpoint → file → function call flow for every API

3. Process (read once, not per-feature)

	5. docs/guides/workflow.md (short form) / docs/guides/detailed_workflow.md (full process) — how feature tracking/review works in this repo
	6. ../.claude/CONVENTIONS.md — lives one level ABOVE this repo folder, in the Invoice_LLM workspace root (moved there; there is no .claude/ inside Prod_Invoice_LLM). How the AI agent system works: architect (scopes work, never executes) + 6 specialists (senior-dev, functional-tester, load-tester, security-tester, infra-devops, business-analyst). Every specialist follows the same pattern — state scope before running, file real evidence after, at a fixed location per agent (`../.claude/agents/*.md` has each persona's exact job; `../.claude/skills/*` holds the build-feature / gap-open / gap-work / done / hand-back / verify-postgres workflows). Read this before asking an agent to do anything. The workspace-root CLAUDE.md also documents the doc- and code-dependency-graph scripts (dependency_parser.py, code_dependency_graph.py).

4. Feature-by-feature detail — backend first

	7. apps/invoice-be/docs/be_features_tracker.md — status index and the single source of truth for open implementation items
	8. Individual apps/invoice-be/docs/feature_*.md files, in numeric order — target design for each feature. The sequence is not clean: it runs 1..29 but there is no feature_5 (merged into 2), no feature_21, no feature_22 (never existed), and no standalone 23 or 24; six decimal sub-feature docs sit alongside their parents (feature_1.1_rbac, 2.1_vendor_flow_ingestion, 3.1_fix_ftr2_3, 6.1_vendor_flow_chat, 7.1_vendor_flow_auditor, 8.1_vendor_flow_dashboard); feature_18 (alert-anchored trainer) is marked CANCELLED in the tracker but its doc stays because the code is live and FE Feature 14 depends on it; feature_21 has NO doc of its own — its code (the SAGE tool-calling orchestrator) was deleted on 2026-08-25 after a live head-to-head, so feature_21_sage.md was deleted with it; Feature 21's whole closing record (the revert, the rewrite, the live head-to-head, the deletion decision) was moved into feature_6_rag.md's "Feature 21 — the SAGE alternative, tried and closed" section that same day, since the two surviving functions are Feature 6 dependencies — be_features_tracker.md's "Feature 21" section is now a short pointer to that, plus Gap 316 for the deletion itself (feature_21_sage.md had itself replaced feature_21_architecture.md and feature_21_rag_faithfulness.md earlier the same day; none of the three exists, do not recreate them); features 20, 23 and 24 share one consolidated doc, feature_20_23_24_ops_workbook.md (the ops workbooks + the per-field recommendation pass — it replaced feature_20_observability_monitoring_alerts.md, feature_23_ai_control_tower.md, feature_24_ops_digest_agent.md and feature_20_23_24_implementation_status.md on 2026-08-25); and five docs were added after 2026-08-25 — feature_25_plug_and_play_workflows, 26_chat_attached_documents, 27_generic_extraction, 28_image_upload_pdf_boundary, 29_llm_optimisation — 30 files in total as of 2026-09-07. Also in the same folder, not feature specs: chat_and_extraction_improvements_roadmap.md, f26_attachment_benchmark_scenarios.md, financial-document-taxonomy-research-2026-09-02.md, test_coverage_map.md, test_evidence/, extraction_benchmark/.

5. Frontend
	9. apps/invoice-fe/docs/fe_features_tracker.md
	10. Individual apps/invoice-fe/docs/feature_*.md files, in order — a contiguous 1..20 (12 is a spec-only test-suite doc; 18 desktop app is planned, not started; 14 is the FE half of BE feature_18; 20 is the FE half of BE feature_17 Invoice Builder), plus three decimal sub-feature docs (feature_2.1_vendor_flow_dashboard, 3.1_vendor_flow_ingestion, 4.1_vendor_flow_auditor) — 23 files in total as of 2026-09-07.

6. Website
	11. apps/invoice-website/website_features/website_features_tracker.md
	12. apps/invoice-website/website_features/feature_*.md, in order — a contiguous 1..7, plus one decimal sub-feature doc (feature_3.1_vendor_flow_pricing) — 8 files in total as of 2026-09-07.

7. App-level implementation READMEs (once you're about to touch code)
	13. apps/invoice-be/README.md, apps/invoice-be/Backend_Code_Layout_Document.md. (apps/invoice-be/agents/README.md still exists but is a generic ReAct blueprint that no longer describes the actual agent modules — treat it as stale.)
	14. apps/invoice-fe/README.md
	15. apps/invoice-website/README.md
	16. infra/README.md (10-stage bicep deployment strategy, file-by-file), infra/NEW_ENVIRONMENT.md (standing up a fresh environment), infra/THIRD_PARTY_INTEGRATIONS_SETUP.md (Clerk, PayU, Google Drive OAuth, SendGrid inbound/outbound mail, Front Door custom domain, Key Vault seeding — the Salesforce section is struck through, do not perform it), infra/deployment_tracker.md (what is actually deployed on dev), docs/guides/SECRETS_SYNC_GUIDE.md

	16b. infra/FLAGS_AND_INFRA_CHECKLIST.md — every switch with its config default vs dev vs prod value and the container app that carries it, model deployment params, jobs declared vs actually deployed, known gotchas, and the pre-deploy / post-deploy checklists. Read before any deploy or flag change.

8. Roadmap/QA (optional, situational)
	17. docs/guides/implementation_plan_updated.md — week-by-week sequencing (Month 1/2/3 sub-plans were retired 2026-07-27; current status lives in the *_features_tracker.md files instead)
	17b. docs/guides/gap_resolution_autopilot_audit_trainer_chat_plan.md — phased execution order for the (now closed) Autopilot, Audit Review, Trainer & Chat gaps 217–221; historical
	17c. docs/phase_2_enhancements.md — the forward-looking idea index: capture only, nothing in it is scoped or started; items graduate out of it into a feature_N doc when scoped (chat attachments and image upload already did, as Features 26 and 28)
	18. docs/test_cases/*.md — static QA reference; apps/*/docs/test_coverage_map.md (one per app, all three exist) is the live record of what's actually automated vs. manually verified, with raw evidence under apps/*/docs/test_evidence/
	18b. reports/ — filed evidence from audits, chat-latency runs, and the load/ and security/ test folders
	19. docs/guides/local_uv_setup.md — only when you're actually about to run it locally (README.md's quick start is the condensed version of this)

Steps 1-7 are the ones that actually matter for "understanding the application." 8 is there when you get to frontend/website/ops work specifically. For current build status and open work, the *_features_tracker.md files in steps 4-6 are the single source of truth — the architecture docs and individual feature files describe the target design only, and README.md / the two System Journey guides are dated snapshots (see their "Last reconciled" lines).
