"""
EXRP Guarded Schema Deployment & Non-Destructive Snapshot Reconciler
Implements ADR-001 (Rev 2.3) Sections 6, 7, 8, and 9:
- Bounded, collision-resistant MariaDB GET_LOCK identifier (<= 64 chars) with 1 / 0 / NULL handling (§7.2)
- Immutable Idempotency Key + Canonical Payload Hash conflict detection (§7.1)
- Approved-Only DDL Plan Inspection Gate before synchronous execution (§6.1 & §6.2)
- 6-Stage Durable Deployment Sequence surviving MariaDB implicit commits (§8)
- Non-Destructive Exhaustive Snapshot Reconciliation (§9): Phase 1 NEVER auto-deletes orphaned metadata
  or drops physical columns; all uncertain or divergent states enter `RECOVERY_REQUIRED`.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Protocol


class IdempotencyConflictError(Exception):
    """Raised when an idempotency_key is reused with a different canonical request payload."""
    pass


@dataclass(frozen=True)
class ExhaustiveSnapshot:
    has_meta: bool
    has_col: bool
    definition_matches: bool = True
    indexes_unchanged: bool = True
    provenance_matches: bool = True
    unapproved_side_effects: bool = False
    revision_hash: str = ""


from .ddl_plan_gate import (
    DDLPlanInspection,
    inspect_frappe_ddl_plan,
    validate_ddl_plan,
)


class Rev23DeploymentAdapter(Protocol):
    """Protocol for Frappe v15 + MariaDB 10.11 deployment execution under ADR-001 Rev 2.3."""

    def acquire_advisory_lock(self, lock_key: str, wait_seconds: int) -> Optional[int]: ...
    def release_advisory_lock(self, lock_key: str) -> None: ...
    def is_target_in_recovery_required(self, site_id: str, doctype: str) -> bool: ...
    def get_existing_deployment_by_idempotency(self, site_id: str, idempotency_key: str) -> Optional[Dict[str, Any]]: ...
    def take_snapshot(self, doctype: str, fieldname: str, expected_deployment_id: str) -> ExhaustiveSnapshot: ...
    def inspect_ddl_plan(self, doctype: str, field_def: Dict[str, Any]) -> DDLPlanInspection: ...
    def persist_prepare_and_audit_intent(self, record: Dict[str, Any]) -> None: ...
    def persist_final_outcome_and_audit(self, deployment_id: str, outcome: Dict[str, Any]) -> None: ...
    def set_lock_wait_timeout(self, seconds: int) -> None: ...
    def apply_native_custom_field(self, deployment_id: str, doctype: str, field_def: Dict[str, Any]) -> None: ...
    def clear_doctype_cache(self, doctype: str) -> None: ...


def make_bounded_lock_key(site_id: str, doctype: str) -> str:
    """
    Maps (site_id, doctype) to a bounded, collision-resistant lock identifier <= 64 chars
    respecting MariaDB GET_LOCK limits and avoiding raw string concatenation (§7.2).
    """
    digest = hashlib.sha256(f"{site_id}\x00{doctype}".encode("utf-8")).hexdigest()[:48]
    return f"exrp:v1:{digest}"


def compute_canonical_payload_hash(site_id: str, doctype: str, field_def: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash of the canonical request payload (§7.1)."""
    canonical = json.dumps(
        {"site_id": site_id, "doctype": doctype, "field_def": field_def},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def execute_single_field_deployment(
    db: Rev23DeploymentAdapter,
    deployment_id: str,
    idempotency_key: str,
    site_id: str,
    doctype: str,
    base_revision_hash: str,
    field_def: Dict[str, Any],
    lock_wait_seconds: int = 3,
) -> Dict[str, Any]:
    """
    Executes the 6-Stage Durable Deployment Sequence defined in ADR-001 Rev 2.3 (§8 & §9).
    """
    fieldname = field_def["fieldname"]
    payload_hash = compute_canonical_payload_hash(site_id, doctype, field_def)
    lock_key = make_bounded_lock_key(site_id, doctype)

    # Stage 1: Acquire verified connection-scoped advisory lock (1 = acquired, 0 = timeout, None = error)
    lock_result = db.acquire_advisory_lock(lock_key, wait_seconds=5)
    if lock_result != 1:
        reason = "Lock wait timeout (0)" if lock_result == 0 else "Database lock error (NULL)"
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "stage": "ACQUIRE",
            "reason": f"Could not acquire MariaDB GET_LOCK ({reason})",
        }

    try:
        # Step 1.5: Check Idempotency Binding (§7.1)
        existing = db.get_existing_deployment_by_idempotency(site_id, idempotency_key)
        if existing is not None:
            if existing.get("payload_hash") != payload_hash:
                raise IdempotencyConflictError(
                    f"IDEMPOTENCY_CONFLICT: Key '{idempotency_key}' was already used with a different payload."
                )
            return existing["outcome"]

        # Block if target DocType already has an unresolved RECOVERY_REQUIRED deployment (§8.1)
        if db.is_target_in_recovery_required(site_id, doctype):
            return {
                "deployment_id": deployment_id,
                "status": "RECOVERY_REQUIRED",
                "stage": "INSPECT",
                "reason": f"Target '{doctype}' has an unresolved RECOVERY_REQUIRED state; deployments blocked.",
            }

        # Stage 2: Inspect Revision, Before-Snapshot, and Approved-Only DDL Plan (§6.1, §8)
        before = db.take_snapshot(doctype, fieldname, expected_deployment_id=deployment_id)

        if before.revision_hash != base_revision_hash:
            return {
                "deployment_id": deployment_id,
                "status": "REVISION_CONFLICT",
                "stage": "INSPECT",
                "reason": "DocType configuration revision changed externally before deployment.",
            }

        # Pre-existing partial or conflicting state check (§5.1, §9)
        if before.has_meta or before.has_col:
            status = "RECOVERY_REQUIRED" if (before.has_meta != before.has_col) else "REJECTED"
            return {
                "deployment_id": deployment_id,
                "status": status,
                "stage": "INSPECT",
                "reason": (
                    f"Pre-existing field or divergence on '{doctype}.{fieldname}' "
                    f"(has_meta={before.has_meta}, has_col={before.has_col})."
                ),
            }

        # Mandatory DDL Plan Safety Gate (§6.1 & §6.2)
        if hasattr(db, "inspect_ddl_plan") and callable(getattr(db, "inspect_ddl_plan", None)):
            ddl_plan = db.inspect_ddl_plan(doctype, field_def)
        else:
            existing_cols = None
            if hasattr(db, "get_table_columns_description") and callable(getattr(db, "get_table_columns_description", None)):
                existing_cols = db.get_table_columns_description(doctype)
            ddl_plan = inspect_frappe_ddl_plan(doctype, field_def, existing_columns_desc=existing_cols)

        # Enforce fail-closed gate validation on planned statements (§6.1 & §6.2)
        if ddl_plan.inspectable and ddl_plan.is_approved_additive_only:
            is_valid, validation_reason = validate_ddl_plan(ddl_plan.statements)
            if not is_valid:
                ddl_plan = DDLPlanInspection(
                    inspectable=True,
                    statements=ddl_plan.statements,
                    is_approved_additive_only=False,
                    rejection_reason=validation_reason,
                )

        if not ddl_plan.inspectable or not ddl_plan.is_approved_additive_only:
            return {
                "deployment_id": deployment_id,
                "status": "REJECTED",
                "stage": "INSPECT",
                "fallback_action": "QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT",
                "reason": ddl_plan.rejection_reason or "Unprovable or non-additive DDL plan from updatedb().",
            }

        # Stage 3: Prepare — Commit durable intent, payload hash, DDL plan evidence, and audit BEFORE DDL (§8, §10)
        try:
            db.persist_prepare_and_audit_intent({
                "deployment_id": deployment_id,
                "idempotency_key": idempotency_key,
                "payload_hash": payload_hash,
                "site_id": site_id,
                "doctype": doctype,
                "fieldname": fieldname,
                "base_revision_hash": base_revision_hash,
                "ddl_plan_statements": ddl_plan.statements,
                "status": "PREPARED",
            })
        except Exception as prep_exc:
            # Fail closed before any schema mutation is attempted
            return {
                "deployment_id": deployment_id,
                "status": "FAILED_CLEAN",
                "stage": "PREPARE",
                "reason": f"Fail-closed: Could not persist deployment/audit intent: {prep_exc}",
            }

        # Stage 4: Apply Native Frappe Configuration Operation (§8)
        db.set_lock_wait_timeout(lock_wait_seconds)
        apply_error: Optional[str] = None
        try:
            db.apply_native_custom_field(deployment_id, doctype, field_def)
        except Exception as exc:
            # Do NOT assume rollback on exception; proceed to Stage 5 Reconciliation
            apply_error = str(exc)

        # Stage 5: Reconcile Exhaustive Snapshot (§9 — Non-Destructive by Default)
        after = db.take_snapshot(doctype, fieldname, expected_deployment_id=deployment_id)
        outcome = reconcile_exhaustive_snapshot(
            deployment_id=deployment_id,
            doctype=doctype,
            fieldname=fieldname,
            before=before,
            after=after,
            apply_error=apply_error,
        )

        if outcome["status"] == "APPLIED":
            db.clear_doctype_cache(doctype)

        # Stage 6: Finalize State & Audit Event (§8)
        try:
            db.persist_final_outcome_and_audit(
                deployment_id,
                {"payload_hash": payload_hash, "outcome": outcome},
            )
        except Exception as fin_exc:
            # If finalization fails after DDL, preserve RECOVERY_REQUIRED / unfinalized journal warning
            outcome = {
                **outcome,
                "status": "RECOVERY_REQUIRED",
                "finalization_error": str(fin_exc),
            }

        return outcome
    finally:
        db.release_advisory_lock(lock_key)


