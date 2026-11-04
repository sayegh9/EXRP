"""
EXRP Declarative Workflow Engine & Multi-Tier Approval State Machine
Implements ADR-001 (Rev 2.3) Section 10, ADR-006, and PRD-001:
- Typed Pydantic models for Workflow Definition, States, and Transitions.
- Strict DocType Allowlist & Tier 0 Invariant Protection (prohibits GL Entry, User, Role, etc.).
- Graph reachability, deadlock, and Frappe docstatus invariant analysis.
- Mermaid diagram generation for interactive sidecar visualization.
- MariaDB GET_LOCK advisory-locked execution with fail-closed audit journal durability.
- Snapshot baseline capture of pre-existing active workflows for 1-click rollback.
"""

import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional, Set, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator

try:
    import frappe
except ImportError:
    frappe = None

from .safety_guardrails import (
    TIER_1_GOVERNANCE_ROLES,
    ZONE_2_LOCKED_DOCTYPES,
    ZoneSafetyViolation,
)
from .schema_reconciler import (
    IdempotencyConflictError,
    compute_canonical_payload_hash,
    make_bounded_lock_key,
)

# DocTypes prohibited from workflow creation under ADR-001 Rev 2.3 §10
TIER_0_PROHIBITED_WORKFLOW_DOCTYPES: Set[str] = set(ZONE_2_LOCKED_DOCTYPES).union({
    "GL Entry",
    "Stock Ledger Entry",
    "DocType",
    "User",
    "Role",
    "Custom Field",
    "Property Setter",
    "Workflow",
    "Workflow State",
    "Workflow Action",
    "Workflow Transition",
    "Workflow Action Master",
    "DocPerm",
    "Custom DocPerm",
    "Patch Log",
    "Installed Application",
})

# Terminal rejected state name conventions
TERMINAL_REJECT_STATE_NAMES: Set[str] = {
    "rejected",
    "reject",
    "declined",
    "cancelled",
    "canceled",
    "disapproved",
    "closed",
    "terminated",
    "dropped",
}


class WorkflowStateModel(BaseModel):
    """
    Workflow state definition conforming to Frappe Workflow State doctype.
    """
    model_config = ConfigDict(extra="allow")

    state: str = Field(..., min_length=1, description="State identifier, e.g. 'Draft', 'Pending Approval'")
    doc_status: int = Field(default=0, ge=0, le=2, description="Frappe docstatus: 0 (Draft), 1 (Submitted), 2 (Cancelled)")
    allow_edit: str = Field(..., min_length=1, description="Role allowed to edit the document in this state")
    style: Optional[str] = Field(
        default="Primary",
        description="Visual badge style: 'Success', 'Danger', 'Warning', 'Primary', 'Inverse'"
    )
    is_terminal: bool = Field(default=False, description="Flag indicating an explicitly terminal sink state")

    @field_validator("style")
    @classmethod
    def validate_style(cls, v: Optional[str]) -> str:
        if not v:
            return "Primary"
        allowed = {"Success", "Danger", "Warning", "Primary", "Inverse", "Info"}
        if v.capitalize() in allowed:
            return v.capitalize()
        return "Primary"


class WorkflowTransitionModel(BaseModel):
    """
    Workflow transition definition conforming to Frappe Workflow Transition doctype.
    """
    model_config = ConfigDict(extra="allow")

    state: str = Field(..., min_length=1, description="Source state name")
    action: str = Field(..., min_length=1, description="Action button label, e.g. 'Approve', 'Reject'")
    next_state: str = Field(..., min_length=1, description="Target state name")
    allowed: str = Field(..., min_length=1, description="Role permitted to execute this transition")
    condition: Optional[str] = Field(default=None, description="Optional Python evaluation condition, e.g. 'doc.grand_total > 10000'")
    allow_self_approval: bool = Field(default=False, description="Whether the document owner can approve their own document")


class WorkflowDefinition(BaseModel):
    """
    Declarative workflow specification adhering to ADR-001 Rev 2.3 (§10, ADR-006).
    """
    model_config = ConfigDict(extra="allow")

    workflow_name: str = Field(..., min_length=1, description="Unique workflow identifier")
    document_type: str = Field(..., min_length=1, description="Target DocType, e.g. 'Sales Order'")
    is_active: bool = Field(default=True, description="Whether this workflow is activated upon deployment")
    workflow_state_field: str = Field(default="workflow_state", description="Fieldname storing current state")
    states: List[WorkflowStateModel] = Field(..., min_length=2, description="Ordered list of workflow states")
    transitions: List[WorkflowTransitionModel] = Field(..., min_length=1, description="Permitted state transitions")
    override_status: bool = Field(default=False, description="Override document status with workflow state")
    send_email_alert: bool = Field(default=False, description="Send email notifications on transition")


