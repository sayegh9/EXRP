"""
EXRP Whitelisted API Endpoints & Document Lifecycle Hooks
Implements supported Frappe REST and Desk RPC interfaces for the AI Control Plane.
"""

from typing import Dict, Any, Optional
import json

# Safe imports for standalone execution or Frappe runtime
try:
    import frappe
    from frappe import _
except ImportError:
    frappe = None

from exrp.ai_control_plane.schema_extractor import get_compact_doctype_schema
from exrp.ai_control_plane.safety_guardrails import validate_mutation_safety, ZoneSafetyViolation
from exrp.ai_control_plane.ddl_plan_gate import inspect_frappe_ddl_plan
from exrp.ai_control_plane.schema_reconciler import (
    execute_single_field_deployment,
    Rev23DeploymentAdapter,
)


def get_current_user_roles() -> list:
    """Returns the authenticated Frappe user's assigned roles."""
    if frappe and hasattr(frappe, "get_roles"):
        return frappe.get_roles(frappe.session.user)
    return ["System Manager"]


def propose_configuration_change(doctype: str, proposal_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Whitelisted RPC method: Evaluates an AI proposal against the 2-Axis Policy Compiler
    and generates the non-executing DDL Plan Gate evidence.
    Does NOT execute physical DDL or write to production tables.
    """
    proposal_payload["target_doctype"] = doctype
    proposal_payload["user_roles"] = get_current_user_roles()

    # Step 1: Policy & Invariant Evaluation
    validation_result = validate_mutation_safety(proposal_payload)

    # Step 2: DDL Plan Gate Inspection (Zero DDL executed)
    changes = proposal_payload.get("changes", [])
    ddl_plan_result = None
    if proposal_payload.get("intent") == "add_custom_fields" and changes:
        field_def = changes[0]
        ddl_plan = inspect_frappe_ddl_plan(doctype, field_def)
        ddl_plan_result = {
            "inspectable": ddl_plan.inspectable,
            "statements": ddl_plan.statements,
            "is_approved_additive_only": ddl_plan.is_approved_additive_only,
            "rejection_reason": ddl_plan.rejection_reason,
        }

    return {
        "status": "PROPOSED",
        "validation": validation_result,
        "ddl_plan": ddl_plan_result,
        "preview_fidelity_notice": (
            "Layout, labels, and field controls previewed. "
            "ERPNext tax/pricing recalculations and server validations execute on real documents."
        ),
    }


# Frappe whitelisted decorator when running inside Frappe
if frappe and hasattr(frappe, "whitelist"):
    propose_configuration_change = frappe.whitelist()(propose_configuration_change)


def enforce_runtime_policies_on_validate(doc, method=None):
    """Lifecycle hook for Document.validate"""
    pass


def enforce_runtime_policies_on_submit(doc, method=None):
    """Lifecycle hook for Document.before_submit"""
    pass


def enforce_runtime_policies_on_update_after_submit(doc, method=None):
    """Lifecycle hook for Document.before_update_after_submit"""
    pass