def reconcile_exhaustive_snapshot(
    deployment_id: str,
    doctype: str,
    fieldname: str,
    before: ExhaustiveSnapshot,
    after: ExhaustiveSnapshot,
    apply_error: Optional[str],
) -> Dict[str, Any]:
    """
    Implements the exact 6-row Non-Destructive Reconciliation Table from ADR-001 Rev 2.3 (§9).
    Phase 1 NEVER auto-deletes orphaned Custom Field metadata or drops physical columns.
    """
    # Row 1: Absent | Absent | Baseline unchanged, no partial side effects -> FAILED_CLEAN
    if not after.has_meta and not after.has_col:
        if after.unapproved_side_effects or not after.indexes_unchanged:
            return {
                "deployment_id": deployment_id,
                "status": "RECOVERY_REQUIRED",
                "disposition": "UNAPPROVED_SIDE_EFFECT_WITHOUT_FIELD",
                "error": apply_error,
            }
        return {
            "deployment_id": deployment_id,
            "status": "FAILED_CLEAN",
            "disposition": "ABSENT_ABSENT_BASELINE_VERIFIED",
            "error": apply_error,
        }

    # Row 4: Present | Absent | Orphan metadata -> RECOVERY_REQUIRED by default (No auto-delete in Phase 1)
    if after.has_meta and not after.has_col:
        return {
            "deployment_id": deployment_id,
            "status": "RECOVERY_REQUIRED",
            "disposition": "ORPHAN_METADATA_NON_DESTRUCTIVE_HOLD",
            "error": apply_error,
        }

    # Row 5: Absent | Present | Orphan physical column -> RECOVERY_REQUIRED
    if not after.has_meta and after.has_col:
        return {
            "deployment_id": deployment_id,
            "status": "RECOVERY_REQUIRED",
            "disposition": "ORPHAN_PHYSICAL_COLUMN",
            "error": apply_error,
        }

    # Both Present | Present (Rows 2, 3, 6):
    # Row 3: Definition mismatch or unexpected side effect / index modification -> RECOVERY_REQUIRED
    if not after.definition_matches or not after.indexes_unchanged or after.unapproved_side_effects:
        return {
            "deployment_id": deployment_id,
            "status": "RECOVERY_REQUIRED",
            "disposition": "DEFINITION_MISMATCH_OR_UNAPPROVED_SIDE_EFFECT",
            "error": apply_error,
        }

    # Row 6: Definition matches, but provenance or concurrent external revision is uncertain -> RECOVERY_REQUIRED
    if not after.provenance_matches:
        return {
            "deployment_id": deployment_id,
            "status": "RECOVERY_REQUIRED",
            "disposition": "UNCERTAIN_PROVENANCE_OR_CONCURRENT_REVISION",
            "error": apply_error,
        }

    # Row 2: Present | Present | Expected definition, indexes, and provenance; no unapproved effects -> APPLIED
    return {
        "deployment_id": deployment_id,
        "status": "APPLIED",
        "disposition": "VERIFIED_CONSISTENT",
        "doctype": doctype,
        "fieldname": fieldname,
        "post_apply_warning": apply_error,
    }
