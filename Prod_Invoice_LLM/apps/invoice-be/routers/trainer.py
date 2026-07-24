import os
import json
import logging
from uuid import UUID, uuid4
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from config import get_settings
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import ExtractionTemplate, ExtractionTemplateVersion, Invoice, User
from queue_worker.handlers import _run_ocr
from agents.extraction_agent import run_extraction_agent
from agents.trainer_agent import run_trainer_agent
from services.storage import LOCAL_STORAGE_DIR
from services import trainer_sessions
from azure.storage.queue import QueueClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trainer", tags=["trainer"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class ChatPayload(BaseModel):
    content: str


# ─────────────────────────────────────────────────────────────────────────────
# Serialization helpers — the FE (lib/trainer-service.ts) consumes a specific
# `TrainerSession` shape (camelCase). We build it here so the FE mapping is thin.
# ─────────────────────────────────────────────────────────────────────────────

# Scalar fields shown in the "Variables & Rules" inspector, in display order.
_FIELD_LABELS = [
    ("invoice_number", "Invoice Number"),
    ("invoice_date", "Invoice Date"),
    ("due_date", "Due Date"),
    ("vendor_name", "Vendor Name"),
    ("po_number", "PO Number"),
    ("currency", "Currency"),
    ("subtotal", "Subtotal"),
    ("tax_amount", "Tax Amount"),
    ("discount_amount", "Discount Amount"),
    ("grand_total", "Grand Total"),
]

# Best-effort map from our schema keys to Azure prebuilt-invoice confidence keys.
# Confidence is display-only (the FE flags < 0.8); default to 1.0 when unknown.
_CONFIDENCE_ALIASES = {
    "invoice_number": ["InvoiceId"],
    "invoice_date": ["InvoiceDate"],
    "due_date": ["DueDate"],
    "vendor_name": ["VendorName"],
    "po_number": ["PurchaseOrder"],
    "subtotal": ["SubTotal"],
    "tax_amount": ["TotalTax"],
    "grand_total": ["InvoiceTotal"],
    "discount_amount": ["TotalDiscount"],
}


def _build_variables(extracted_data: dict | None, field_confidence: dict | None, corrected_keys) -> list[dict]:
    """Project the extraction result into the FE's ExtractedVariable[] shape."""
    if not extracted_data:
        return []
    field_confidence = field_confidence or {}
    corrected = set(corrected_keys or [])
    variables: list[dict] = []
    for key, label in _FIELD_LABELS:
        value = extracted_data.get(key)
        if value in (None, "", []):
            continue
        confidence = 1.0
        for alias in _CONFIDENCE_ALIASES.get(key, []):
            score = field_confidence.get(alias)
            if score is not None:
                confidence = float(score)
                break
        variables.append({
            "id": key,
            "key": key,
            "label": label,
            "value": str(value),
            "confidence": confidence,
            "isCorrected": key in corrected,
        })
    return variables


def _serialize_session(s: dict) -> dict:
    """Convert the stored session dict into the FE `TrainerSession` shape."""
    pdf_url = None
    # Existing-vendor sessions are grounded on a real production invoice, served
    # through the same same-origin proxy the auditor uses. New-vendor / Global
    # uploads keep their client-side object URL (the FE has the File locally).
    if s.get("scope") == "existing_vendor" and s.get("sample_invoice_id"):
        pdf_url = f"/api/invoices/{s['sample_invoice_id']}/pdf"
    return {
        "sessionId": s["session_id"],
        "scope": s.get("scope"),
        "vendorName": s.get("vendor_name"),
        "fileName": s.get("file_name"),
        "pdfUrl": pdf_url,
        "createdAt": s.get("created_at"),
        "variables": _build_variables(s.get("extracted_data"), s.get("field_confidence"), s.get("corrected_keys")),
        "activeRules": s.get("constraints") or [],
        "chatHistory": s.get("chat_history") or [],
    }


def _now_hm() -> str:
    return datetime.utcnow().strftime("%H:%M")


def _msg(sender: str, text: str, suggested_rule: str | None = None) -> dict:
    m = {"id": f"msg-{uuid4().hex[:8]}", "sender": sender, "text": text, "timestamp": _now_hm()}
    if suggested_rule:
        m["suggestedRule"] = suggested_rule
    return m


