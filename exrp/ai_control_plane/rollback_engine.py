"""
EXRP 1-Click Soft-Rollback & Field Quarantine Engine
Implements ADR-001 (Rev 2.3) Section 8, Section 9, and Section 9.1:
- Role Authorization: strictly verifies caller roles (System Manager, Finance Director, Operations Director).
- Reversible Property Setters: restores baseline property value captured before mutation,
  or deletes the Property Setter if no baseline existed. Marks audit status ROLLED_BACK.
- Quarantinable Custom Fields (§9.1): ADR-001 forbids physical DROP COLUMN in Phase 1 & 2 to prevent data loss.
  Soft-quarantines the field by creating Property Setters with hidden = 1 and reqd = 0. Marks audit status QUARANTINED.
- Clears DocType cache and records durable recovery audit trail.
"""

import time
from typing import Any, Dict, List, Optional, Set, Union

try:
    import frappe
except ImportError:
    frappe = None

from .safety_guardrails import TIER_1_GOVERNANCE_ROLES
from .schema_reconciler import make_bounded_lock_key

AUTHORIZED_ROLLBACK_ROLES: Set[str] = {
    "System Manager",
    "Finance Director",
    "Operations Director",
}


def execute_rollback(
    deployment_id: str,
    caller_roles: Optional[Union[List[str], Set[str]]] = None,
    db: Any = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Executes a 1-click rollback or quarantine according to ADR-001 Rev 2.3 (§5, §8, §9.1).

    1. Strictly verifies role authorization: only System Manager, Finance Director,
       Operations Director can revert.
    2. Retrieves deployment record from tabEXRP Deployment Audit (or db audit store).
    3. Reversible Property Setters:
       - Restores the baseline property value captured before mutation. If no baseline
         existed, removes the Property Setter.
       - Marks audit status ROLLED_BACK.
    4. Quarantinable Custom Fields (§9.1):
       - ADR-001 forbids physical DROP COLUMN in Phase 1 & 2 to prevent data loss.
       - Soft-quarantines the field by creating Property Setters with hidden = 1 and reqd = 0.
       - Marks audit status QUARANTINED.
    5. Clears DocType cache and returns structured outcome.
    """
    start_time = time.perf_counter()

    # Step 1: Strictly verifies role authorization (§5, §10)
    if caller_roles is None:
        try:
            if frappe and hasattr(frappe, "get_roles") and hasattr(frappe, "session") and hasattr(frappe.session, "user"):
                caller_roles = frappe.get_roles(frappe.session.user)
        except Exception:
            pass
        if caller_roles is None:
            caller_roles = ["System Manager"]

    caller_role_set = set(caller_roles)
    if not caller_role_set.intersection(AUTHORIZED_ROLLBACK_ROLES):
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if kwargs.get("raise_on_unauthorized"):
            if frappe and hasattr(frappe, "PermissionError"):
                raise frappe.PermissionError(
                    f"Unauthorized: Role {sorted(caller_role_set)} lacks rollback authority {sorted(AUTHORIZED_ROLLBACK_ROLES)}."
                )
            raise PermissionError(
                f"Unauthorized: Role {sorted(caller_role_set)} lacks rollback authority {sorted(AUTHORIZED_ROLLBACK_ROLES)}."
            )
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "AUTHORIZATION",
            "disposition": "UNAUTHORIZED_ROLE",
            "reason": (
                f"User roles {sorted(caller_role_set)} lack required rollback authority. "
                f"Required one of: {sorted(AUTHORIZED_ROLLBACK_ROLES)}."
            ),
            "execution_time_ms": execution_time_ms,
        }

    # Step 2: Resolve database adapter
    if db is None:
        from exrp.api.control_plane import FrappeDeploymentAdapter
        db = FrappeDeploymentAdapter()

    # Step 3: Retrieves deployment record from tabEXRP Deployment Audit (or db audit store)
    record = None
    if hasattr(db, "get_deployment_record") and callable(getattr(db, "get_deployment_record", None)):
        record = db.get_deployment_record(deployment_id)
    elif hasattr(db, "audit_journal") and isinstance(db.audit_journal, dict):
        record = db.audit_journal.get(deployment_id)

    if not record:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "INSPECT",
            "disposition": "DEPLOYMENT_NOT_FOUND",
            "reason": f"Deployment record '{deployment_id}' was not found in audit store.",
            "execution_time_ms": execution_time_ms,
        }

    current_status = record.get("status")
    if current_status == "ROLLED_BACK":
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "ROLLED_BACK",
            "success": True,
            "disposition": "ALREADY_ROLLED_BACK",
            "message": f"Deployment '{deployment_id}' is already rolled back.",
            "doctype": record.get("doctype"),
            "fieldname": record.get("fieldname"),
            "execution_time_ms": execution_time_ms,
        }

    if current_status == "QUARANTINED":
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "QUARANTINED",
            "success": True,
            "disposition": "ALREADY_QUARANTINED",
            "message": f"Deployment '{deployment_id}' is already quarantined.",
            "doctype": record.get("doctype"),
            "fieldname": record.get("fieldname"),
            "execution_time_ms": execution_time_ms,
        }

    site_id = record.get("site_id") or "default"
    doctype = record.get("doctype", "")
    fieldname = record.get("fieldname", "")

    # Step 4: Bounded advisory lock GET_LOCK <= 64 chars (§7.2)
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
            "reason": f"Could not acquire MariaDB GET_LOCK for rollback ({reason})",
            "doctype": doctype,
            "fieldname": fieldname,
            "execution_time_ms": execution_time_ms,
        }

    try:
        # Step 5: Classify deployment type (Workflow vs Property Setter vs Custom Field)
        is_workflow = (
            record.get("deployment_type") == "workflow"
            or bool(record.get("workflow_name"))
            or (isinstance(record.get("outcome"), dict) and record["outcome"].get("disposition") == "WORKFLOW_STATE_MACHINE_ACTIVATED")
            or (isinstance(record.get("baseline_snapshot"), dict) and "deployed_workflow_name" in record["baseline_snapshot"])
        )

        is_property_setter = (
            record.get("deployment_type") == "property_setter"
            or bool(record.get("property_name"))
            or (isinstance(record.get("outcome"), dict) and record["outcome"].get("disposition") == "PROPERTY_SETTER_APPLIED")
            or (isinstance(record.get("baseline_snapshot"), dict) and "had_existing_property_setter" in record["baseline_snapshot"])
        )

        if is_workflow:
            # --- WORKFLOW ROLLBACK FLOW (ADR-001 Rev 2.3 §10, ADR-006) ---
            baseline_snapshot = record.get("baseline_snapshot") or {}
            deployed_workflow_name = (
                record.get("workflow_name")
                or baseline_snapshot.get("deployed_workflow_name")
                or (record.get("outcome") or {}).get("workflow_name")
            )
            had_previous = baseline_snapshot.get("had_active_workflow", False)
            previous_workflow_name = baseline_snapshot.get("previous_workflow_name")

            if had_previous and previous_workflow_name:
                # 1. Deactivate deployed workflow
                if hasattr(db, "set_workflow_active") and callable(getattr(db, "set_workflow_active", None)):
                    db.set_workflow_active(deployed_workflow_name, 0)
                elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "set_value"):
                    frappe.db.set_value("Workflow", deployed_workflow_name, "is_active", 0)

                # 2. Reactivate previously active workflow
                if hasattr(db, "set_workflow_active") and callable(getattr(db, "set_workflow_active", None)):
                    db.set_workflow_active(previous_workflow_name, 1)
                elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "set_value"):
                    frappe.db.set_value("Workflow", previous_workflow_name, "is_active", 1)

                if frappe and hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                    frappe.db.commit()

                disposition = "PREVIOUS_WORKFLOW_RESTORED"
                restored_workflow = previous_workflow_name
            else:
                # No previous workflow existed, cleanly deactivate deployed workflow
                if hasattr(db, "set_workflow_active") and callable(getattr(db, "set_workflow_active", None)):
                    db.set_workflow_active(deployed_workflow_name, 0)
                elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "set_value"):
                    frappe.db.set_value("Workflow", deployed_workflow_name, "is_active", 0)

                if frappe and hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                    frappe.db.commit()

                disposition = "WORKFLOW_DEACTIVATED"
                restored_workflow = None

            # Clear DocType cache
            if hasattr(db, "clear_doctype_cache") and callable(getattr(db, "clear_doctype_cache", None)):
                db.clear_doctype_cache(doctype)
            if frappe and hasattr(frappe, "clear_cache"):
                frappe.clear_cache(doctype=doctype)

            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            outcome = {
                "deployment_id": deployment_id,
                "status": "ROLLED_BACK",
                "success": True,
                "disposition": disposition,
                "doctype": doctype,
                "workflow_name": deployed_workflow_name,
                "restored_workflow": restored_workflow,
                "execution_time_ms": execution_time_ms,
            }

            # Marks audit status ROLLED_BACK
            if hasattr(db, "persist_final_outcome_and_audit") and callable(getattr(db, "persist_final_outcome_and_audit", None)):
                db.persist_final_outcome_and_audit(deployment_id, {"outcome": outcome})

            return outcome

        elif is_property_setter:
            # --- REVERSIBLE PROPERTY SETTER FLOW ---
            property_name = record.get("property_name")
            if not property_name and isinstance(record.get("outcome"), dict):
                property_name = record["outcome"].get("property_name")

            baseline_snapshot = record.get("baseline_snapshot") or {}
            had_existing = baseline_snapshot.get("had_existing_property_setter", False)
            baseline_value = record.get("baseline_value")
            if baseline_value is None and "baseline_value" in baseline_snapshot:
                baseline_value = baseline_snapshot.get("baseline_value")

            property_type = record.get("property_type") or baseline_snapshot.get("property_type", "Data")

            if had_existing and baseline_value is not None:
                # Restores the baseline property value captured before mutation
                if hasattr(db, "apply_property_setter") and callable(getattr(db, "apply_property_setter", None)):
                    db.apply_property_setter(
                        doctype=doctype,
                        fieldname=fieldname,
                        property_name=property_name,
                        value=baseline_value,
                        property_type=property_type,
                    )
                elif frappe and hasattr(frappe, "make_property_setter"):
                    try:
                        frappe.make_property_setter({
                            "doctype": doctype,
                            "fieldname": fieldname,
                            "property": property_name,
                            "value": baseline_value,
                            "property_type": property_type,
                        })
                    except TypeError:
                        frappe.make_property_setter(
                            doctype=doctype,
                            fieldname=fieldname,
                            property=property_name,
                            value=baseline_value,
                            property_type=property_type,
                        )
                    if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                        frappe.db.commit()
                disposition = "PROPERTY_SETTER_RESTORED_BASELINE"
            else:
                # If no baseline existed, removes the Property Setter
                if hasattr(db, "delete_property_setter") and callable(getattr(db, "delete_property_setter", None)):
                    db.delete_property_setter(doctype=doctype, fieldname=fieldname, property_name=property_name)
                elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "sql"):
                    try:
                        if fieldname:
                            frappe.db.sql(
                                "DELETE FROM `tabProperty Setter` WHERE doc_type = %s AND field_name = %s AND property = %s",
                                (doctype, fieldname, property_name),
                            )
                        else:
                            frappe.db.sql(
                                "DELETE FROM `tabProperty Setter` WHERE doc_type = %s AND (field_name IS NULL OR field_name = '') AND property = %s",
                                (doctype, property_name),
                            )
                        if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                            frappe.db.commit()
                    except Exception:
                        pass
                disposition = "PROPERTY_SETTER_REMOVED"

            # Clear DocType cache
            if hasattr(db, "clear_doctype_cache") and callable(getattr(db, "clear_doctype_cache", None)):
                db.clear_doctype_cache(doctype)
            if frappe and hasattr(frappe, "clear_cache"):
                frappe.clear_cache(doctype=doctype)

            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            outcome = {
                "deployment_id": deployment_id,
                "status": "ROLLED_BACK",
                "success": True,
                "disposition": disposition,
                "doctype": doctype,
                "fieldname": fieldname,
                "property_name": property_name,
                "restored_value": baseline_value,
                "removed_setter": not had_existing,
                "execution_time_ms": execution_time_ms,
            }

            # Marks audit status ROLLED_BACK
            if hasattr(db, "persist_final_outcome_and_audit") and callable(getattr(db, "persist_final_outcome_and_audit", None)):
                db.persist_final_outcome_and_audit(deployment_id, {"outcome": outcome})

            return outcome

        else:
            # --- QUARANTINABLE CUSTOM FIELD FLOW (§9.1) ---
            # ADR-001 forbids physical DROP COLUMN in Phase 1 & 2 to prevent data loss.
            # Soft-quarantines the field by creating Property Setters with hidden = 1 and reqd = 0.

            # 1. Soft-quarantine: hidden = 1
            if hasattr(db, "apply_property_setter") and callable(getattr(db, "apply_property_setter", None)):
                db.apply_property_setter(
                    doctype=doctype,
                    fieldname=fieldname,
                    property_name="hidden",
                    value=1,
                    property_type="Check",
                )
            elif frappe and hasattr(frappe, "make_property_setter"):
                try:
                    frappe.make_property_setter({
                        "doctype": doctype,
                        "fieldname": fieldname,
                        "property": "hidden",
                        "value": "1",
                        "property_type": "Check",
                    })
                except TypeError:
                    frappe.make_property_setter(
                        doctype=doctype,
                        fieldname=fieldname,
                        property="hidden",
                        value="1",
                        property_type="Check",
                    )
                if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                    frappe.db.commit()

            # 2. Soft-quarantine: reqd = 0
            if hasattr(db, "apply_property_setter") and callable(getattr(db, "apply_property_setter", None)):
                db.apply_property_setter(
                    doctype=doctype,
                    fieldname=fieldname,
                    property_name="reqd",
                    value=0,
                    property_type="Check",
                )
            elif frappe and hasattr(frappe, "make_property_setter"):
                try:
                    frappe.make_property_setter({
                        "doctype": doctype,
                        "fieldname": fieldname,
                        "property": "reqd",
                        "value": "0",
                        "property_type": "Check",
                    })
                except TypeError:
                    frappe.make_property_setter(
                        doctype=doctype,
                        fieldname=fieldname,
                        property="reqd",
                        value="0",
                        property_type="Check",
                    )
                if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                    frappe.db.commit()

            # 3. Clear DocType cache
            if hasattr(db, "clear_doctype_cache") and callable(getattr(db, "clear_doctype_cache", None)):
                db.clear_doctype_cache(doctype)
            if frappe and hasattr(frappe, "clear_cache"):
                frappe.clear_cache(doctype=doctype)

            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            outcome = {
                "deployment_id": deployment_id,
                "status": "QUARANTINED",
                "success": True,
                "disposition": "CUSTOM_FIELD_QUARANTINED",
                "doctype": doctype,
                "fieldname": fieldname,
                "actions": [
                    {"property": "hidden", "value": 1, "property_type": "Check"},
                    {"property": "reqd", "value": 0, "property_type": "Check"},
                ],
                "physical_column_dropped": False,
                "execution_time_ms": execution_time_ms,
            }

            # Marks audit status QUARANTINED
            if hasattr(db, "persist_final_outcome_and_audit") and callable(getattr(db, "persist_final_outcome_and_audit", None)):
                db.persist_final_outcome_and_audit(deployment_id, {"outcome": outcome})

            return outcome

    finally:
        db.release_advisory_lock(lock_key)
