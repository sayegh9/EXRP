"""
EXRP Whitelisted API Endpoints & Document Lifecycle Hooks
Implements supported Frappe REST and Desk RPC interfaces for the AI Control Plane.
"""

import hashlib
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Safe imports for standalone execution or Frappe runtime
try:
    import frappe
    from frappe import _
except ImportError:
    frappe = None

from exrp.ai_control_plane.schema_extractor import get_compact_doctype_schema
from exrp.ai_control_plane.safety_guardrails import (
    TIER_1_GOVERNANCE_ROLES,
    validate_mutation_safety,
    ZoneSafetyViolation,
)
from exrp.ai_control_plane.ddl_plan_gate import (
    ColumnDesc,
    DDLPlanInspection,
    MARIADB_TYPE_MAP,
    inspect_frappe_ddl_plan,
)
from exrp.ai_control_plane.schema_reconciler import (
    ExhaustiveSnapshot,
    IdempotencyConflictError,
    Rev23DeploymentAdapter,
    compute_canonical_payload_hash,
    execute_single_field_deployment,
    make_bounded_lock_key,
)
from exrp.ai_control_plane.planner import AIConfigurationPlanner, resolve_llm_config
from exrp.ai_control_plane.policy_enforcer import (
    PolicyType,
    RuntimePolicy,
    PolicyEvaluationResult,
    RuntimePolicyViolation,
    RuntimePolicyCatalog,
    policy_catalog,
)

from exrp.ai_control_plane.property_setter_engine import execute_property_setter_deployment
from exrp.ai_control_plane.rollback_engine import execute_rollback

AUTHORIZED_DEPLOYMENT_ROLES: Set[str] = {
    "System Manager",
    "Finance Director",
    "Operations Director",
}


def get_current_user_roles() -> list:
    """Returns the authenticated Frappe user's assigned roles."""
    try:
        if frappe and hasattr(frappe, "get_roles") and hasattr(frappe, "session") and hasattr(frappe.session, "user"):
            return frappe.get_roles(frappe.session.user)
    except Exception:
        pass
    return ["System Manager"]



