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

from .property_setter_engine import execute_property_setter_deployment
from .rollback_engine import execute_rollback
from .workflow_engine import (
    WorkflowStateModel,
    WorkflowTransitionModel,
    WorkflowDefinition,
    WorkflowValidationResult,
    validate_workflow_state_machine,
    execute_workflow_deployment,
    generate_mermaid_graph,
)
from .report_engine import (
    ReportColumn,
    ReportFilter,
    ReportChartConfig,
    ReportDefinition,
    ReportValidationResult,
    validate_report_definition,
    get_report_preview_data,
    execute_report_deployment,
)
from .cross_doc_policy import (
    CrossDocPolicy,
    CrossDocPolicyCatalog,
    cross_doc_catalog,
)

__all__ = [
    "get_compact_doctype_schema",
    "validate_mutation_safety",
    "ZoneSafetyViolation",
    "inspect_frappe_ddl_plan",
    "DDLPlanInspection",
    "validate_ddl_plan",
    "execute_single_field_deployment",
    "execute_property_setter_deployment",
    "execute_workflow_deployment",
    "execute_report_deployment",
    "execute_rollback",
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
    "WorkflowStateModel",
    "WorkflowTransitionModel",
    "WorkflowDefinition",
    "WorkflowValidationResult",
    "validate_workflow_state_machine",
    "generate_mermaid_graph",
    "ReportColumn",
    "ReportFilter",
    "ReportChartConfig",
    "ReportDefinition",
    "ReportValidationResult",
    "validate_report_definition",
    "get_report_preview_data",
    "CrossDocPolicy",
    "CrossDocPolicyCatalog",
    "cross_doc_catalog",
]
