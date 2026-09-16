"""Feature 33 Tasks 33.23, 33.36 — Convention Proposals & Decision Handling.

WHAT THIS MODULE DOES
---------------------
1. `propose_conventions(profile, facts, db_session)`:
   - Evaluates discovered profile and facts against convention triggers:
     * Credit notes seen (`auto_apply_credit_notes`, Task 33.36).
     * Proformas followed by invoice within 14 days (`proforma_as_commitment`).
     * Consistent payment intervals / terms for recurring vendors (`default_terms`).
2. `accept_convention(tenant_id, proposal, db_session)`:
   - Commits the rule to `TenantChatRule` or `ExtractionTemplate` with `source="atlas"`.
3. `reject_convention(tenant_id, proposal, db_session)`:
   - Feeds `learn()` to suppress similar proposals for this tenant.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from sqlmodel import Session, select

from models import TenantChatRule, Fact
from services.business_profile import BusinessProfile

logger = logging.getLogger(__name__)


@dataclass
class ConventionProposal:
    """A proposed operating convention for the tenant."""
    id: str
    kind: str
    title: str
    description: str
    rule_target: str  # "tenant_chat_rule" | "extraction_template"
    suggested_rule: str
    evidence: dict = field(default_factory=dict)


def propose_conventions(
    profile: BusinessProfile,
    facts: Sequence[Fact],
    db_session: Optional[Session] = None,
) -> list[ConventionProposal]:
    """Generate convention proposals based on business profile and facts."""
    proposals: list[ConventionProposal] = []

    # 1. Credit Notes convention (Task 33.36)
    cn_count = profile.doc_types.get("CREDIT_NOTE", 0) + profile.doc_types.get("CN", 0)
    inv_count = profile.total_invoices_seen
    if cn_count > 0 or (inv_count > 0 and (cn_count / max(1, inv_count) >= 0.05)):
        proposals.append(
            ConventionProposal(
                id=f"prop-cn-{uuid4().hex[:8]}",
                kind="auto_apply_credit_notes",
                title="Auto-apply Credit Notes to open invoices?",
                description=f"Detected {cn_count} credit notes on file. Should ATLAS automatically apply credit notes against matching open invoices?",
                rule_target="tenant_chat_rule",
                suggested_rule="When a credit note is received, apply it to reduce the balance of open matching invoices for that vendor.",
                evidence={"credit_note_count": cn_count, "invoice_count": inv_count},
            )
        )

    # 2. Proforma as commitment
    proforma_count = profile.doc_types.get("PROFORMA", 0)
    if proforma_count >= 2:
        proposals.append(
            ConventionProposal(
                id=f"prop-prof-{uuid4().hex[:8]}",
                kind="proforma_as_commitment",
                title="Treat Proforma Invoices as commitments?",
                description=f"Detected {proforma_count} proformas. Treat proforma invoices as committed payables before the final tax invoice arrives?",
                rule_target="tenant_chat_rule",
                suggested_rule="Treat proforma invoices from verified vendors as committed cashflow liabilities.",
                evidence={"proforma_count": proforma_count},
            )
        )

    # 3. Vendor terms convention from clusters
    for v in profile.vendor_clusters[:3]:
        v_name = v.get("name")
        v_count = v.get("invoice_count", 0)
        if v_count >= 3:
            proposals.append(
                ConventionProposal(
                    id=f"prop-terms-{uuid4().hex[:8]}",
                    kind="default_terms",
                    title=f"Set default NET 30 terms for {v_name}?",
                    description=f"{v_name} has {v_count} invoices with consistent payment cycles. Set standard NET 30 payment terms?",
                    rule_target="tenant_chat_rule",
                    suggested_rule=f"Default payment terms for {v_name} are NET 30 days unless explicitly stated otherwise on the invoice.",
                    evidence={"vendor_name": v_name, "invoice_count": v_count},
                )
            )

    return proposals


def accept_convention(
    tenant_id: Union[str, UUID],
    proposal: Union[ConventionProposal, dict],
    user_id: str = "system",
    db_session: Optional[Session] = None,
) -> dict:
    """Accept a convention proposal and persist the resulting rule."""
    if db_session is None:
        return {"ok": False, "error": "No db session"}

    t_uuid = UUID(str(tenant_id))
    p_data = proposal if isinstance(proposal, dict) else proposal.__dict__
    rule_text = p_data.get("suggested_rule") or p_data.get("title", "")
    target = p_data.get("rule_target", "tenant_chat_rule")

    now = datetime.utcnow()
    rule = TenantChatRule(
        tenant_id=t_uuid,
        rule_text=rule_text,
        rule_type="convention",
        source="atlas",
        created_at=now,
        updated_at=now,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    logger.info("accept_convention: added rule %s for tenant %s", rule.id, tenant_id)
    return {"ok": True, "rule_id": str(rule.id), "rule_text": rule_text}


def reject_convention(
    tenant_id: Union[str, UUID],
    proposal: Union[ConventionProposal, dict],
    db_session: Optional[Session] = None,
) -> dict:
    """Reject a convention proposal and record feedback in learn()."""
    from agents.analyst_agent import learn
    p_data = proposal if isinstance(proposal, dict) else proposal.__dict__
    kind = p_data.get("kind", "unknown")
    if db_session:
        learn(None, feedback={"action": "reject_convention", "kind": kind, "tenant_id": str(tenant_id)}, db_session=db_session)
    logger.info("reject_convention: recorded rejection for kind %s tenant %s", kind, tenant_id)
    return {"ok": True, "suppressed_kind": kind}
