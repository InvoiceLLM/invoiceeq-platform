"""Outbound (AR) extraction entry point — a thin wrapper, not a second graph.

Gap 283 (2026-08-21): this module used to hold a *separate* 2-node LangGraph
(`extract -> verify`) that reimplemented most of `agents/extraction_agent.py`
and, in doing so, silently skipped everything inbound had gained since Feature
2.1 shipped — `classify_node`, `dynamic_qa_node` (Gap 4), the bounded
`verify -> extract` retry loop with feedback injection (Gap 2/47), the Doc
Intelligence tax-anchor backfill, and the unit-price faithfulness check (Gap 44).

None of those nodes are direction-aware: they read `ocr_text`/`ocr_result`/
`complexity` and the generic numeric fields (`items`, `subtotal`, `tax_amount`,
`grand_total`) that exist identically on both schemas. There was therefore no
reason for a second graph, and keeping one meant every inbound improvement had
to be ported by hand or (as happened) quietly not ported at all.

There is now exactly ONE compiled graph, in `agents/extraction_agent.py`
(`classify -> dynamic_qa -> extract -> verify`, with the conditional retry edge),
parameterised by `flow_direction`. Everything outbound-specific lives in that
file's `_DIRECTION_PROFILES["OUTBOUND"]` entry: the schema, the prompt builders,
the required-field set, and the `VERIFIED`/`NEEDS_REVIEW` status vocabulary.

This module is kept as the outbound entry point so callers, tests and docs that
reference `run_outbound_extraction_agent` / `OutboundInvoiceExtractionSchema`
keep working and so "where does outbound extraction start?" stays answerable by
filename. It defines no nodes, no state and no graph of its own.
"""
import logging
from typing import Any, Dict, Optional

from agents.extraction_agent import (  # noqa: F401 -- re-exported for callers/tests
    GAP_46_VERBATIM_DIRECTIVE,
    OutboundInvoiceExtractionSchema,
    OutboundInvoiceLineItem,
    build_outbound_multimodal_prompt,
    extract_node,
    invoke_with_retry,
    pdf_to_base64_images,
    run_extraction_agent,
    verify_node,
)

logger = logging.getLogger(__name__)

# Fields whose absence is worth flagging -- a tenant's own invoice should
# always have these, unlike an unpredictable vendor document. Kept here as the
# documented outbound contract; the value actually enforced by verify_node is
# `_DIRECTION_PROFILES["OUTBOUND"].required_fields` in extraction_agent.py.
_REQUIRED_FIELDS = ("customer_name", "invoice_number", "grand_total")


def run_outbound_extraction_agent(
    file_path: str,
    ocr_text: str,
    tenant_id: str,
    rules: Optional[Dict[str, Any]] = None,
    ocr_result: Optional[Any] = None,
    on_log: Optional[Any] = None,
) -> dict:
    """Runs the shared extraction graph in OUTBOUND mode.

    Returns the same `{status, alerts, extracted_data}` shape as before, with
    the same `VERIFIED`/`NEEDS_REVIEW` status vocabulary — the graph resolves
    those from the OUTBOUND direction profile, so nothing downstream
    (`queue_worker/outbound_handlers.py`, `routers/outbound_audit.py`) changes.
    """
    return run_extraction_agent(
        file_path=file_path,
        ocr_text=ocr_text,
        tenant_id=tenant_id,
        rules=rules,
        ocr_result=ocr_result,
        on_log=on_log,
        flow_direction="OUTBOUND",
    )
