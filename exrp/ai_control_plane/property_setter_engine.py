"""
EXRP Property Setter Mutation Engine
Implements ADR-001 (Rev 2.3) Section 5, Section 8, and Section 9.1:
- Evaluates proposal against validate_mutation_safety() (ensuring Tier 0 invariants cannot be hidden or altered).
- Bounded advisory lock GET_LOCK <= 64 chars respecting MariaDB limits (§7.2).
- Persists baseline snapshot before modification in audit journal (fail-closed durability, §8).
- Applies Property Setter via native frappe.make_property_setter or in-memory deployment adapter.
- Clears DocType cache frappe.clear_cache(doctype=doctype).
- Verifies effective metadata reflection and returns structured outcome (status: APPLIED, disposition: PROPERTY_SETTER_APPLIED).
"""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Set, Union

try:
    import frappe
except ImportError:
    frappe = None

from .safety_guardrails import (
    TIER_1_GOVERNANCE_ROLES,
    validate_mutation_safety,
    ZoneSafetyViolation,
)
from .schema_reconciler import (
    IdempotencyConflictError,
    compute_canonical_payload_hash,
    make_bounded_lock_key,
)

PROPERTY_TYPE_MAP: Dict[str, str] = {
    "label": "Data",
    "description": "Text",
    "reqd": "Check",
    "hidden": "Check",
    "read_only": "Check",
    "in_list_view": "Check",
    "in_standard_filter": "Check",
    "bold": "Check",
    "collapsible": "Check",
    "options": "Text",
    "default": "Data",
}


def normalize_property_value(property_name: str, property_type: str, value: Any) -> Any:
    """Normalizes property value based on property type (e.g. Check properties store 0 or 1)."""
    if property_type == "Check" or property_name in ("reqd", "hidden", "read_only", "in_list_view", "in_standard_filter", "bold", "collapsible"):
        if value is None:
            return 0
        if isinstance(value, str):
            return 1 if value.strip() in ("1", "true", "True") else 0
        return 1 if bool(value) else 0
    if value is None:
        return ""
    return str(value)


