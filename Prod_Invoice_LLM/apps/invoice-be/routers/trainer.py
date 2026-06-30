import os
import json
import logging
from uuid import UUID, uuid4
from datetime import datetime
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel
from sqlmodel import Session, select

from config import get_settings
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import ExtractionTemplate
from workers.tasks import _run_ocr
from agents.extraction_agent import run_extraction_agent
from agents.trainer_agent import run_trainer_agent
from services.storage import LOCAL_STORAGE_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trainer", tags=["trainer"])

# Global transient session store for the sandbox
TRAINER_SESSIONS: Dict[str, Dict[str, Any]] = {}

DEFAULT_TEMPLATES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "default_templates.json"
)

# Schemas
class ChatPayload(BaseModel):
    content: str

class CommitPayload(BaseModel):
    global_mode: bool = False

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_transient_file(
    file: UploadFile = File(...),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """
    Accepts a PDF file upload, parses layout strings immediately via OCR + Extraction Agent,
    and returns parsed properties + transient session_id without saving to permanent invoices table.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported for training."
        )

    session_id = str(uuid4())
    session_dir = os.path.join(LOCAL_STORAGE_DIR, "trainer")
    os.makedirs(session_dir, exist_ok=True)
    file_path = os.path.join(session_dir, f"{session_id}.pdf")

    # Read and save PDF file transiently
    try:
        content_bytes = await file.read()
        with open(file_path, "wb") as f:
            f.write(content_bytes)
    except Exception as e:
        logger.error("Failed to save transient training file: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file."
        )

    # Execute OCR and Extraction Agent
    settings = get_settings()
    try:
        ocr_text = _run_ocr(file_path, settings)
        extraction_res = run_extraction_agent(file_path, ocr_text, str(tenant_context.tenant_id))
    except Exception as e:
        logger.error("OCR or Extraction Agent failed for transient training: %s", e)
        # Clean up temporary file
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transient parsing failed: {str(e)}"
        )

    # Save to global sandbox session store
    TRAINER_SESSIONS[session_id] = {
        "session_id": session_id,
        "tenant_id": str(tenant_context.tenant_id),
        "file_path": file_path,
        "ocr_text": ocr_text,
        "constraints": [],
        "extracted_data": extraction_res.get("extracted_data") or {}
    }

    return {
        "session_id": session_id,
        "extracted_data": TRAINER_SESSIONS[session_id]["extracted_data"]
    }

@router.post("/sessions/{session_id}/chat")
def trainer_chat(
    session_id: str,
    payload: ChatPayload,
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """
    Process conversational corrections, update layout constraints, and re-extract fields.
    """
    session_data = TRAINER_SESSIONS.get(session_id)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training session not found."
        )

    if session_data["tenant_id"] != str(tenant_context.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden to this session."
        )

    try:
        result = run_trainer_agent(
            file_path=session_data["file_path"],
            ocr_text=session_data["ocr_text"],
            tenant_id=session_data["tenant_id"],
            user_message=payload.content,
            current_constraints=session_data["constraints"]
        )
    except Exception as e:
        logger.error("Trainer Agent failed during chat correction: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat feedback: {str(e)}"
        )

    # Update state
    session_data["constraints"] = result["constraints"]
    session_data["extracted_data"] = result["extracted_data"] or {}

    return {
        "constraints": result["constraints"],
        "extracted_data": result["extracted_data"],
        "status": result["status"],
        "alerts": result["alerts"]
    }

@router.post("/sessions/{session_id}/commit")
def trainer_commit(
    session_id: str,
    payload: CommitPayload,
    db_session: Session = Depends(get_db_session),
    tenant_context: TenantContext = Depends(get_tenant_context)
):
    """
    Save customized rules to PostgreSQL or static default_templates.json.
    """
    session_data = TRAINER_SESSIONS.get(session_id)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training session not found."
        )

    if session_data["tenant_id"] != str(tenant_context.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden to this session."
        )

    vendor_name = session_data["extracted_data"].get("vendor_name")
    if not vendor_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot commit rules because vendor name was not successfully extracted."
        )

    rules = {"constraints": session_data["constraints"]}

    if payload.global_mode:
        # Global Developer Mode: write to default_templates.json
        os.makedirs(os.path.dirname(DEFAULT_TEMPLATES_PATH), exist_ok=True)
        default_templates = {}
        if os.path.exists(DEFAULT_TEMPLATES_PATH):
            try:
                with open(DEFAULT_TEMPLATES_PATH, "r") as f:
                    default_templates = json.load(f)
            except Exception as e:
                logger.error("Failed to load global default templates: %s", e)

        default_templates[vendor_name] = rules

        try:
            with open(DEFAULT_TEMPLATES_PATH, "w") as f:
                json.dump(default_templates, f, indent=2)
        except Exception as e:
            logger.error("Failed to write to default_templates.json: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save global template rules."
            )
    else:
        # Tenant specific mode: save to database
        stmt = select(ExtractionTemplate).where(
            ExtractionTemplate.tenant_id == tenant_context.tenant_id,
            ExtractionTemplate.vendor_name == vendor_name
        )
        template = db_session.exec(stmt).first()

        if template:
            template.rules = rules
            template.updated_at = datetime.utcnow()
            db_session.add(template)
        else:
            template = ExtractionTemplate(
                id=uuid4(),
                tenant_id=tenant_context.tenant_id,
                vendor_name=vendor_name,
                rules=rules
            )
            db_session.add(template)

        db_session.commit()
        db_session.refresh(template)

    # Clean up the transient training session file
    file_path = session_data["file_path"]
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning("Failed to remove transient session file: %s", e)

    # Remove session from store
    TRAINER_SESSIONS.pop(session_id, None)

    return {
        "status": "success",
        "vendor_name": vendor_name,
        "rules": rules
    }