def _welcome_message(scope: str, vendor_name: str | None, file_name: str | None) -> dict:
    if scope == "global":
        text = ("Welcome to the Global Rule Sandbox. Rules trained here apply tenant-wide to every "
                "vendor. Describe a rule to add or refine — a sample PDF is optional.")
    elif scope == "existing_vendor":
        text = (f"Loaded a production sample invoice for {vendor_name}. What extraction rules should "
                "we refine for this vendor?")
    else:
        text = (f"Uploaded sample invoice {file_name or ''}. Let's set up cold-start extraction rules "
                "for this new vendor.")
    return _msg("assistant", text)


def _run_ocr_split(file_path: str) -> tuple[str, dict, Any]:
    """Run OCR and normalise the (text, field_confidence, raw_result) triple.

    `_run_ocr` returns a dict on Azure (content + coordinates + field_confidence)
    and a plain string in local/Ollama mode.
    """
    settings = get_settings()
    ocr_result = _run_ocr(file_path, settings)
    if isinstance(ocr_result, dict):
        return ocr_result.get("content", ""), ocr_result.get("field_confidence", {}), ocr_result
    return ocr_result, {}, ocr_result


# ─────────────────────────────────────────────────────────────────────────────
# Template / re-audit helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_template(db_session: Session, tenant_id: UUID, vendor_name: str | None) -> ExtractionTemplate | None:
    """Fetch a template row. vendor_name=None resolves the tenant's Global template."""
    stmt = select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == tenant_id)
    if vendor_name is None:
        stmt = stmt.where(ExtractionTemplate.vendor_name.is_(None))
    else:
        stmt = stmt.where(ExtractionTemplate.vendor_name == vendor_name)
    return db_session.exec(stmt).first()


def _global_constraints(db_session: Session, tenant_id: UUID) -> list[str]:
    """Return the tenant's current Global-template constraints (read-only context)."""
    tpl = _get_template(db_session, tenant_id, None)
    if tpl and isinstance(tpl.rules, dict):
        return tpl.rules.get("constraints", []) or []
    return []


def _resolve_changed_by(db_session: Session, context: TenantContext) -> str:
    """Human-readable actor for version history — email if we have it, else user id."""
    if context.db_user_id:
        user = db_session.get(User, context.db_user_id)
        if user and user.email:
            return user.email
    return context.user_id