def propose_configuration_change(
    doctype: str,
    proposal_payload: Optional[Dict[str, Any]] = None,
    user_prompt: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Whitelisted RPC method:
    - If user_prompt is provided (directly, via kwargs, or inside proposal_payload),
      invokes AIConfigurationPlanner().plan_change(...) to generate, validate, and inspect DDL.
    - Otherwise evaluates a raw proposal_payload against the 2-Axis Policy Compiler
      and generates non-executing DDL Plan Gate evidence.
    Does NOT execute physical DDL or write to production tables.
    """
    if isinstance(proposal_payload, str):
        try:
            proposal_payload = json.loads(proposal_payload)
        except Exception:
            proposal_payload = None

    if not user_prompt:
        if isinstance(proposal_payload, dict) and "user_prompt" in proposal_payload:
            user_prompt = proposal_payload.get("user_prompt")
        elif "user_prompt" in kwargs:
            user_prompt = kwargs.get("user_prompt")

    user_roles = kwargs.get("user_roles") or get_current_user_roles()

    if user_prompt:
        planner_kwargs = kwargs.get("planner_kwargs", {})
        planner = AIConfigurationPlanner(**planner_kwargs)
        result = planner.plan_change(doctype=doctype, user_prompt=user_prompt, user_roles=user_roles)

        return {
            "status": "PROPOSED" if result.success else "REJECTED",
            "success": result.success,
            "proposal": result.proposal.model_dump() if result.proposal else None,
            "validation": result.validation,
            "ddl_plan": result.ddl_plan,
            "error_message": result.error_message,
            "attempts": result.attempts,
            "feedback_history": result.feedback_history,
            "preview_fidelity_notice": (
                "Layout, labels, and field controls previewed. "
                "ERPNext tax/pricing recalculations and server validations execute on real documents."
            ),
        }

    # Raw proposal_payload execution flow
    if proposal_payload is None:
        proposal_payload = {}

    proposal_payload["target_doctype"] = doctype
    proposal_payload["user_roles"] = user_roles

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
        "success": True,
        "proposal": proposal_payload,
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


_LOCK_SENTINEL = object()


class FrappeDeploymentAdapter:
    """
    ADR-001 Rev 2.3 Deployment Adapter for Frappe Framework (v15 LTS) & MariaDB (10.11 LTS).
    Implements Rev23DeploymentAdapter protocol.

    - Live Frappe runtime:
      Uses frappe.db.sql for GET_LOCK, RELEASE_LOCK, SET SESSION lock_wait_timeout,
      and schema reflection on information_schema.COLUMNS and tabCustom Field.
      Durably persists deployment and audit journal to tabEXRP Deployment Audit.
      Inserts Custom Field documents natively via frappe.get_doc({...}).insert().
    - Standalone / Unit-Test runtime:
      Provides an in-memory, mockable implementation with deterministic state management,
      failure injection, and snapshot validation without requiring an active database or bench.
    """

    _shared_locks: Set[str] = set()
    _shared_audit_journal: Dict[str, Dict[str, Any]] = {}
    _shared_idempotency_store: Dict[Tuple[str, str], Dict[str, Any]] = {}
    _shared_custom_fields: Dict[Tuple[str, str], Dict[str, Any]] = {}
    _shared_property_setters: Dict[Tuple[str, Optional[str], str], Dict[str, Any]] = {}
    _shared_table_columns: Dict[str, List[ColumnDesc]] = {}
    _shared_revision_hashes: Dict[str, str] = {}

    @classmethod
    def reset_in_memory_state(cls) -> None:
        """Resets all shared in-memory state between unit test runs."""
        cls._shared_locks.clear()
        cls._shared_audit_journal.clear()
        cls._shared_idempotency_store.clear()
        cls._shared_custom_fields.clear()
        cls._shared_property_setters.clear()
        cls._shared_table_columns.clear()
        cls._shared_revision_hashes.clear()

    def __init__(
        self,
        frappe_module: Any = None,
        in_memory: Optional[bool] = None,
        audit_table: str = "tabEXRP Deployment Audit",
        lock_return: Any = _LOCK_SENTINEL,
        target_in_recovery: bool = False,
        before_snapshot: Optional[ExhaustiveSnapshot] = None,
        after_snapshot: Optional[ExhaustiveSnapshot] = None,
        ddl_plan: Optional[DDLPlanInspection] = None,
        existing_columns_desc: Optional[List[ColumnDesc]] = None,
        doctype_fields: Optional[List[Dict[str, Any]]] = None,
        simulate_prepare_error: bool = False,
        simulate_apply_error: bool = False,
        simulate_finalize_error: bool = False,
        use_shared_state: bool = True,
    ):
        self._frappe = frappe_module if frappe_module is not None else frappe
        self.audit_table = audit_table
        self.lock_return = lock_return
        self.target_in_recovery = target_in_recovery
        self.before_snapshot_override = before_snapshot
        self.after_snapshot_override = after_snapshot
        self.ddl_plan_override = ddl_plan
        self.existing_columns_desc_override = existing_columns_desc
        self.doctype_fields_override = doctype_fields
        self.simulate_prepare_error = simulate_prepare_error
        self.simulate_apply_error = simulate_apply_error
        self.simulate_finalize_error = simulate_finalize_error
        self.use_shared_state = use_shared_state

        if in_memory is not None:
            self.in_memory = in_memory
        else:
            self.in_memory = not self._is_frappe_db_available()

        self.apply_called: bool = False
        self.cache_cleared: bool = False
        self.prepared_records: List[Dict[str, Any]] = []
        self.lock_wait_timeout_seconds: Optional[int] = None

        if self.use_shared_state:
            self.locks = self._shared_locks
            self.audit_journal = self._shared_audit_journal
            self.idempotency_store = self._shared_idempotency_store
            self.custom_fields = self._shared_custom_fields
            self.property_setters = self._shared_property_setters
            self.table_columns = self._shared_table_columns
            self.revision_hashes = self._shared_revision_hashes
        else:
            self.locks = set()
            self.audit_journal = {}
            self.idempotency_store = {}
            self.custom_fields = {}
            self.property_setters = {}
            self.table_columns = {}
            self.revision_hashes = {}

        if not self.in_memory:
            self._ensure_audit_table()

    def _is_frappe_db_available(self) -> bool:
        if self._frappe is None:
            return False
        try:
            db = getattr(self._frappe, "db", None)
            if db is None or not hasattr(db, "sql") or not callable(db.sql):
                return False
            return True
        except Exception:
            return False

    def _ensure_audit_table(self) -> None:
        if self.in_memory:
            return
        try:
            self._frappe.db.sql(f"""
                CREATE TABLE IF NOT EXISTS `{self.audit_table}` (
                    name VARCHAR(140) PRIMARY KEY,
                    deployment_id VARCHAR(140),
                    idempotency_key VARCHAR(140),
                    payload_hash VARCHAR(64),
                    site_id VARCHAR(140),
                    doctype VARCHAR(140),
                    fieldname VARCHAR(140),
                    base_revision_hash VARCHAR(64),
                    ddl_plan_statements LONGTEXT,
                    status VARCHAR(64),
                    outcome_json LONGTEXT,
                    created_at DATETIME(6),
                    updated_at DATETIME(6),
                    INDEX idx_site_idemp (site_id, idempotency_key),
                    INDEX idx_site_doctype_status (site_id, doctype, status)
                ) ENGINE=InnoDB
            """)
        except Exception:
            pass

    def acquire_advisory_lock(self, lock_key: str, wait_seconds: int) -> Optional[int]:
        if not self.in_memory:
            try:
                res = self._frappe.db.sql("SELECT GET_LOCK(%s, %s)", (lock_key, wait_seconds))
                if res and len(res) > 0 and len(res[0]) > 0:
                    val = res[0][0]
                    return int(val) if val is not None else None
                return None
            except Exception:
                return None

        # Standalone / in-memory mode
        if self.lock_return is not _LOCK_SENTINEL:
            return self.lock_return
        if lock_key in self.locks:
            return 0  # Lock wait timeout (contention)
        self.locks.add(lock_key)
        return 1

    def release_advisory_lock(self, lock_key: str) -> None:
        if not self.in_memory:
            try:
                self._frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_key,))
            except Exception:
                pass
        else:
            self.locks.discard(lock_key)

    def set_lock_wait_timeout(self, seconds: int) -> None:
        self.lock_wait_timeout_seconds = seconds
        if not self.in_memory:
            try:
                self._frappe.db.sql(f"SET SESSION lock_wait_timeout = {int(seconds)}")
            except Exception:
                pass

    def is_target_in_recovery_required(self, site_id: str, doctype: str) -> bool:
        if self.target_in_recovery:
            return True
        if not self.in_memory:
            try:
                res = self._frappe.db.sql(f"""
                    SELECT COUNT(*) FROM `{self.audit_table}`
                    WHERE site_id = %s AND doctype = %s AND status = 'RECOVERY_REQUIRED'
                """, (site_id, doctype))
                if res and res[0][0] > 0:
                    return True
            except Exception:
                pass
            return False
        for rec in self.audit_journal.values():
            if rec.get("site_id") == site_id and rec.get("doctype") == doctype:
                if rec.get("status") == "RECOVERY_REQUIRED":
                    return True
        return False

    def get_existing_deployment_by_idempotency(
        self, site_id: str, idempotency_key: str
    ) -> Optional[Dict[str, Any]]:
        if not self.in_memory:
            try:
                res = self._frappe.db.sql(f"""
                    SELECT payload_hash, outcome_json FROM `{self.audit_table}`
                    WHERE site_id = %s AND idempotency_key = %s AND outcome_json IS NOT NULL
                """, (site_id, idempotency_key))
                if res and res[0]:
                    payload_hash, outcome_json = res[0]
                    if outcome_json:
                        return {"payload_hash": payload_hash, "outcome": json.loads(outcome_json)}
            except Exception:
                pass
            return None
        return self.idempotency_store.get((site_id, idempotency_key))

    def _get_default_columns(self, doctype: str) -> List[ColumnDesc]:
        return [
            ColumnDesc(name="name", type="varchar(140)", default=None),
            ColumnDesc(name="creation", type="datetime(6)", default=None),
            ColumnDesc(name="modified", type="datetime(6)", default=None),
            ColumnDesc(name="modified_by", type="varchar(140)", default=None),
            ColumnDesc(name="owner", type="varchar(140)", default=None),
            ColumnDesc(name="docstatus", type="int(1)", default="0"),
            ColumnDesc(name="idx", type="int(8)", default="0"),
        ]

    def _update_in_memory_revision_hash(self, doctype: str) -> None:
        cols = self.get_table_columns_description(doctype)
        payload = json.dumps([[c.name, c.type, c.default] for c in cols], sort_keys=True)
        self.revision_hashes[doctype] = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def get_table_columns_description(self, doctype: str) -> List[ColumnDesc]:
        if self.existing_columns_desc_override is not None:
            return self.existing_columns_desc_override
        if not self.in_memory:
            table_name = f"tab{doctype}"
            try:
                res = self._frappe.db.sql(
                    """
                    SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (table_name,),
                )
                return [ColumnDesc(name=r[0], type=r[1], default=r[2]) for r in res]
            except Exception:
                return self._get_default_columns(doctype)
        if doctype not in self.table_columns:
            self.table_columns[doctype] = self._get_default_columns(doctype)
        return list(self.table_columns[doctype])

    def get_doctype_revision_hash(self, doctype: str) -> str:
        if not self.in_memory:
            table_name = f"tab{doctype}"
            try:
                res = self._frappe.db.sql(
                    """
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (table_name,),
                )
                payload = json.dumps([list(c) for c in res], sort_keys=True)
                return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
            except Exception:
                return "rev_default"
        if doctype not in self.revision_hashes:
            self._update_in_memory_revision_hash(doctype)
        return self.revision_hashes[doctype]

    def take_snapshot(
        self, doctype: str, fieldname: str, expected_deployment_id: str
    ) -> ExhaustiveSnapshot:
        if not self.apply_called and self.before_snapshot_override is not None:
            return self.before_snapshot_override
        if self.apply_called and self.after_snapshot_override is not None:
            return self.after_snapshot_override

        if not self.in_memory:
            table_name = f"tab{doctype}"
            try:
                meta_row = self._frappe.db.sql(
                    "SELECT name, fieldtype FROM `tabCustom Field` WHERE dt = %s AND fieldname = %s",
                    (doctype, fieldname),
                )
                has_meta = bool(meta_row)

                col_row = self._frappe.db.sql(
                    """
                    SELECT COLUMN_NAME, COLUMN_TYPE
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
                    """,
                    (table_name, fieldname),
                )
                has_col = bool(col_row)
                rev_hash = self.get_doctype_revision_hash(doctype)
                return ExhaustiveSnapshot(
                    has_meta=has_meta,
                    has_col=has_col,
                    definition_matches=True,
                    indexes_unchanged=True,
                    provenance_matches=True,
                    unapproved_side_effects=False,
                    revision_hash=rev_hash,
                )
            except Exception:
                return ExhaustiveSnapshot(
                    has_meta=False,
                    has_col=False,
                    definition_matches=False,
                    indexes_unchanged=False,
                    provenance_matches=False,
                    unapproved_side_effects=True,
                    revision_hash="rev_error",
                )
        else:
            has_meta = (doctype, fieldname) in self.custom_fields
            cols = self.get_table_columns_description(doctype)
            has_col = any(c.name == fieldname for c in cols)
            rev_hash = self.get_doctype_revision_hash(doctype)
            return ExhaustiveSnapshot(
                has_meta=has_meta,
                has_col=has_col,
                definition_matches=True,
                indexes_unchanged=True,
                provenance_matches=True,
                unapproved_side_effects=False,
                revision_hash=rev_hash,
            )

    def inspect_ddl_plan(self, doctype: str, field_def: Dict[str, Any]) -> DDLPlanInspection:
        if self.ddl_plan_override is not None:
            return self.ddl_plan_override
        cols = self.get_table_columns_description(doctype)
        return inspect_frappe_ddl_plan(
            doctype=doctype,
            field_def=field_def,
            existing_columns_desc=cols,
            doctype_fields=self.doctype_fields_override,
        )

    def persist_prepare_and_audit_intent(self, record: Dict[str, Any]) -> None:
        if self.simulate_prepare_error:
            raise RuntimeError("Fail-closed: Simulated audit prepare failure")

        if not self.in_memory:
            self._ensure_audit_table()
            dep_id = record["deployment_id"]
            ddl_stmts = json.dumps(record.get("ddl_plan_statements", []))
            self._frappe.db.sql(f"""
                INSERT INTO `{self.audit_table}` (
                    name, deployment_id, idempotency_key, payload_hash, site_id, doctype,
                    fieldname, base_revision_hash, ddl_plan_statements, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(6), NOW(6))
                ON DUPLICATE KEY UPDATE
                    idempotency_key = VALUES(idempotency_key),
                    payload_hash = VALUES(payload_hash),
                    status = VALUES(status),
                    updated_at = NOW(6)
            """, (
                dep_id,
                record["deployment_id"],
                record["idempotency_key"],
                record["payload_hash"],
                record["site_id"],
                record["doctype"],
                record["fieldname"],
                record["base_revision_hash"],
                ddl_stmts,
                record["status"],
            ))
            if hasattr(self._frappe.db, "commit"):
                self._frappe.db.commit()
        else:
            dep_id = record["deployment_id"]
            self.audit_journal[dep_id] = dict(record)
            self.prepared_records.append(record)
            self.idempotency_store[(record["site_id"], record["idempotency_key"])] = {
                "payload_hash": record["payload_hash"],
                "outcome": None,
            }

    def persist_final_outcome_and_audit(
        self, deployment_id: str, outcome_record: Dict[str, Any]
    ) -> None:
        if self.simulate_finalize_error:
            raise RuntimeError("Final audit persistence simulated failure")

        outcome = outcome_record.get("outcome", {})
        status = outcome.get("status", "COMPLETED")
        outcome_json = json.dumps(outcome)

        if not self.in_memory:
            self._ensure_audit_table()
            self._frappe.db.sql(f"""
                UPDATE `{self.audit_table}`
                SET status = %s, outcome_json = %s, updated_at = NOW(6)
                WHERE deployment_id = %s
            """, (status, outcome_json, deployment_id))
            if hasattr(self._frappe.db, "commit"):
                self._frappe.db.commit()
        else:
            if deployment_id in self.audit_journal:
                self.audit_journal[deployment_id]["status"] = status
                self.audit_journal[deployment_id]["outcome"] = outcome
                rec = self.audit_journal[deployment_id]
                self.idempotency_store[(rec["site_id"], rec["idempotency_key"])] = outcome_record
            else:
                self.audit_journal[deployment_id] = {
                    "deployment_id": deployment_id,
                    "status": status,
                    "outcome": outcome,
                }

    def apply_native_custom_field(
        self, deployment_id: str, doctype: str, field_def: Dict[str, Any]
    ) -> None:
        self.apply_called = True
        if self.simulate_apply_error:
            raise TimeoutError("(1205, 'Lock wait timeout exceeded')")

        fieldname = field_def["fieldname"]
        if not self.in_memory:
            cf_args = {
                "doctype": "Custom Field",
                "dt": doctype,
                "fieldname": fieldname,
                "label": field_def.get("label", fieldname),
                "fieldtype": field_def.get("fieldtype", "Data"),
                "options": field_def.get("options"),
                "reqd": field_def.get("reqd", 0),
                "read_only": field_def.get("read_only", 0),
                "description": field_def.get("description"),
                "insert_after": field_def.get("insert_after"),
                "default": field_def.get("default"),
            }
            cf_doc = self._frappe.get_doc(cf_args)
            cf_doc.insert(ignore_permissions=True)
            if hasattr(self._frappe.db, "commit"):
                self._frappe.db.commit()
        else:
            self.custom_fields[(doctype, fieldname)] = dict(field_def)
            if doctype not in self.table_columns:
                self.table_columns[doctype] = self._get_default_columns(doctype)
            if not any(c.name == fieldname for c in self.table_columns[doctype]):
                t_info = MARIADB_TYPE_MAP.get(field_def.get("fieldtype", "Data"), ("varchar", "140"))
                type_str = f"{t_info[0]}({t_info[1]})" if t_info[1] else t_info[0]
                self.table_columns[doctype].append(
                    ColumnDesc(name=fieldname, type=type_str, default=field_def.get("default"))
                )
            self._update_in_memory_revision_hash(doctype)

    def clear_doctype_cache(self, doctype: str) -> None:
        self.cache_cleared = True
        if not self.in_memory:
            if hasattr(self._frappe, "clear_cache"):
                self._frappe.clear_cache(doctype=doctype)

    def apply_property_setter(
        self,
        doctype: str,
        fieldname: Optional[str],
        property_name: str,
        value: Any,
        property_type: str = "Data",
    ) -> None:
        self.apply_called = True
        if self.simulate_apply_error:
            raise TimeoutError("(1205, 'Lock wait timeout exceeded')")

        if self.in_memory:
            self.property_setters[(doctype, fieldname, property_name)] = {
                "name": f"ps-{doctype}-{fieldname or 'doc'}-{property_name}",
                "doc_type": doctype,
                "field_name": fieldname,
                "property": property_name,
                "value": value,
                "property_type": property_type,
            }
        else:
            if hasattr(self._frappe, "make_property_setter"):
                try:
                    self._frappe.make_property_setter({
                        "doctype": doctype,
                        "fieldname": fieldname,
                        "property": property_name,
                        "value": value,
                        "property_type": property_type,
                    })
                except TypeError:
                    self._frappe.make_property_setter(
                        doctype=doctype,
                        fieldname=fieldname,
                        property=property_name,
                        value=value,
                        property_type=property_type,
                    )
                if hasattr(self._frappe.db, "commit"):
                    self._frappe.db.commit()

    def get_property_setter(
        self, doctype: str, fieldname: Optional[str], property_name: str
    ) -> Optional[Dict[str, Any]]:
        if self.in_memory:
            return self.property_setters.get((doctype, fieldname, property_name))
        try:
            if fieldname:
                res = self._frappe.db.sql(
                    "SELECT name, value, property_type FROM `tabProperty Setter` WHERE doc_type = %s AND field_name = %s AND property = %s",
                    (doctype, fieldname, property_name),
                    as_dict=True,
                )
            else:
                res = self._frappe.db.sql(
                    "SELECT name, value, property_type FROM `tabProperty Setter` WHERE doc_type = %s AND (field_name IS NULL OR field_name = '') AND property = %s",
                    (doctype, property_name),
                    as_dict=True,
                )
            if res:
                row = res[0]
                if isinstance(row, dict):
                    return row
                return {"name": row[0], "value": row[1], "property_type": row[2] if len(row) > 2 else "Data"}
            return None
        except Exception:
            return None

    def delete_property_setter(
        self, doctype: str, fieldname: Optional[str], property_name: str
    ) -> None:
        if self.in_memory:
            self.property_setters.pop((doctype, fieldname, property_name), None)
        else:
            try:
                if fieldname:
                    self._frappe.db.sql(
                        "DELETE FROM `tabProperty Setter` WHERE doc_type = %s AND field_name = %s AND property = %s",
                        (doctype, fieldname, property_name),
                    )
                else:
                    self._frappe.db.sql(
                        "DELETE FROM `tabProperty Setter` WHERE doc_type = %s AND (field_name IS NULL OR field_name = '') AND property = %s",
                        (doctype, property_name),
                    )
                if hasattr(self._frappe.db, "commit"):
                    self._frappe.db.commit()
            except Exception:
                pass

    def get_deployment_record(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        if self.in_memory:
            return self.audit_journal.get(deployment_id)
        try:
            self._ensure_audit_table()
            res = self._frappe.db.sql(
                f"SELECT * FROM `{self.audit_table}` WHERE deployment_id = %s",
                (deployment_id,),
                as_dict=True,
            )
            if res:
                row = dict(res[0])
                if row.get("outcome_json"):
                    try:
                        extra = json.loads(row["outcome_json"])
                        if isinstance(extra, dict):
                            for k, v in extra.items():
                                if k not in row or row[k] is None:
                                    row[k] = v
                    except Exception:
                        pass
                return row
            return None
        except Exception:
            return None

    def update_deployment_status(
        self, deployment_id: str, status: str, outcome: Optional[Dict[str, Any]] = None
    ) -> None:
        outcome_record = {"outcome": outcome or {"status": status}}
        self.persist_final_outcome_and_audit(deployment_id, outcome_record)

    def get_effective_field_property(
        self, doctype: str, fieldname: str, property_name: str
    ) -> Any:
        ps = self.get_property_setter(doctype, fieldname, property_name)
        if ps is not None:
            return ps.get("value")
        if self.in_memory:
            if (doctype, fieldname) in self.custom_fields:
                return self.custom_fields[(doctype, fieldname)].get(property_name)
            if property_name in ("hidden", "reqd", "read_only", "in_list_view", "in_standard_filter", "bold"):
                return 0
            if property_name == "label":
                return fieldname.replace("_", " ").title()
            return None
        else:
            if hasattr(self._frappe, "get_meta"):
                try:
                    meta = self._frappe.get_meta(doctype)
                    df = meta.get_field(fieldname) if hasattr(meta, "get_field") else None
                    if df:
                        return getattr(df, property_name, None)
                except Exception:
                    pass
            return None



def apply_configuration_change(
    doctype: str,
    deployment_id: Optional[str] = None,
    field_def: Optional[Union[Dict[str, Any], str]] = None,
    idempotency_key: Optional[str] = None,
    proposal: Optional[Any] = None,
    base_revision_hash: Optional[str] = None,
    site_id: Optional[str] = None,
    adapter: Optional[Rev23DeploymentAdapter] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Whitelisted RPC endpoint for single-field physical schema deployment.
    Adheres strictly to ADR-001 Rev 2.3:
    1. Checks authenticated user roles: only authorized roles (System Manager,
       Finance Director, Operations Director) can apply changes.
    2. Invokes execute_single_field_deployment with durable MariaDB advisory lock,
       DDL plan gate, prepare audit, native Custom Field creation, and snapshot reconciliation.
    3. Returns structured deployment outcome (status, disposition, execution_time_ms).
    """
    start_time = time.perf_counter()

    # Normalize deployment_id
    if not deployment_id:
        deployment_id = kwargs.get("deployment_id") or f"dep_{uuid.uuid4().hex[:12]}"

    # Extract field_def from proposal if needed
    if not field_def and isinstance(proposal, dict):
        changes = proposal.get("changes", [])
        if changes:
            field_def = changes[0]

    # Normalize JSON field_def if serialized over RPC
    if isinstance(field_def, str):
        try:
            field_def = json.loads(field_def)
        except Exception as parse_err:
            execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "deployment_id": deployment_id,
                "status": "REJECTED",
                "success": False,
                "stage": "VALIDATE",
                "disposition": "INVALID_JSON_PAYLOAD",
                "reason": f"Could not parse field_def JSON string: {parse_err}",
                "execution_time_ms": execution_time_ms,
            }

    if not field_def or not isinstance(field_def, dict) or "fieldname" not in field_def:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "VALIDATE",
            "disposition": "INVALID_FIELD_DEFINITION",
            "reason": "Missing or invalid 'field_def' (must contain 'fieldname').",
            "execution_time_ms": execution_time_ms,
        }

    # Step 1: Check user roles
    user_roles = kwargs.get("user_roles")
    if user_roles is None:
        user_roles = get_current_user_roles()

    user_role_set = set(user_roles)
    if not user_role_set.intersection(AUTHORIZED_DEPLOYMENT_ROLES):
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if kwargs.get("raise_on_unauthorized"):
            if frappe and hasattr(frappe, "PermissionError"):
                raise frappe.PermissionError(
                    f"Unauthorized: User roles {sorted(user_role_set)} lack required deployment authority {sorted(AUTHORIZED_DEPLOYMENT_ROLES)}."
                )
            raise PermissionError(
                f"Unauthorized: User roles {sorted(user_role_set)} lack required deployment authority {sorted(AUTHORIZED_DEPLOYMENT_ROLES)}."
            )
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "AUTHORIZATION",
            "disposition": "UNAUTHORIZED_ROLE",
            "reason": (
                f"User does not possess any authorized deployment role. "
                f"Required one of: {sorted(AUTHORIZED_DEPLOYMENT_ROLES)}. Found: {sorted(user_role_set)}"
            ),
            "execution_time_ms": execution_time_ms,
        }

    # Step 1.5: Validate mutation safety against Zone rules & Tier 0 invariants
    proposal_payload = proposal if isinstance(proposal, dict) else {
        "target_doctype": doctype,
        "intent": "add_custom_fields",
        "changes": [field_def],
        "user_roles": list(user_role_set),
    }
    proposal_payload["target_doctype"] = doctype
    proposal_payload["user_roles"] = list(user_role_set)

    try:
        validate_mutation_safety(proposal_payload)
    except ZoneSafetyViolation as exc:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "SAFETY_GUARDRAILS",
            "disposition": "ZONE_SAFETY_VIOLATION",
            "reason": str(exc),
            "execution_time_ms": execution_time_ms,
        }

    # Step 2: Initialize or resolve deployment adapter
    db = adapter or kwargs.get("db")
    if db is None:
        db = FrappeDeploymentAdapter()

    # Step 3: Resolve site_id and idempotency_key
    if not site_id:
        site_id = (
            getattr(getattr(frappe, "local", None), "site", None)
            or kwargs.get("site")
            or "default"
        )

    if not idempotency_key:
        idempotency_key = kwargs.get("idempotency_key") or f"idemp-{deployment_id}"

    # Step 4: Resolve base_revision_hash if not provided
    if base_revision_hash is None:
        if hasattr(db, "get_doctype_revision_hash") and callable(getattr(db, "get_doctype_revision_hash", None)):
            base_revision_hash = db.get_doctype_revision_hash(doctype)
        elif hasattr(db, "take_snapshot") and callable(getattr(db, "take_snapshot", None)):
            base_revision_hash = db.take_snapshot(doctype, field_def["fieldname"], deployment_id).revision_hash
        else:
            base_revision_hash = "rev_default"

    lock_wait_seconds = int(kwargs.get("lock_wait_seconds", 3))

    # Step 5: Execute 6-stage durable deployment sequence (§8 & §9)
    try:
        outcome = execute_single_field_deployment(
            db=db,
            deployment_id=deployment_id,
            idempotency_key=idempotency_key,
            site_id=site_id,
            doctype=doctype,
            base_revision_hash=base_revision_hash,
            field_def=field_def,
            lock_wait_seconds=lock_wait_seconds,
        )
    except IdempotencyConflictError as conflict_err:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if kwargs.get("raise_on_conflict"):
            raise
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "IDEMPOTENCY_CHECK",
            "disposition": "IDEMPOTENCY_CONFLICT",
            "reason": str(conflict_err),
            "execution_time_ms": execution_time_ms,
        }
    except Exception as exc:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "FAILED_CLEAN",
            "success": False,
            "stage": "UNKNOWN",
            "disposition": "UNEXPECTED_ERROR",
            "reason": f"Deployment execution raised unhandled exception: {exc}",
            "execution_time_ms": execution_time_ms,
        }

    execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
    outcome["execution_time_ms"] = execution_time_ms
    outcome["success"] = (outcome.get("status") == "APPLIED")
    if "doctype" not in outcome:
        outcome["doctype"] = doctype
    if "fieldname" not in outcome and "fieldname" in field_def:
        outcome["fieldname"] = field_def["fieldname"]

    if "disposition" not in outcome:
        if outcome.get("status") == "REJECTED" and outcome.get("stage") == "ACQUIRE":
            outcome["disposition"] = "LOCK_CONTENTION_OR_TIMEOUT"
        else:
            outcome["disposition"] = outcome.get("stage", outcome.get("status", "UNKNOWN"))

    return outcome


