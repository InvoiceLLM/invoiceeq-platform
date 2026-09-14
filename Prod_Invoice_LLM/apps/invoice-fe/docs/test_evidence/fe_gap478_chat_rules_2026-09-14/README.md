# FE Gap 478 — Settings > Chat Rules — Local Stack + Real Azure AI

## Create a rule (BE preview -> commit, real endpoints)

```
POST /api/v1/chat/rules/preview  {"category":"wrong_status_filter","pattern":"Only count invoices with status VERIFIED or PAID as counted"}
-> 200 {"previewToken":"e633774ab836b1785c825056bf6fa140", "ruleText":"When filtering by status for this kind of question, count: Only count invoices with status VERIFIED or PAID as counted."}

POST /api/v1/chat/rules/commit  (same body + preview_token)
-> 201 {"id":"cfe830a9-f592-4a2f-9acd-9587a1f3e4ff", ...}
```

## FE screenshot before delete

`before_delete.png` — `/settings/chat-rules` (Playwright, chromium, 1280x900,
DISABLE_CLERK_AUTH=true, no stubbing): rule card renders category chip "USED THE
WRONG STATUS FILTER", full `ruleText`, and timestamp "Added 14 Sept 2026, 08:31 by
user_test_default" — category + ruleText + timestamp all present as required.

## Delete via UI

Clicked the trash icon; native `confirm()` dialog fired with text "Delete this chat
rule? Future answers will stop applying it. This cannot be undone." — accepted
programmatically (Playwright `page.on('dialog', ...).accept()`).

`after_delete.png` — empty state "No chat rules yet" rendered immediately after delete.

## Hard-delete confirmation (real Postgres + API)

```
GET /api/v1/chat/rules -> []
SELECT id FROM tenant_chat_rules WHERE id='cfe830a9-...' -> 0 rows
```
Confirms a real hard delete (per this repo's hard-delete-only rule), not a soft
disable.

## Result

- Rule renders with category + ruleText + timestamp: **PASS**
- Delete requires confirm, then removes the row from the list: **PASS**
- `GET /chat/rules` and Postgres both confirm the rule is gone (hard delete): **PASS**

Run against local stack with real Azure AI services (chat-rules logic itself is
deterministic template code per the router's own docstring — no LLM call in this path).