def _enqueue_reaudit(tenant_id: str, vendor_name: str | None) -> bool:
    """Queue a background re-audit (Task 10.7). vendor_name=None => all vendors (Global)."""
    settings = get_settings()
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        logger.warning("AZURE_STORAGE_CONNECTION_STRING missing; skipped re-audit enqueue.")
        return False
    try:
        queue_client = QueueClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING, "extraction-tasks-queue"
        )
        queue_client.send_message(json.dumps({
            "task": "reaudit_templates",
            "kwargs": {"tenant_id": tenant_id, "vendor_name": vendor_name},
        }))
        return True
    except Exception as e:
        logger.warning("Failed to enqueue re-audit task: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Session entry points (one per scope) — Tasks 10.2, 10.3, 10.4
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_transient_file(
    file: UploadFile = File(...),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Scope #3 (New Vendor): cold-start from a freshly uploaded sample PDF (Task 10.4)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported for training.")

    session_id = str(uuid4())
    session_dir = os.path.join(LOCAL_STORAGE_DIR, "trainer")
    os.makedirs(session_dir, exist_ok=True)
    file_path = os.path.join(session_dir, f"{session_id}.pdf")

    try:
        content_bytes = await file.read()
        with open(file_path, "wb") as f:
            f.write(content_bytes)
    except Exception as e:
        logger.error("Failed to save transient training file: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save uploaded file.")

    try:
        ocr_text, field_confidence, ocr_result = _run_ocr_split(file_path)
        extraction_res = run_extraction_agent(file_path, ocr_text, str(tenant_context.tenant_id), ocr_result=ocr_result)
    except Exception as e:
        logger.error("OCR/Extraction failed for transient training upload: %s", e)
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Transient parsing failed: {str(e)}")

    session = {
        "session_id": session_id,
        "tenant_id": str(tenant_context.tenant_id),
        "scope": "new_vendor",
        "vendor_name": (extraction_res.get("extracted_data") or {}).get("vendor_name"),
        "file_path": file_path,
        "file_name": file.filename,
        "sample_invoice_id": None,
        "ocr_text": ocr_text,
        "field_confidence": field_confidence,
        "constraints": [],
        "corrected_keys": [],
        "extracted_data": extraction_res.get("extracted_data") or {},
        "chat_history": [_welcome_message("new_vendor", None, file.filename)],
        "created_at": datetime.utcnow().isoformat(),
    }
    trainer_sessions.save_session(session_id, session)
    return _serialize_session(session)


@router.post("/sessions/global", status_code=status.HTTP_201_CREATED)
async def start_global_session(
    file: UploadFile | None = File(default=None),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Scope #1 (Global): tenant-wide, vendor-agnostic. Chat-only or optionally PDF-grounded (Task 10.2)."""
    session_id = str(uuid4())
    file_path = None
    file_name = None
    ocr_text = ""
    field_confidence: dict = {}
    extracted_data: dict = {}

    if file is not None and file.filename:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported for grounding.")
        session_dir = os.path.join(LOCAL_STORAGE_DIR, "trainer")
        os.makedirs(session_dir, exist_ok=True)
        file_path = os.path.join(session_dir, f"{session_id}.pdf")
        try:
            content_bytes = await file.read()
            with open(file_path, "wb") as f:
                f.write(content_bytes)
            file_name = file.filename
            ocr_text, field_confidence, ocr_result = _run_ocr_split(file_path)
            extraction_res = run_extraction_agent(file_path, ocr_text, str(tenant_context.tenant_id), ocr_result=ocr_result)
            extracted_data = extraction_res.get("extracted_data") or {}
        except Exception as e:
            logger.error("OCR/Extraction failed for global grounding upload: %s", e)
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Grounding parse failed: {str(e)}")

    session = {
        "session_id": session_id,
        "tenant_id": str(tenant_context.tenant_id),
        "scope": "global",
        "vendor_name": None,
        "file_path": file_path,
        "file_name": file_name,
        "sample_invoice_id": None,
        "ocr_text": ocr_text,
        "field_confidence": field_confidence,
        # Seed with the tenant's currently-committed Global rules so the user edits from the live baseline.
        "constraints": _global_constraints(db_session, tenant_context.tenant_id),
        "corrected_keys": [],
        "extracted_data": extracted_data,
        "chat_history": [_welcome_message("global", None, file_name)],
        "created_at": datetime.utcnow().isoformat(),
    }
    trainer_sessions.save_session(session_id, session)
    return _serialize_session(session)


@router.post("/sessions/from-production", status_code=status.HTTP_201_CREATED)
def start_from_production_session(
    vendor_name: str = Query(..., description="Vendor whose latest production invoice seeds the sandbox"),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Scope #2 (Existing Vendor): seed from a real, already-extracted production invoice (Task 10.3)."""
    stmt = (
        select(Invoice)
        .where(Invoice.tenant_id == tenant_context.tenant_id, Invoice.vendor_name == vendor_name)
        .order_by(Invoice.created_at.desc())
    )
    invoice = db_session.exec(stmt).first()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No production invoice found for vendor '{vendor_name}'.",
        )

    session_id = str(uuid4())

    # Reuse the invoice's already-stored extraction; re-run OCR only for the raw
    # text (not retained on the row) so chat corrections can re-extract.
    ocr_text = ""
    try:
        ocr_text, _, _ = _run_ocr_split(invoice.file_path)
    except Exception as e:
        logger.warning("Could not re-run OCR for production seed (%s): %s", invoice.id, e)

    extracted_data = {
        "vendor_name": invoice.vendor_name,
        "invoice_number": invoice.invoice_number,
        "invoice_date": str(invoice.invoice_date) if invoice.invoice_date else None,
        "due_date": str(invoice.due_date) if invoice.due_date else None,
        "tax_amount": invoice.tax_amount,
        "grand_total": invoice.grand_total,
        "po_number": invoice.po_number,
        "currency": invoice.currency,
        "discount_amount": invoice.discount_amount,
        "items": invoice.items,
    }

    # Seed constraints from this vendor's existing template, if one exists.
    vendor_tpl = _get_template(db_session, tenant_context.tenant_id, vendor_name)
    seed_constraints = vendor_tpl.rules.get("constraints", []) if (vendor_tpl and isinstance(vendor_tpl.rules, dict)) else []

    session = {
        "session_id": session_id,
        "tenant_id": str(tenant_context.tenant_id),
        "scope": "existing_vendor",
        "vendor_name": vendor_name,
        "file_path": invoice.file_path,
        "file_name": os.path.basename(invoice.file_path),
        "sample_invoice_id": str(invoice.id),
        "ocr_text": ocr_text,
        "field_confidence": invoice.field_confidence or {},
        "constraints": list(seed_constraints),
        "corrected_keys": [],
        "extracted_data": extracted_data,
        "chat_history": [_welcome_message("existing_vendor", vendor_name, None)],
        "created_at": datetime.utcnow().isoformat(),
    }
    trainer_sessions.save_session(session_id, session)
    return _serialize_session(session)


@router.get("/vendors")
def list_trainer_vendors(
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """List the tenant's known vendors (with a sample invoice) for the Existing-Vendor picker."""
    stmt = select(Invoice).where(
        Invoice.tenant_id == tenant_context.tenant_id,
        Invoice.vendor_name.is_not(None),
    )
    invoices = db_session.exec(stmt).all()

    by_vendor: dict[str, dict] = {}
    for inv in invoices:
        name = inv.vendor_name
        if not name:
            continue
        entry = by_vendor.get(name)
        if entry is None:
            by_vendor[name] = {
                "id": name,
                "name": name,
                "invoiceCount": 1,
                "sampleInvoiceId": str(inv.id),
                "sampleFileName": os.path.basename(inv.file_path) if inv.file_path else f"{name}.pdf",
                "samplePdfUrl": f"/api/invoices/{inv.id}/pdf",
            }
        else:
            entry["invoiceCount"] += 1

    return sorted(by_vendor.values(), key=lambda v: v["name"].lower())


# ─────────────────────────────────────────────────────────────────────────────
# Conversational correction — Task 10.5
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/chat")
def trainer_chat(
    session_id: str,
    payload: ChatPayload,
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Refine constraints from a natural-language correction and re-extract."""
    session = trainer_sessions.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training session not found or expired.")
    if session["tenant_id"] != str(tenant_context.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access forbidden to this session.")

    old_constraints = session.get("constraints", []) or []
    old_data = session.get("extracted_data") or {}
    scope = session.get("scope", "new_vendor")

    # For vendor scopes, hand the agent the tenant's Global rules as read-only context
    # so it prefers editing the global rule when a correction is general (Task 10.5).
    global_constraints = _global_constraints(db_session, tenant_context.tenant_id) if scope != "global" else []

    chat_history = session.get("chat_history", [])
    chat_history.append(_msg("user", payload.content))

    try:
        result = run_trainer_agent(
            file_path=session.get("file_path"),
            ocr_text=session.get("ocr_text", ""),
            tenant_id=session["tenant_id"],
            user_message=payload.content,
            current_constraints=old_constraints,
            scope=scope,
            global_constraints=global_constraints,
        )
    except Exception as e:
        logger.error("Trainer Agent failed during chat correction: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to process chat feedback: {str(e)}")

    new_constraints = result.get("constraints", old_constraints)
    new_data = result.get("extracted_data") or old_data

    # A "new rule" = a constraint present now that wasn't before.
    added = [c for c in new_constraints if c not in old_constraints]
    suggested_rule = added[0] if added else None

    # Mark scalar fields whose value changed as corrected (drives the FE tick / highlight).
    corrected = set(session.get("corrected_keys", []))
    for key, _ in _FIELD_LABELS:
        new_val = new_data.get(key)
        if new_val not in (None, "", []) and new_val != old_data.get(key):
            corrected.add(key)

    if suggested_rule:
        reply = f'Understood — I registered a new rule and re-applied it: "{suggested_rule}".'
    elif new_constraints != old_constraints:
        reply = "Updated the active rules and re-ran extraction with them."
    else:
        reply = "I processed your note. No new rule was needed; the extraction is unchanged."
    if result.get("alerts"):
        reply += " Note: some validation alerts remain on the sample."
    chat_history.append(_msg("assistant", reply, suggested_rule))

    session["constraints"] = new_constraints
    session["extracted_data"] = new_data
    session["corrected_keys"] = list(corrected)
    session["chat_history"] = chat_history
    trainer_sessions.save_session(session_id, session)

    return {"updatedSession": _serialize_session(session), "newRuleCreated": suggested_rule}


# ─────────────────────────────────────────────────────────────────────────────
# Commit + versioning + re-audit — Tasks 10.6, 10.7, 10.10
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/commit")
def trainer_commit(
    session_id: str,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Persist session rules to the correct scope, record a version, and queue re-audit."""
    session = trainer_sessions.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training session not found or expired.")
    if session["tenant_id"] != str(tenant_context.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access forbidden to this session.")

    scope = session.get("scope", "new_vendor")
    constraints = session.get("constraints", []) or []
    rules = {"constraints": constraints}

    # Resolve which template row this commits to.
    if scope == "global":
        vendor_name = None
    else:
        vendor_name = session.get("vendor_name") or (session.get("extracted_data") or {}).get("vendor_name")
        if not vendor_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot commit: vendor name was not resolved for this session.",
            )

    changed_by = _resolve_changed_by(db_session, tenant_context)

    template = _get_template(db_session, tenant_context.tenant_id, vendor_name)
    if template:
        template.rules = rules
        template.version = (template.version or 1) + 1
        template.updated_at = datetime.utcnow()
        db_session.add(template)
    else:
        template = ExtractionTemplate(
            id=uuid4(),
            tenant_id=tenant_context.tenant_id,
            vendor_name=vendor_name,
            rules=rules,
            version=1,
        )
        db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # Append the new version to the history log.
    db_session.add(ExtractionTemplateVersion(
        template_id=template.id,
        tenant_id=tenant_context.tenant_id,
        vendor_name=vendor_name,
        version=template.version,
        rules=rules,
        changed_by=changed_by,
    ))
    db_session.commit()

    # Re-audit: Global => all vendors; Existing Vendor => that vendor; New Vendor => none.
    reaudit_queued = False
    if scope == "global":
        reaudit_queued = _enqueue_reaudit(str(tenant_context.tenant_id), None)
    elif scope == "existing_vendor":
        reaudit_queued = _enqueue_reaudit(str(tenant_context.tenant_id), vendor_name)

    # Clean up only transient uploaded files — never a production invoice's blob.
    file_path = session.get("file_path")
    if file_path and scope in ("new_vendor", "global") and "trainer" in file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning("Failed to remove transient session file: %s", e)

    trainer_sessions.delete_session(session_id)

    return {
        "status": "success",
        "scope": scope,
        "vendor_name": vendor_name,
        "version": template.version,
        "rules": rules,
        "reaudit_queued": reaudit_queued,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rule history + rollback — Task 10.10
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/templates/history")
def get_template_history(
    scope: str = Query(..., description="'global' or 'vendor'"),
    vendor_name: Optional[str] = Query(None),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db_session: Session = Depends(get_db_session),
):
    """Version timeline for the active template (Global, or the selected vendor)."""
    resolved_vendor = None if scope == "global" else vendor_name
    template = _get_template(db_session, tenant_context.tenant_id, resolved_vendor)
    if not template:
        return []

    rows = db_session.exec(
        select(ExtractionTemplateVersion)
        .where(ExtractionTemplateVersion.template_id == template.id)
        .order_by(ExtractionTemplateVersion.version.desc())
    ).all()

    return [{
        "id": str(r.id),
        "templateId": str(template.id),
        "version": r.version,
        "scope": scope,
        "vendorName": r.vendor_name,
        "rules": (r.rules or {}).get("constraints", []) if isinstance(r.rules, dict) else [],
        "changedBy": r.changed_by,
        "changedAt": r.changed_at.strftime("%Y-%m-%d %H:%M") if r.changed_at else "",
        "isCurrent": r.version == template.version,
    } for r in rows]


@router.post("/templates/{template_id}/rollback/{version}")
def rollback_template(
    template_id: UUID,
    version: int,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context),
):
    """Promote a past rule version back to current (writes a new version, queues re-audit)."""
    template = db_session.get(ExtractionTemplate, template_id)
    if not template or template.tenant_id != tenant_context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found or access denied.")

    target = db_session.exec(
        select(ExtractionTemplateVersion).where(
            ExtractionTemplateVersion.template_id == template_id,
            ExtractionTemplateVersion.version == version,
        )
    ).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found for this template.")

    template.rules = target.rules
    template.version = (template.version or 1) + 1
    template.updated_at = datetime.utcnow()
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    db_session.add(ExtractionTemplateVersion(
        template_id=template.id,
        tenant_id=tenant_context.tenant_id,
        vendor_name=template.vendor_name,
        version=template.version,
        rules=target.rules,
        changed_by=_resolve_changed_by(db_session, tenant_context),
    ))
    db_session.commit()

    reaudit_queued = _enqueue_reaudit(str(tenant_context.tenant_id), template.vendor_name)

    return {
        "status": "success",
        "version": template.version,
        "rules": template.rules,
        "reaudit_queued": reaudit_queued,
    }
