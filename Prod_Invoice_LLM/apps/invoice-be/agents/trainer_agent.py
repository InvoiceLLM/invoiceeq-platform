import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from utils.llm import get_llm
from langchain_core.messages import SystemMessage, HumanMessage
from agents.extraction_agent import run_extraction_agent

logger = logging.getLogger(__name__)

class ConstraintList(BaseModel):
    constraints: List[str] = Field(description="The refined list of layout constraints/rules")

SYSTEM_PROMPT = (
    "You are an AI Trainer Agent for an invoice processing pipeline.\n"
    "Your task is to maintain a set of layout extraction constraints or templates "
    "for a specific vendor's invoices based on conversational corrections from the user.\n"
    "You will receive the current list of constraints and a new user correction. "
    "Refine, update, remove, or append to the constraints to resolve the user's feedback. "
    "Keep constraints generic yet clear (e.g. 'The invoice date is located below the invoice number', "
    "'The invoice_number field is always prefixed with INV-').\n"
    "Output the final list of active constraints."
)

def refine_constraints(user_message: str, current_constraints: List[str]) -> List[str]:
    """
    Uses LLM to refine the list of rules/constraints based on user conversational corrections.
    """
    llm = get_llm(temperature=0.0)
    try:
        structured_llm = llm.with_structured_output(ConstraintList)
        prompt = f"Current constraints: {current_constraints}\nUser feedback: {user_message}"
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        result = structured_llm.invoke(messages)
        if hasattr(result, "constraints"):
            return result.constraints
        elif isinstance(result, dict) and "constraints" in result:
            return result["constraints"]
        return current_constraints + [user_message]
    except Exception as e:
        logger.warning("Failed to refine constraints via LLM: %s. Appending user message directly.", e)
        return current_constraints + [user_message]

def run_trainer_agent(
    file_path: str,
    ocr_text: str,
    tenant_id: str,
    user_message: str,
    current_constraints: List[str]
) -> dict:
    """
    Refines layout constraints based on user feedback and runs the extraction agent
    with the updated constraints.
    """
    updated_constraints = refine_constraints(user_message, current_constraints)
    rules = {"constraints": updated_constraints}
    extraction_result = run_extraction_agent(file_path, ocr_text, tenant_id, rules=rules)
    
    return {
        "constraints": updated_constraints,
        "extracted_data": extraction_result["extracted_data"],
        "status": extraction_result["status"],
        "alerts": extraction_result["alerts"]
    }
