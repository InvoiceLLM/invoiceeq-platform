// =============================================================================
// FILE: tests/unit/atlas-fixtures.ts
// FEATURE: FE Feature 23 — the shapes the unit tests render.
//
// **Every FIELD here is one the backend really emits; the VALUES are chosen to
// exercise the render.** The field list was checked against a live
// `GET /api/v1/atlas/lines` captured on 2026-09-18 (mock-auth uvicorn on the dev
// Postgres) — including the ones easy to get wrong: `batchable` is present and
// computed, `why.doubt` is `null` on a certain line, `Figure.value` arrives as a
// STRING ("241300.0"), and `correction` is `null` unless the line is a Trainer
// correction. The wording differs from the live lines (the real headline reads
// "Kumar Supplies #1041", the real action label "Approve"), which is why the
// wording is never asserted anywhere.
//
// A fixture nobody compared against a real response is how the F33/F22 seam was
// built, so the real payload is rendered too, by
// `atlas-live-backend.test.tsx` — that test, not this file, is the end-to-end
// evidence.
// =============================================================================

import type { AtlasLinesResponse, AtlasRecommendation } from "@/lib/atlas";

export const auditLine: AtlasRecommendation = {
  id: "approve-8f2c3e91-0001",
  capability: "audit",
  skill: "invoice_awaiting_decision",
  what: {
    headline: "Kumar Supplies #1041 is waiting on you",
    entity_kind: "invoice",
    entity_id: "8f2c3e91-0000-0000-0000-000000000001",
  },
  why: {
    text: "2,41,300.00 is due in 3 days and nobody has decided on it.",
    figures: [
      {
        rendered: "2,41,300.00",
        value: "241300.00",
        currency: "INR",
        source: "computed",
        computation: "the grand total on this invoice, as extracted",
      },
    ],
    references: ["#1041"],
  },
  action: {
    kind: "resolve_invoice",
    label: "Open the decision",
    target_id: "8f2c3e91-0000-0000-0000-000000000001",
    params: {},
  },
  verify: {
    question: "What is on invoice #1041 and when is it due?",
    document_id: "8f2c3e91-0000-0000-0000-000000000001",
  },
  certainty: "certain",
  reversibility: "reversible",
  currency: "INR",
  batchable: true,
};

export const uncertainDoubtLine: AtlasRecommendation = {
  id: "doubt-rate-8f2c3e91-0002",
  capability: "audit",
  skill: "claim_in_doubt_rate",
  what: {
    headline: "Kumar Supplies #1042: their quotation would settle this",
    entity_kind: "invoice",
    entity_id: "8f2c3e91-0000-0000-0000-000000000002",
  },
  why: {
    text:
      "2,40,000.00 is over 4x their usual 40,000.00–60,000.00 across 4 invoices. " +
      "Attaching their quotation settles it in one step.",
    figures: [
      {
        rendered: "2,40,000.00",
        value: "240000.00",
        currency: "INR",
        source: "computed",
        computation: "the total on this invoice, as extracted",
      },
      {
        rendered: "40,000.00",
        value: "40000.00",
        currency: "INR",
        source: "computed",
        computation: "the lowest of Kumar Supplies's 4 previous invoices in this currency",
      },
      {
        rendered: "60,000.00",
        value: "60000.00",
        currency: "INR",
        source: "computed",
        computation: "the highest of Kumar Supplies's 4 previous invoices in this currency",
      },
    ],
    references: ["#1042", "4"],
    doubt: "I cannot tell whether this is agreed or an error without their quotation.",
  },
  action: {
    kind: "attach_witness_document",
    label: "Attach their quotation",
    target_id: "8f2c3e91-0000-0000-0000-000000000002",
    params: { witness: "QUOTATION", claim: "rate" },
  },
  verify: {
    question: "What did you compare #1042 against, and which invoices are in that range?",
    document_id: "8f2c3e91-0000-0000-0000-000000000002",
  },
  certainty: "uncertain",
  reversibility: "reversible",
  currency: "INR",
  batchable: false,
};

export const trainerCorrectionLine: AtlasRecommendation = {
  id: "correct-total-8f2c3e91-0003",
  capability: "train",
  skill: "invoice_arithmetic_correction",
  what: {
    headline: "Shree Packaging #7001's total disagrees with its own line items",
    entity_kind: "invoice",
    entity_id: "8f2c3e91-0000-0000-0000-000000000003",
  },
  why: {
    text: "The line items, plus tax, less discount, come to 52,000.00, not 50,000.00.",
    figures: [
      {
        rendered: "52,000.00",
        value: "52000.00",
        currency: "INR",
        source: "computed",
        computation: "the line items, plus tax, less discount",
      },
      {
        rendered: "50,000.00",
        value: "50000.00",
        currency: "INR",
        source: "computed",
        computation: "the grand total as extracted",
      },
    ],
    references: ["#7001"],
  },
  action: {
    kind: "apply_field_correction",
    label: "Apply the correction",
    target_id: "8f2c3e91-0000-0000-0000-000000000003",
    params: { field: "grand_total" },
  },
  verify: {
    question: "Which line items did you add up for #7001?",
    document_id: "8f2c3e91-0000-0000-0000-000000000003",
  },
  correction: {
    field_label: "Invoice total",
    field_name: "grand_total",
    before_rendered: "50,000.00",
    after_rendered: "52,000.00",
  },
  certainty: "certain",
  reversibility: "reversible",
  currency: "INR",
  batchable: true,
};

export const loaderLine: AtlasRecommendation = {
  id: "ingestion-failed-0004",
  capability: "load",
  skill: "ingestion_failure",
  what: {
    headline: "2 files from the Drive folder did not load",
    entity_kind: "ingestion_source",
    entity_id: "8f2c3e91-0000-0000-0000-000000000004",
  },
  why: {
    text: "The folder was shared read-only, so re-sharing it with edit access fixes this.",
    figures: [],
    references: [],
  },
  action: {
    kind: "retry_ingestion_source",
    label: "Try the folder again",
    target_id: "8f2c3e91-0000-0000-0000-000000000004",
    params: {},
  },
  verify: { question: "Which files failed, and what did the connector say?" },
  certainty: "certain",
  reversibility: "reversible",
  currency: "INR",
  batchable: true,
};

export function linesResponse(
  lines: AtlasRecommendation[],
  overrides: Partial<AtlasLinesResponse> = {}
): AtlasLinesResponse {
  return {
    ungranted: false,
    capabilities: ["audit"],
    lines,
    doubt_checks_run: lines.length,
    doubt_checks_skipped: 0,
    ...overrides,
  };
}