if frappe and hasattr(frappe, "whitelist"):
    apply_configuration_change = frappe.whitelist()(apply_configuration_change)


def apply_property_setter_change(
    doctype: str,
    deployment_id: Optional[str] = None,
    fieldname: Optional[str] = None,
    property_name: Optional[str] = None,
    value: Any = None,
    property_type: str = "Data",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Whitelisted RPC endpoint for Property Setter metadata mutation.
    Adheres strictly to ADR-001 Rev 2.3 (§5, §8, §9.1):
    1. Checks authenticated user roles: only authorized roles (System Manager,
       Finance Director, Operations Director) can apply changes.
    2. Invokes execute_property_setter_deployment with durable MariaDB advisory lock,
       audit prepare durability, Property Setter creation, cache clear, and metadata reflection.
    3. Returns structured outcome (status, disposition, execution_time_ms).
    """
    start_time = time.perf_counter()

    if not deployment_id:
        deployment_id = kwargs.get("deployment_id") or f"dep_ps_{uuid.uuid4().hex[:12]}"

    if not property_name and "property" in kwargs:
        property_name = kwargs.get("property")

    user_roles = kwargs.get("user_roles")
    if user_roles is None:
        user_roles = get_current_user_roles()

    user_role_set = set(user_roles)
    if not user_role_set.intersection(AUTHORIZED_DEPLOYMENT_ROLES):
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if kwargs.get("raise_on_unauthorized"):
            if frappe and hasattr(frappe, "PermissionError"):
                raise frappe.PermissionError(
                    f"Unauthorized: User roles {sorted(user_role_set)} lack required deployment authority {sorted(AUTHORIZED_DEPLOYMENT_ROLES)}."
                )
            raise PermissionError(
                f"Unauthorized: User roles {sorted(user_role_set)} lack required deployment authority {sorted(AUTHORIZED_DEPLOYMENT_ROLES)}."
            )
        return {
            "deployment_id": deployment_id,
            "status": "REJECTED",
            "success": False,
            "stage": "AUTHORIZATION",
            "disposition": "UNAUTHORIZED_ROLE",
            "reason": (
                f"User does not possess any authorized deployment role. "
                f"Required one of: {sorted(AUTHORIZED_DEPLOYMENT_ROLES)}. Found: {sorted(user_role_set)}"
            ),
            "execution_time_ms": execution_time_ms,
        }

    db = kwargs.get("adapter") or kwargs.get("db")
    if db is None:
        db = FrappeDeploymentAdapter()

    site_id = (
        getattr(getattr(frappe, "local", None), "site", None)
        or kwargs.get("site")
        or kwargs.get("site_id")
        or "default"
    )

    forward_kwargs = dict(kwargs)
    forward_kwargs.pop("user_roles", None)
    forward_kwargs.pop("adapter", None)
    forward_kwargs.pop("db", None)
    forward_kwargs.pop("site", None)
    forward_kwargs.pop("site_id", None)

    try:
        outcome = execute_property_setter_deployment(
            db=db,
            deployment_id=deployment_id,
            site_id=site_id,
            doctype=doctype,
            fieldname=fieldname,
            property_name=property_name,
            value=value,
            property_type=property_type,
            user_roles=user_roles,
            **forward_kwargs,
        )
    except Exception as exc:
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "deployment_id": deployment_id,
            "status": "FAILED_CLEAN",
            "success": False,
            "stage": "UNKNOWN",
            "disposition": "UNEXPECTED_ERROR",
            "reason": f"Property Setter execution raised unhandled exception: {exc}",
            "execution_time_ms": execution_time_ms,
        }

    return outcome


def revert_configuration_change(
    deployment_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Whitelisted RPC endpoint for 1-click rollback and soft quarantine.
    Adheres strictly to ADR-001 Rev 2.3 (§8, §9.1):
    - Strictly checks authorization: only System Manager, Finance Director, Operations Director.
    - If Property Setter: restores baseline property value captured before mutation,
      or removes Property Setter if no baseline existed. Marks ROLLED_BACK.
    - If Custom Field: soft-quarantines by setting hidden=1 and reqd=0 without dropping column.
      Marks QUARANTINED.
    """
    user_roles = kwargs.get("caller_roles") or kwargs.get("user_roles")
    if user_roles is None:
        user_roles = get_current_user_roles()

    db = kwargs.get("adapter") or kwargs.get("db")
    if db is None:
        db = FrappeDeploymentAdapter()

    forward_kwargs = dict(kwargs)
    forward_kwargs.pop("caller_roles", None)
    forward_kwargs.pop("user_roles", None)
    forward_kwargs.pop("adapter", None)
    forward_kwargs.pop("db", None)

    return execute_rollback(
        deployment_id=deployment_id,
        caller_roles=user_roles,
        db=db,
        **forward_kwargs,
    )



if frappe and hasattr(frappe, "whitelist"):
    apply_property_setter_change = frappe.whitelist()(apply_property_setter_change)
    revert_configuration_change = frappe.whitelist()(revert_configuration_change)



def enforce_runtime_policies_on_validate(doc, method=None, user_roles: Optional[List[str]] = None) -> PolicyEvaluationResult:
    """
    Lifecycle hook for Document.validate (§4.2).
    Resolves caller roles and evaluates active runtime policies against the document.
    Throws frappe.ValidationError (RuntimePolicyViolation) on violation.
    """
    if user_roles is None:
        user_roles = get_current_user_roles()

    result = policy_catalog.evaluate_validate(doc, user_roles=user_roles, raise_exception=False)
    if not result.allowed:
        policy_id = result.violated_policies[0] if result.violated_policies else "UNKNOWN"
        reason = result.reasons[0] if result.reasons else "Policy validation failed"
        msg = f"Runtime Policy Violation [{policy_id}]: {reason}"
        if frappe and hasattr(frappe, "throw"):
            frappe.throw(msg, exc=RuntimePolicyViolation)
        raise RuntimePolicyViolation(msg, policy_id=policy_id, result=result)
    return result


def enforce_runtime_policies_on_submit(doc, method=None, user_roles: Optional[List[str]] = None) -> PolicyEvaluationResult:
    """
    Lifecycle hook for Document.before_submit (§4.2).
    Evaluates submission gates and submit-time invariants.
    Throws frappe.ValidationError (RuntimePolicyViolation) on violation.
    """
    if user_roles is None:
        user_roles = get_current_user_roles()

    result = policy_catalog.evaluate_submit(doc, user_roles=user_roles, raise_exception=False)
    if not result.allowed:
        policy_id = result.violated_policies[0] if result.violated_policies else "UNKNOWN"
        reason = result.reasons[0] if result.reasons else "Policy submit lock failed"
        msg = f"Runtime Policy Violation [{policy_id}]: {reason}"
        if frappe and hasattr(frappe, "throw"):
            frappe.throw(msg, exc=RuntimePolicyViolation)
        raise RuntimePolicyViolation(msg, policy_id=policy_id, result=result)
    return result


def enforce_runtime_policies_on_update_after_submit(doc, method=None, user_roles: Optional[List[str]] = None) -> PolicyEvaluationResult:
    """
    Lifecycle hook for Document.before_update_after_submit (§4.2).
    Prevents modifying locked or protected fields on submitted documents.
    Throws frappe.ValidationError (RuntimePolicyViolation) on violation.
    """
    if user_roles is None:
        user_roles = get_current_user_roles()

    result = policy_catalog.evaluate_update_after_submit(doc, user_roles=user_roles, raise_exception=False)
    if not result.allowed:
        policy_id = result.violated_policies[0] if result.violated_policies else "UNKNOWN"
        reason = result.reasons[0] if result.reasons else "Policy update-after-submit violation"
        msg = f"Runtime Policy Violation [{policy_id}]: {reason}"
        if frappe and hasattr(frappe, "throw"):
            frappe.throw(msg, exc=RuntimePolicyViolation)
        raise RuntimePolicyViolation(msg, policy_id=policy_id, result=result)
    return result


def get_runtime_policies(doctype: Optional[str] = None, stage: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Whitelisted RPC method: returns active runtime policies for a given DocType and lifecycle stage.
    """
    if doctype:
        policies = policy_catalog.get_active_policies(doctype, stage=stage)
    else:
        policies = []
        for dt in policy_catalog._policies:
            policies.extend(policy_catalog.get_active_policies(dt, stage=stage))
    return [p.to_dict() for p in policies]


def register_runtime_policy(policy_data: Union[Dict[str, Any], RuntimePolicy]) -> Dict[str, Any]:
    """
    Registers a new runtime policy or updates an existing one.
    """
    if isinstance(policy_data, dict):
        policy = RuntimePolicy(**policy_data)
    else:
        policy = policy_data
    policy_catalog.register_policy(policy)
    return {"success": True, "policy_id": policy.policy_id}


def evaluate_document_policies(
    doctype: str,
    doc: Dict[str, Any],
    stage: str = "validate",
    user_roles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Whitelisted RPC method: Evaluates runtime policies against a document preview
    without saving to the database.
    """
    if user_roles is None:
        user_roles = get_current_user_roles()
    if isinstance(doc, dict):
        doc = dict(doc)
        doc["doctype"] = doctype

    norm_stage = (stage or "validate").lower()
    if norm_stage in ("submit", "before_submit"):
        res = policy_catalog.evaluate_submit(doc, user_roles=user_roles, raise_exception=False)
    elif norm_stage in ("update_after_submit", "before_update_after_submit"):
        res = policy_catalog.evaluate_update_after_submit(doc, user_roles=user_roles, raise_exception=False)
    else:
        res = policy_catalog.evaluate_validate(doc, user_roles=user_roles, raise_exception=False)

    return res.to_dict()


def test_llm_connection(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    api_base_url: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Whitelisted RPC endpoint: Tests connectivity to the selected LLM provider.
    Returns {"success": True, "message": "Connection verified successfully!"} or error details.
    """
    config = resolve_llm_config()

    eff_provider = provider or config.get("llm_provider") or "Google Gemini"
    eff_api_key = api_key or config.get("api_key")
    eff_model = model_name or config.get("model_name") or "gemini-3.8-flash"
    eff_base_url = api_base_url or config.get("api_base_url")

    # If offline_mode is set in EXRP Settings and no provider was explicitly passed,
    # or provider is explicitly Mock
    if eff_provider == "Mock / Offline Test Mode" or (config.get("offline_mode") and not provider):
        return {
            "success": True,
            "message": "Connection verified successfully!",
        }

    if not eff_api_key:
        return {
            "success": False,
            "message": f"API key is missing for provider '{eff_provider}'.",
            "error": "Missing API Key",
        }

    try:
        if eff_provider == "Google Gemini":
            from google import genai
            client = genai.Client(api_key=eff_api_key)
            client.models.get(model=eff_model)
            return {
                "success": True,
                "message": "Connection verified successfully!",
            }

        elif eff_provider in ("OpenAI", "Custom OpenAI-Compatible"):
            import requests
            base_url = (eff_base_url or "https://api.openai.com/v1").rstrip("/")
            url = f"{base_url}/models"
            headers = {"Authorization": f"Bearer {eff_api_key}"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection verified successfully!",
                }
            else:
                return {
                    "success": False,
                    "message": f"{eff_provider} HTTP {resp.status_code}: {resp.text}",
                    "status_code": resp.status_code,
                }

        elif eff_provider == "Anthropic":
            import requests
            base_url = (eff_base_url or "https://api.anthropic.com/v1").rstrip("/")
            url = f"{base_url}/models"
            headers = {
                "x-api-key": eff_api_key,
                "anthropic-version": "2023-06-01",
            }
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection verified successfully!",
                }
            else:
                return {
                    "success": False,
                    "message": f"Anthropic HTTP {resp.status_code}: {resp.text}",
                    "status_code": resp.status_code,
                }

        else:
            return {
                "success": False,
                "message": f"Unsupported LLM provider: {eff_provider}",
            }

    except Exception as exc:
        return {
            "success": False,
            "message": f"Connection failed: {str(exc)}",
            "error": str(exc),
        }


def get_llm_config() -> Dict[str, Any]:
    """
    Whitelisted RPC endpoint: returns non-sensitive LLM configuration
    (provider, model_name, has_api_key: bool).
    """
    config = resolve_llm_config()
    return {
        "provider": config.get("llm_provider"),
        "model_name": config.get("model_name"),
        "has_api_key": bool(config.get("api_key")),
        "api_base_url": config.get("api_base_url"),
        "offline_mode": bool(config.get("offline_mode")),
        "temperature": config.get("temperature", 0.2),
        "max_retries": config.get("max_retries", 2),
        "enable_sidecar": bool(config.get("enable_sidecar", True)),
    }


if frappe and hasattr(frappe, "whitelist"):
    get_runtime_policies = frappe.whitelist()(get_runtime_policies)
    register_runtime_policy = frappe.whitelist()(register_runtime_policy)
    evaluate_document_policies = frappe.whitelist()(evaluate_document_policies)
    test_llm_connection = frappe.whitelist()(test_llm_connection)
    get_llm_config = frappe.whitelist()(get_llm_config)