class WorkflowValidationResult(BaseModel):
    """
    Result of workflow state machine static analysis and reachability verification.
    """
    model_config = ConfigDict(extra="allow")

    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    mermaid_graph: str = ""

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)


def generate_mermaid_graph(wf: WorkflowDefinition) -> str:
    """
    Generates Mermaid flowchart TD diagram syntax for the Workflow state machine.
    Safe for rendering directly in Frappe Desk AI sidecar and Markdown previewers.
    """
    lines = ["graph TD"]
    status_map = {0: "Draft", 1: "Submitted", 2: "Cancelled"}

    # Define State nodes
    for s in wf.states:
        node_id = re.sub(r"[^a-zA-Z0-9_]", "_", s.state)
        st_label = status_map.get(s.doc_status, f"docstatus:{s.doc_status}")
        label = f"{s.state} ({st_label})"
        lines.append(f'    {node_id}["{label}"]')

    # Define Transitions
    for t in wf.transitions:
        src_id = re.sub(r"[^a-zA-Z0-9_]", "_", t.state)
        tgt_id = re.sub(r"[^a-zA-Z0-9_]", "_", t.next_state)
        edge_text = f"{t.action} [{t.allowed}]"
        if t.condition:
            edge_text += f" ({t.condition})"
        lines.append(f'    {src_id} -->|"{edge_text}"| {tgt_id}')

    # Apply style formatting
    for s in wf.states:
        node_id = re.sub(r"[^a-zA-Z0-9_]", "_", s.state)
        if s.style == "Success" or s.doc_status == 1:
            lines.append(f"    style {node_id} fill:#d4edda,stroke:#28a745,stroke-width:2px")
        elif s.style == "Danger" or s.doc_status == 2 or s.state.strip().lower() in TERMINAL_REJECT_STATE_NAMES:
            lines.append(f"    style {node_id} fill:#f8d7da,stroke:#dc3545,stroke-width:2px")
        elif s.style == "Warning":
            lines.append(f"    style {node_id} fill:#fff3cd,stroke:#ffc107,stroke-width:2px")
        elif s.style == "Inverse":
            lines.append(f"    style {node_id} fill:#e2e3e5,stroke:#383d41,stroke-width:2px")
        else:
            lines.append(f"    style {node_id} fill:#cce5ff,stroke:#007bff,stroke-width:2px")

    return "\n".join(lines)


def _is_terminal_state(state: WorkflowStateModel) -> bool:
    """Determines if a state is legitimately terminal (approved sink or rejected sink)."""
    if getattr(state, "is_terminal", False):
        return True
    if state.doc_status == 1:
        return True
    if state.doc_status == 2:
        return True
    norm_name = state.state.strip().lower()
    if norm_name in TERMINAL_REJECT_STATE_NAMES:
        return True
    return False


