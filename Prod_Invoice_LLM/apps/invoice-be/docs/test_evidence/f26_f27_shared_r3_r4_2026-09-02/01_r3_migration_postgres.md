# R3 — Alembic chain applied and proven reversible on the dev Postgres

Date 2026-09-02. Persona: functional-tester. Hard rule 2 evidence for
Feature 27 R-27-26 and Feature 26's migration claim.

Target: `postgresql://<redacted>@localhost:5433/invoice_db` (container
`invoice-postgres-local`, healthy). Script head: `e4f5a6b7c8d9` (single head,
resolved via `ScriptDirectory.get_heads()` because `alembic.exe` is blocked by
this machine's Application Control policy — the Python API is the substitute).

## Starting state — already at head, contrary to both specs

Both Build status blocks said the migration "has never been applied to any
Postgres instance". **That was wrong.** `alembic_version` already read
`e4f5a6b7c8d9`, and every one of the 25 SQLModel tables was present. Corrected
in both specs by this pass.

One false alarm, recorded so it is not repeated: an initial check for a table
named `chatattachment` returned zero columns and briefly looked like a missing
shipped table. The real name is **`chat_attachments`** (the model sets
`__tablename__`), and it is present with all 20 columns. No defect; a wrong
query. **No gap filed.**

## Column verification, read back from `information_schema`

`invoice`:            doc_type varchar NULL, doc_type_evidence varchar NULL, no default
`documents`:          35 columns; tenant_id uuid NOT NULL; status varchar NOT NULL;
                      doc_type varchar NULL; doc_type_evidence varchar NULL;
                      doc_type_confidence double precision NULL; file_hash varchar NULL
`chat_attachments`:   chunk_count integer NOT NULL default 0;
                      indexed_at timestamp NULL; expires_at timestamp NULL

All money and classification columns nullable with no server default — E8's
"None means the document did not state it, never zero" holds at the DDL level.

`documents` indexes (7): documents_pkey, ix_documents_batch_id,
ix_documents_deleted_at, ix_documents_doc_type, ix_documents_file_hash,
ix_documents_tenant_created_at, ix_documents_tenant_doc_type, ix_documents_tenant_id.
Both composite indexes are tenant-led, per FE Gap 29's pattern.

## Reversibility — run, not assumed

    downgrade -1   e4f5a6b7c8d9 -> d3e4f5a6b7c8
      documents present: False
      invoice.doc_type present: False
      chat_attachments.chunk_count present: True   <- F26's migration correctly untouched
    upgrade head   d3e4f5a6b7c8 -> e4f5a6b7c8d9
      version: e4f5a6b7c8d9
      documents present: True, 35 columns, 7 indexes
      invoice.doc_type present: True

Safe to run because `documents` held 0 rows (`chat_attachments` 2, `invoice` 8,
both untouched by this revision and both still intact afterwards).

**Verdict: R-27-26 SATISFIED.** The chain applies, downgrades cleanly without
touching Feature 26's revision beneath it, and re-applies to an identical shape.