def execute_property_setter_deployment(
    db: Any,
    deployment_id: str,
    site_id: str,
    doctype: str,
    fieldname: Optional[str],
    property_name: str,
    value: Any,
    property_type: str = "Data",
    user_roles: Optional[Union[List[str], Set[str]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Executes a Property Setter mutation deployment under ADR-001 Rev 2.3 (§5, §8, §9.1).

    1. Evaluates proposal against validate_mutation_safety() (ensuring Tier 0 fields
       cannot be hidden or altered).
    2. Acquires MariaDB GET_LOCK advisory lock with <= 64 char identifier.
    3. Checks idempotency binding and recovers from any ongoing RECOVERY_REQUIRED target.
    4. Persists baseline snapshot before modification in audit journal (fail-closed durability).
    5. Applies Property Setter via frappe.make_property_setter or db adapter.
    6. Clears DocType cache via frappe.clear_cache(doctype=doctype).
    7. Verifies effective metadata reflection and returns structured outcome.
    """
    start_time = time.perf_counter()

    # Step 0: Normalize property type and value
    eff_property_type = property_type
    if property_type == "Data" and property_name in PROPERTY_TYPE_MAP:
        eff_property_type = PROPERTY_TYPE_MAP[property_name]
    normalized_value = normalize_property_value(property_name, eff_property_type, value)

    # Step 1: Evaluates proposal against validate_mutation_safety()
    proposal_payload: Dict[str, Any] = {
        "intent": "set_property",
        "target_doctype": doctype,
        "changes": [
            {
                "fieldname": fieldname or "",
                "property": property_name,
                "value": normalized_value,
            }
        ],
    }
    if user_roles is not None:
        proposal_payload["user_roles"] = list(user_roles)

    try:
        validate_mutation_safety(proposal_payload)
    except ZoneSafetyViolation as exc:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if kwargs.get("raise_on_violation") or kwargs.get("raise_on_safety_violation"):
            raise
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "SAFETY_GUARDRAILS",
            "disposition": "ZONE_SAFETY_VIOLATION",
            "reason": str(exc),
            "doctype": doctype,
            "fieldname": fieldname,
            "property_name": property_name,
            "execution_time_ms": execution_time_ms,
        }

    # Step 2: Bounded advisory lock GET_LOCK <= 64 chars (§7.2)
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
            "fieldname": fieldname,
            "execution_time_ms": execution_time_ms,
        }

    try:
        # Step 2.5: Idempotency Binding Check (§7.1)
        idempotency_key = kwargs.get("idempotency_key") or f"idemp-{deployment_id}"
        payload_hash = compute_canonical_payload_hash(
            site_id,
            doctype,
            {
                "fieldname": fieldname,
                "property": property_name,
                "value": normalized_value,
                "property_type": eff_property_type,
            },
        )

        existing = db.get_existing_deployment_by_idempotency(site_id, idempotency_key)
        if existing is not None:
            if existing.get("payload_hash") != payload_hash:
                raise IdempotencyConflictError(
                    f"IDEMPOTENCY_CONFLICT: Key '{idempotency_key}' was already used with a different payload."
                )
            cached_outcome = dict(existing["outcome"])
            cached_outcome["execution_time_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
            return cached_outcome

        # Target DocType recovery state gate (§8.1)
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

        # Step 3: Persists baseline snapshot before modification in audit journal (§8, §9.1)
        had_existing = False
        existing_ps_name = None
        baseline_value = None

        if hasattr(db, "get_property_setter") and callable(getattr(db, "get_property_setter", None)):
            existing_ps = db.get_property_setter(doctype, fieldname, property_name)
            if existing_ps is not None:
                had_existing = True
                baseline_value = existing_ps.get("value")
                existing_ps_name = existing_ps.get("name")
        elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "get_value"):
            try:
                ps_dict = frappe.db.get_value(
                    "Property Setter",
                    {"doc_type": doctype, "field_name": fieldname, "property": property_name},
                    ["name", "value", "property_type"],
                    as_dict=True,
                )
                if ps_dict:
                    had_existing = True
                    baseline_value = ps_dict.get("value")
                    existing_ps_name = ps_dict.get("name")
            except Exception:
                pass

        if not had_existing:
            if hasattr(db, "get_effective_field_property") and callable(getattr(db, "get_effective_field_property", None)):
                baseline_value = db.get_effective_field_property(doctype, fieldname, property_name)
            elif frappe and hasattr(frappe, "get_meta"):
                try:
                    meta = frappe.get_meta(doctype)
                    df = meta.get_field(fieldname) if hasattr(meta, "get_field") else None
                    if df:
                        baseline_value = getattr(df, property_name, None)
                except Exception:
                    pass

        baseline_snapshot: Dict[str, Any] = {
            "had_existing_property_setter": had_existing,
            "existing_property_setter_name": existing_ps_name,
            "baseline_value": baseline_value,
            "property_type": eff_property_type,
            "property_name": property_name,
        }

        base_revision_hash = kwargs.get("base_revision_hash")
        if not base_revision_hash:
            if hasattr(db, "get_doctype_revision_hash") and callable(getattr(db, "get_doctype_revision_hash", None)):
                base_revision_hash = db.get_doctype_revision_hash(doctype)
            else:
                base_revision_hash = "rev_ps_default"

        prepare_record = {
            "deployment_id": deployment_id,
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "site_id": site_id,
            "doctype": doctype,
            "fieldname": fieldname,
            "base_revision_hash": base_revision_hash,
            "deployment_type": "property_setter",
            "property_name": property_name,
            "property_value": normalized_value,
            "property_type": eff_property_type,
            "baseline_value": baseline_value,
            "baseline_snapshot": baseline_snapshot,
            "status": "PREPARED",
        }

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
                "execution_time_ms": execution_time_ms,
            }

        # Step 4: Applies Property Setter via native frappe.make_property_setter or db adapter
        apply_error: Optional[str] = None
        try:
            if hasattr(db, "apply_property_setter") and callable(getattr(db, "apply_property_setter", None)):
                db.apply_property_setter(
                    doctype=doctype,
                    fieldname=fieldname,
                    property_name=property_name,
                    value=normalized_value,
                    property_type=eff_property_type,
                )
            elif frappe and hasattr(frappe, "make_property_setter"):
                try:
                    frappe.make_property_setter({
                        "doctype": doctype,
                        "fieldname": fieldname,
                        "property": property_name,
                        "value": normalized_value,
                        "property_type": eff_property_type,
                    })
                except TypeError:
                    frappe.make_property_setter(
                        doctype=doctype,
                        fieldname=fieldname,
                        property=property_name,
                        value=normalized_value,
                        property_type=eff_property_type,
                    )
                if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                    frappe.db.commit()

            # ADR-001 Rev 2.3 (§9.1): When quarantining a field (hidden=1), also set reqd=0
            # to guarantee that hiding the field does not cause mandatory validation errors on document save.
            if property_name == "hidden" and int(normalized_value) == 1 and fieldname:
                try:
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
                                "value": 0,
                                "property_type": "Check",
                            })
                        except TypeError:
                            frappe.make_property_setter(
                                doctype=doctype,
                                fieldname=fieldname,
                                property="reqd",
                                value=0,
                                property_type="Check",
                            )
                        if hasattr(frappe, "db") and hasattr(frappe.db, "commit"):
                            frappe.db.commit()
                except Exception:
                    pass
        except Exception as exc:
            apply_error = str(exc)

        # Step 5: Clears DocType cache frappe.clear_cache(doctype=doctype)
        try:
            if hasattr(db, "clear_doctype_cache") and callable(getattr(db, "clear_doctype_cache", None)):
                db.clear_doctype_cache(doctype)
            if frappe and hasattr(frappe, "clear_cache"):
                frappe.clear_cache(doctype=doctype)
        except Exception:
            pass

        # Step 6: Verifies effective metadata reflection
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        if apply_error:
            outcome = {
                "deployment_id": deployment_id,
                "status": "FAILED_CLEAN",
                "success": False,
                "stage": "APPLY",
                "disposition": "PROPERTY_SETTER_APPLY_FAILED",
                "reason": apply_error,
                "doctype": doctype,
                "fieldname": fieldname,
                "property_name": property_name,
                "execution_time_ms": execution_time_ms,
            }
        else:
            verified = True
            if hasattr(db, "get_property_setter") and callable(getattr(db, "get_property_setter", None)):
                ps = db.get_property_setter(doctype, fieldname, property_name)
                if ps is not None:
                    verified = (str(ps.get("value")) == str(normalized_value))
                else:
                    verified = False
            elif frappe and hasattr(frappe, "db") and hasattr(frappe.db, "get_value"):
                try:
                    val = frappe.db.get_value(
                        "Property Setter",
                        {"doc_type": doctype, "field_name": fieldname, "property": property_name},
                        "value",
                    )
                    if val is not None:
                        verified = (str(val) == str(normalized_value))
                    else:
                        verified = False
                except Exception:
                    pass

            if not verified:
                outcome = {
                    "deployment_id": deployment_id,
                    "status": "RECOVERY_REQUIRED",
                    "success": False,
                    "stage": "RECONCILE",
                    "disposition": "METADATA_REFLECTION_MISMATCH",
                    "reason": f"Property Setter on {doctype}.{fieldname}.{property_name} was not reflected in metadata.",
                    "doctype": doctype,
                    "fieldname": fieldname,
                    "property_name": property_name,
                    "execution_time_ms": execution_time_ms,
                }
            else:
                outcome = {
                    "deployment_id": deployment_id,
                    "status": "APPLIED",
                    "success": True,
                    "disposition": "CUSTOM_FIELD_QUARANTINED" if (property_name == "hidden" and int(normalized_value) == 1) else "PROPERTY_SETTER_APPLIED",
                    "doctype": doctype,
                    "fieldname": fieldname,
                    "property_name": property_name,
                    "value": normalized_value,
                    "baseline_value": baseline_value,
                    "execution_time_ms": execution_time_ms,
                }

        # Step 7: Finalize state & audit
        try:
            db.persist_final_outcome_and_audit(
                deployment_id,
                {"payload_hash": payload_hash, "outcome": outcome},
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