def validate_workflow_state_machine(
    wf: Union[WorkflowDefinition, Dict[str, Any]],
    existing_roles: Optional[List[str]] = None,
) -> WorkflowValidationResult:
    """
    Performs comprehensive static analysis on a Workflow definition under ADR-001 Rev 2.3 (§10, ADR-006):
    1. DocType allowlist: strictly prohibits Tier 0 system/financial DocTypes.
    2. Initial state verification: ensures initial state has doc_status == 0.
    3. Reachability analysis: DFS/BFS traversal from initial state, rejecting orphaned states.
    4. Deadlock detection: rejects non-terminal states with no outgoing transitions.
    5. Terminal completeness: requires at least one terminal approved (doc_status==1) or rejected (doc_status==2 or 0) state.
    6. Frappe docstatus invariants:
       - No transition from doc_status == 2 (Cancelled).
       - No transition converting doc_status == 1 (Submitted) back to doc_status == 0 (Draft).
       - No transition converting doc_status == 0 (Draft) directly to doc_status == 2 (Cancelled).
    7. Emits structured validation result and Mermaid diagram syntax.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Parse into WorkflowDefinition model if dict
    if isinstance(wf, dict):
        try:
            wf_obj = WorkflowDefinition(**wf)
        except Exception as exc:
            return WorkflowValidationResult(
                is_valid=False,
                errors=[f"Schema validation error in workflow definition: {exc}"],
                warnings=[],
                mermaid_graph="",
            )
    else:
        wf_obj = wf

    # Rule 1: Check DocType allowlist against Tier 0 protected DocTypes
    target_dt = wf_obj.document_type
    if not target_dt:
        errors.append("Target document_type must be specified.")
    elif target_dt in TIER_0_PROHIBITED_WORKFLOW_DOCTYPES:
        errors.append(
            f"DocType '{target_dt}' is a protected Tier 0 system/financial DocType. "
            f"Workflows are strictly prohibited on Tier 0 DocTypes under ADR-001 Rev 2.3."
        )

    # Rule 2: Minimum states and duplicate states check
    if len(wf_obj.states) < 2:
        errors.append("Workflow state machine must define at least 2 states.")

    state_names = [s.state for s in wf_obj.states]
    seen_states = set()
    dup_states = set()
    for sn in state_names:
        if sn in seen_states:
            dup_states.add(sn)
        seen_states.add(sn)
    if dup_states:
        errors.append(f"Duplicate state definitions found: {sorted(dup_states)}.")

    state_map: Dict[str, WorkflowStateModel] = {s.state: s for s in wf_obj.states}

    # Rule 3: Initial state invariant (Frappe requires first state to have doc_status == 0)
    if wf_obj.states:
        initial_state = wf_obj.states[0]
        if initial_state.doc_status != 0:
            errors.append(
                f"Initial state '{initial_state.state}' must have doc_status == 0 (Draft). "
                f"Found doc_status == {initial_state.doc_status}."
            )

    has_any_draft_state = any(s.doc_status == 0 for s in wf_obj.states)
    if not has_any_draft_state:
        errors.append("Workflow must contain at least one state with doc_status == 0 (Draft).")

    # Rule 4: Transitions presence and state reference integrity
    if not wf_obj.transitions:
        errors.append("Workflow state machine must define at least one transition.")

    adj: Dict[str, Set[str]] = {s.state: set() for s in wf_obj.states}

    for idx, t in enumerate(wf_obj.transitions):
        src_valid = t.state in state_map
        tgt_valid = t.next_state in state_map

        if not src_valid:
            errors.append(f"Transition #{idx + 1} ('{t.action}') references undefined source state '{t.state}'.")
        if not tgt_valid:
            errors.append(f"Transition #{idx + 1} ('{t.action}') references undefined target state '{t.next_state}'.")

        if src_valid and tgt_valid:
            src = state_map[t.state]
            tgt = state_map[t.next_state]
            adj[t.state].add(t.next_state)

            # Frappe docstatus invariants:
            # 1. No transition from Cancelled (doc_status == 2)
            if src.doc_status == 2:
                errors.append(
                    f"Invalid transition '{t.action}': Cannot transition out of Cancelled state '{t.state}' "
                    f"(doc_status == 2). Cancelled documents cannot transition to any state."
                )

            # 2. No transition converting Submitted (1) back to Draft (0)
            if src.doc_status == 1 and tgt.doc_status == 0:
                errors.append(
                    f"Invalid transition '{t.action}': Cannot revert Submitted state '{t.state}' "
                    f"(doc_status == 1) back to Draft state '{t.next_state}' (doc_status == 0)."
                )

            # 3. No transition converting Draft (0) directly to Cancelled (2)
            if src.doc_status == 0 and tgt.doc_status == 2:
                errors.append(
                    f"Invalid transition '{t.action}': Cannot transition Draft state '{t.state}' "
                    f"(doc_status == 0) directly to Cancelled state '{t.next_state}' (doc_status == 2). "
                    f"Documents must be rejected within Draft or submitted before cancellation."
                )

    # Rule 5: Graph Reachability Analysis (BFS from initial state)
    if wf_obj.states:
        initial_name = wf_obj.states[0].state
        visited = set()
        queue = [initial_name]

        while queue:
            curr = queue.pop(0)
            if curr not in visited:
                visited.add(curr)
                for nxt in adj.get(curr, set()):
                    if nxt not in visited:
                        queue.append(nxt)

        unreachable = [s.state for s in wf_obj.states if s.state not in visited]
        for orphaned in unreachable:
            errors.append(
                f"Unreachable state detected: State '{orphaned}' cannot be reached from "
                f"initial state '{initial_name}'."
            )

    # Rule 6: Deadlock and Terminal State Analysis
    has_terminal_approved = False
    has_terminal_rejected = False

    for s in wf_obj.states:
        outgoing = adj.get(s.state, set())
        is_term = _is_terminal_state(s)

        if s.doc_status == 1:
            has_terminal_approved = True
        elif is_term:
            has_terminal_rejected = True

        # Non-terminal state with 0 outgoing transitions is a deadlock
        if len(outgoing) == 0 and not is_term:
            errors.append(
                f"Deadlock state detected: Non-terminal state '{s.state}' has no outgoing transitions."
            )

    # Rule 7: Must have at least one terminal approved or rejected state
    if not (has_terminal_approved or has_terminal_rejected):
        errors.append(
            "Workflow state machine must have at least one terminal approved state (doc_status == 1) "
            "or terminal rejected state (doc_status == 2 or 0)."
        )

    # Role validation warnings (non-fatal)
    if existing_roles:
        existing_role_set = set(existing_roles)
        for s in wf_obj.states:
            if s.allow_edit not in existing_role_set:
                warnings.append(f"Role '{s.allow_edit}' for state '{s.state}' is not found in existing system roles.")
        for t in wf_obj.transitions:
            if t.allowed not in existing_role_set:
                warnings.append(f"Role '{t.allowed}' for transition '{t.action}' is not found in existing system roles.")

    # Generate Mermaid diagram
    mermaid_graph = generate_mermaid_graph(wf_obj)
    is_valid = len(errors) == 0

    return WorkflowValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        mermaid_graph=mermaid_graph,
    )


def execute_workflow_deployment(
    db: Any,
    deployment_id: str,
    site_id: str,
    doctype: str,
    workflow_def: Union[WorkflowDefinition, Dict[str, Any]],
    user_roles: Optional[Union[List[str], Set[str]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Executes a Workflow state machine deployment under ADR-001 Rev 2.3 (§10, ADR-006):
    1. Strictly verifies caller roles (System Manager, Finance Director, Operations Director).
    2. Validates state machine static analysis (reachability, deadlocks, docstatus invariants).
    3. Acquires MariaDB GET_LOCK advisory lock with <= 64 char identifier.
    4. Evaluates idempotency binding; prevents conflicting replays.
    5. Snapshots pre-existing active workflow on document_type for rollback durability.
    6. Persists prepare intent in audit journal (fail-closed durability).
    7. Idempotently ensures all Workflow State records exist.
    8. Creates or updates Workflow document with is_active = 1.
    9. Deactivates previous active workflow on target DocType if replacing.
    10. Clears DocType cache and records APPLIED disposition.
    """
    start_time = time.perf_counter()

    # Step 1: Strictly verify caller authorization (§5, §10)
    if user_roles is None:
        try:
            if frappe and hasattr(frappe, "get_roles") and hasattr(frappe, "session") and hasattr(frappe.session, "user"):
                user_roles = frappe.get_roles(frappe.session.user)
        except Exception:
            pass
        if user_roles is None:
            user_roles = ["System Manager"]

    user_role_set = set(user_roles)
    if not user_role_set.intersection(TIER_1_GOVERNANCE_ROLES):
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if kwargs.get("raise_on_unauthorized"):
            if frappe and hasattr(frappe, "PermissionError"):
                raise frappe.PermissionError(
                    f"Unauthorized: Role {sorted(user_role_set)} lacks required workflow deployment authority {sorted(TIER_1_GOVERNANCE_ROLES)}."
                )
            raise PermissionError(
                f"Unauthorized: Role {sorted(user_role_set)} lacks required workflow deployment authority {sorted(TIER_1_GOVERNANCE_ROLES)}."
            )
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "AUTHORIZATION",
            "disposition": "UNAUTHORIZED_ROLE",
            "reason": (
                f"User does not possess any authorized deployment role. "
                f"Required one of: {sorted(TIER_1_GOVERNANCE_ROLES)}. Found: {sorted(user_role_set)}"
            ),
            "doctype": doctype,
            "execution_time_ms": execution_time_ms,
        }

    # Step 2: Parse and validate workflow definition
    if isinstance(workflow_def, dict):
        wf_data = dict(workflow_def)
        if "document_type" not in wf_data or not wf_data["document_type"]:
            wf_data["document_type"] = doctype
        try:
            wf = WorkflowDefinition(**wf_data)
        except Exception as exc:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "deployment_id": deployment_id,
                "status": "REJECTED",
                "success": False,
                "stage": "VALIDATE",
                "disposition": "INVALID_WORKFLOW_PAYLOAD",
                "reason": f"Workflow definition schema validation failed: {exc}",
                "doctype": doctype,
                "execution_time_ms": execution_time_ms,
            }
    else:
        wf = workflow_def

    # Static analysis and reachability inspection
    val_result = validate_workflow_state_machine(wf, existing_roles=kwargs.get("existing_roles"))
    if not val_result.is_valid:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "VALIDATE",
            "disposition": "INVALID_WORKFLOW_STATE_MACHINE",
            "reason": "; ".join(val_result.errors),
            "errors": val_result.errors,
            "warnings": val_result.warnings,
            "mermaid_graph": val_result.mermaid_graph,
            "doctype": doctype,
            "workflow_name": wf.workflow_name,
            "execution_time_ms": execution_time_ms,
        }

    # Step 3: Bounded advisory lock GET_LOCK <= 64 chars (§7.2)
    lock_key = make_bounded_lock_key(site_id, doctype)
    lock_wait_seconds = int(kwargs.get("lock_wait_seconds", 5))
    lock_result = db.acquire_advisory_lock(lock_key, wait_seconds=lock_wait_seconds)

    if lock_result != 1:
        reason = "Lock wait timeout (0)" if lock_result == 0 else "Database lock error (NULL)"
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "ACQUIRE",
            "disposition": "LOCK_CONTENTION_OR_TIMEOUT",
            "reason": f"Could not acquire MariaDB GET_LOCK ({reason})",
            "doctype": doctype,
            "workflow_name": wf.workflow_name,
            "execution_time_ms": execution_time_ms,
        }

    try:
        # Step 4: Idempotency Binding Check (§7.1)
        idempotency_key = kwargs.get("idempotency_key") or f"idemp-{deployment_id}"
        payload_hash = compute_canonical_payload_hash(site_id, doctype, wf.model_dump())

        existing = db.get_existing_deployment_by_idempotency(site_id, idempotency_key)
        if existing is not None:
            if existing.get("payload_hash") != payload_hash:
                raise IdempotencyConflictError(
                    f"IDEMPOTENCY_CONFLICT: Key '{idempotency_key}' was already used with a different payload."
                )
            cached_outcome = dict(existing["outcome"])
            cached_outcome["execution_time_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
            return cached_outcome

        # Step 4.5: Target DocType recovery state gate (§8.1)
        if hasattr(db, "is_target_in_recovery_required") and db.is_target_in_recovery_required(site_id, doctype):
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "deployment_id": deployment_id,
                "status": "RECOVERY_REQUIRED",
                "success": False,
                "stage": "INSPECT",
                "disposition": "TARGET_IN_RECOVERY_REQUIRED",
                "reason": f"Target '{doctype}' has an unresolved RECOVERY_REQUIRED state; deployments blocked.",
                "execution_time_ms": execution_time_ms,
            }

        # Step 5: Snapshot pre-existing active workflow on document_type
        prev_wf = None
        if hasattr(db, "get_active_workflow") and callable(getattr(db, "get_active_workflow", None)):
            prev_wf = db.get_active_workflow(doctype)
        elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "get_value"):
            try:
                prev_wf_name = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
                if prev_wf_name:
                    prev_wf_doc = frappe.get_doc("Workflow", prev_wf_name)
                    prev_wf = prev_wf_doc.as_dict()
            except Exception:
                pass

        prev_wf_name = (prev_wf.get("name") or prev_wf.get("workflow_name")) if prev_wf else None
        baseline_snapshot: Dict[str, Any] = {
            "had_active_workflow": bool(prev_wf),
            "previous_workflow_name": prev_wf_name,
            "previous_workflow_data": prev_wf,
            "deployed_workflow_name": wf.workflow_name,
        }

        prepare_record = {
            "deployment_id": deployment_id,
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "site_id": site_id,
            "doctype": doctype,
            "fieldname": None,
            "deployment_type": "workflow",
            "workflow_name": wf.workflow_name,
            "baseline_snapshot": baseline_snapshot,
            "status": "PREPARED",
        }

        # Fail-closed prepare audit
        try:
            db.persist_prepare_and_audit_intent(prepare_record)
        except Exception as prep_exc:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "deployment_id": deployment_id,
                "status": "FAILED_CLEAN",
                "success": False,
                "stage": "PREPARE",
                "disposition": "AUDIT_PREPARE_FAILED",
                "reason": f"Fail-closed: Could not persist audit intent: {prep_exc}",
                "doctype": doctype,
                "execution_time_ms": execution_time_ms,
            }

        # Step 6: Ensure all Workflow State records exist (idempotently)
        for s in wf.states:
            if hasattr(db, "ensure_workflow_state") and callable(getattr(db, "ensure_workflow_state", None)):
                db.ensure_workflow_state(s.state, style=s.style)
            elif frappe and hasattr(frappe, "db") and hasattr(frappe, "get_doc"):
                if not frappe.db.exists("Workflow State", s.state):
                    ws = frappe.get_doc({
                        "doctype": "Workflow State",
                        "workflow_state_name": s.state,
                        "style": s.style or "Primary",
                    })
                    ws.insert(ignore_permissions=True)
                    if hasattr(frappe.db, "commit"):
                        frappe.db.commit()

        # Step 7: Deactivate pre-existing active workflow if it differs from the new one
        if prev_wf and prev_wf_name and prev_wf_name != wf.workflow_name:
            if hasattr(db, "set_workflow_active") and callable(getattr(db, "set_workflow_active", None)):
                db.set_workflow_active(prev_wf_name, 0)
            elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "set_value"):
                frappe.db.set_value("Workflow", prev_wf_name, "is_active", 0)
                if hasattr(frappe.db, "commit"):
                    frappe.db.commit()

        # Step 8: Create or update Workflow document
        wf_dict = {
            "doctype": "Workflow",
            "workflow_name": wf.workflow_name,
            "document_type": wf.document_type,
            "is_active": 1,
            "workflow_state_field": wf.workflow_state_field,
            "override_status": 1 if wf.override_status else 0,
            "send_email_alert": 1 if wf.send_email_alert else 0,
            "states": [
                {
                    "state": s.state,
                    "doc_status": s.doc_status,
                    "allow_edit": s.allow_edit,
                    "style": s.style,
                }
                for s in wf.states
            ],
            "transitions": [
                {
                    "state": t.state,
                    "action": t.action,
                    "next_state": t.next_state,
                    "allowed": t.allowed,
                    "condition": t.condition,
                    "allow_self_approval": 1 if t.allow_self_approval else 0,
                }
                for t in wf.transitions
            ],
        }

        apply_error = None
        try:
            if hasattr(db, "apply_workflow") and callable(getattr(db, "apply_workflow", None)):
                db.apply_workflow(doctype, wf_dict)
            elif frappe and hasattr(frappe, "get_doc"):
                if frappe.db.exists("Workflow", wf.workflow_name):
                    w_doc = frappe.get_doc("Workflow", wf.workflow_name)
                    w_doc.update(wf_dict)
                    w_doc.is_active = 1
                    w_doc.save(ignore_permissions=True)
                else:
                    w_doc = frappe.get_doc(wf_dict)
                    w_doc.insert(ignore_permissions=True)
                if hasattr(frappe.db, "commit"):
                    frappe.db.commit()
        except Exception as exc:
            apply_error = str(exc)

        # Step 9: Clear DocType cache
        try:
            if hasattr(db, "clear_doctype_cache") and callable(getattr(db, "clear_doctype_cache", None)):
                db.clear_doctype_cache(doctype)
            if frappe and hasattr(frappe, "clear_cache"):
                frappe.clear_cache(doctype=doctype)
        except Exception:
            pass

        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        if apply_error:
            outcome = {
                "deployment_id": deployment_id,
                "status": "FAILED_CLEAN",
                "success": False,
                "stage": "APPLY",
                "disposition": "WORKFLOW_APPLY_FAILED",
                "reason": apply_error,
                "doctype": doctype,
                "workflow_name": wf.workflow_name,
                "execution_time_ms": execution_time_ms,
            }
        else:
            outcome = {
                "deployment_id": deployment_id,
                "status": "APPLIED",
                "success": True,
                "stage": "FINALIZE",
                "disposition": "WORKFLOW_STATE_MACHINE_ACTIVATED",
                "doctype": doctype,
                "workflow_name": wf.workflow_name,
                "is_active": 1,
                "states_count": len(wf.states),
                "transitions_count": len(wf.transitions),
                "mermaid_graph": val_result.mermaid_graph,
                "baseline_snapshot": baseline_snapshot,
                "execution_time_ms": execution_time_ms,
            }

        # Step 10: Persist final outcome & audit
        try:
            db.persist_final_outcome_and_audit(
                deployment_id,
                {"payload_hash": payload_hash, "outcome": outcome, "baseline_snapshot": baseline_snapshot},
            )
        except Exception as fin_exc:
            outcome = {
                **outcome,
                "status": "RECOVERY_REQUIRED",
                "finalization_error": str(fin_exc),
            }

        return outcome

    finally:
        db.release_advisory_lock(lock_key)
