"""BE Gap 567: no two classes in agents/extraction_agent.py share a name.

A second `class DeductionItem` (remittance advice) replaced the invoice one at module level, so a
by-name import returned the wrong model and refused every valid invoice deduction correction.
"""
import ast
from collections import Counter
from pathlib import Path
from typing import get_args

import agents.extraction_agent as extraction_agent


def test_no_two_classes_in_the_extraction_agent_share_a_name():
    tree = ast.parse(Path(extraction_agent.__file__).read_text(encoding="utf-8"))
    counts = Counter(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    assert [name for name, count in counts.items() if count > 1] == []


def test_each_deduction_model_is_the_one_its_schema_uses():
    invoice_entry = get_args(extraction_agent.InvoiceExtractionSchema.model_fields["deductions"].annotation)[0]
    remittance_entry = get_args(extraction_agent.GenericDocumentSchema.model_fields["payment_deductions"].annotation)[0]
    assert invoice_entry is extraction_agent.DeductionItem
    assert remittance_entry is extraction_agent.RemittanceDeductionItem
    assert set(extraction_agent.DeductionItem.model_fields) == {"deduction_type", "amount"}
    assert set(extraction_agent.RemittanceDeductionItem.model_fields) == {"kind", "amount", "currency", "reference"}
