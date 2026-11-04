"""
EXRP AI Control Plane
Declarative metadata bridge and safety guardrails for conversational customization.
"""

from .schema_extractor import get_compact_doctype_schema
from .safety_guardrails import validate_mutation_safety, ZoneSafetyViolation
from .ddl_plan_gate import inspect_frappe_ddl_plan, DDLPlanInspection, validate_ddl_plan
from .schema_reconciler import (
    execute_single_field_deployment,
    ExhaustiveSnapshot,
    IdempotencyConflictError,
    make_bounded_lock_key,
)
from .planner import (
    ProposedFieldChange,
    ConfigurationProposal,
    PlannerResult,
    AIConfigurationPlanner,
)
from .policy_enforcer import (
    PolicyType,
    RuntimePolicy,
    PolicyEvaluationResult,
    RuntimePolicyViolation,
    RuntimePolicyCatalog,
    policy_catalog,
)

__all__ = [
    "get_compact_doctype_schema",
    "validate_mutation_safety",
    "ZoneSafetyViolation",
    "inspect_frappe_ddl_plan",
    "DDLPlanInspection",
    "validate_ddl_plan",
    "execute_single_field_deployment",
    "ExhaustiveSnapshot",
    "IdempotencyConflictError",
    "make_bounded_lock_key",
    "ProposedFieldChange",
    "ConfigurationProposal",
    "PlannerResult",
    "AIConfigurationPlanner",
    "PolicyType",
    "RuntimePolicy",
    "PolicyEvaluationResult",
    "RuntimePolicyViolation",
    "RuntimePolicyCatalog",
    "policy_catalog",
]
