import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from utils.llm import get_llm
from langchain_core.messages import SystemMessage, HumanMessage
from agents.extraction_agent import run_extraction_agent

logger = logging.getLogger(__name__)

class ConstraintList(BaseModel):
    model_config = {"extra": "forbid"}
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

def _build_system_prompt(scope: str, global_constraints: List[str]) -> str:
    """Augment the base prompt with scope-specific guidance (Task 10.5)."""
    prompt = SYSTEM_PROMPT
    if scope == "global":
        prompt += (
            "\n\nSCOPE: GLOBAL. These constraints apply tenant-wide to EVERY vendor. "
            "Keep them vendor-agnostic and universally valid (e.g. tax/rounding conventions, "
            "date formats, currency handling). Do not introduce rules that only make sense "
            "for one specific vendor."
        )
    else:
        prompt += (
            "\n\nSCOPE: VENDOR-SPECIFIC. Only manage constraints unique to THIS vendor."
        )
        if global_constraints:
            prompt += (
                "\nThe following GLOBAL rules already apply to this vendor automatically. "
                "Treat them as read-only context: do NOT restate or duplicate them, and only "
                "add constraints not already covered globally:\n"
                + "\n".join(f"- {c}" for c in global_constraints)
            )
    return prompt


def refine_constraints(
    user_message: str,
    current_constraints: List[str],
    scope: str = "new_vendor",
    global_constraints: Optional[List[str]] = None,
) -> List[str]:
    """
    Uses LLM to refine the list of rules/constraints based on user conversational corrections.

    ``scope`` and ``global_constraints`` make the refinement scope-aware (Task 10.5): a
    Global session keeps rules vendor-agnostic, while a vendor session receives the tenant's
    Global rules as read-only context so it avoids duplicating them.
    """
    global_constraints = global_constraints or []
    llm = get_llm()
    try:
        structured_llm = llm.with_structured_output(ConstraintList)
        system_prompt = _build_system_prompt(scope, global_constraints)
        prompt = f"Current constraints: {current_constraints}\nUser feedback: {user_message}"
        messages = [
            SystemMessage(content=system_prompt),
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
    file_path: Optional[str],
    ocr_text: str,
    tenant_id: str,
    user_message: str,
    current_constraints: List[str],
    scope: str = "new_vendor",
    global_constraints: Optional[List[str]] = None,
) -> dict:
    """
    Refines layout constraints based on user feedback and (when a sample PDF is available)
    re-runs the extraction agent with the updated constraints.

    ``scope`` is one of "global" | "existing_vendor" | "new_vendor"; ``global_constraints``
    is the tenant's current Global-template rules, passed as read-only context for vendor scopes.
    """
    updated_constraints = refine_constraints(
        user_message, current_constraints, scope=scope, global_constraints=global_constraints
    )
    rules = {"constraints": updated_constraints}

    # Chat-only sessions (e.g. a Global session started without a sample PDF) have nothing
    # to re-extract against — return the refined rules without touching the extraction agent.
    if not file_path or not ocr_text:
        return {
            "constraints": updated_constraints,
            "extracted_data": {},
            "status": "NO_SAMPLE",
            "alerts": [],
        }

    extraction_result = run_extraction_agent(file_path, ocr_text, tenant_id, rules=rules)

    return {
        "constraints": updated_constraints,
        "extracted_data": extraction_result["extracted_data"],
        "status": extraction_result["status"],
        "alerts": extraction_result["alerts"]
    }
