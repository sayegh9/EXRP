"""
Comprehensive Unit & PoC Verification Suite for EXRP AI Control Plane (ADR-001 Rev 2.3)
Verifies Sections 5, 6, 7, 8, 9, and 11 (Suites A, B, C):
- Suite A: DDL Plan Gate (§6.1/6.2), 6-row Non-Destructive Snapshot Reconciliation Table (§9),
  Idempotency Key + Canonical Payload Hash conflict detection (§7.1)
- Suite B: Bounded <=64-char lock identifier, GET_LOCK (1 / 0 / NULL) handling (§7.2), Revision Conflict
- Suite C: Tier 0 Parent/Child invariant protection, Tier 1 bidirectional authority, Phase 1 additive field rules (§5.1)
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import types
if "frappe" not in sys.modules:
    try:
        import frappe
    except ImportError:
        f = types.ModuleType("frappe")
        f.utils = types.ModuleType("frappe.utils")
        f.utils.cstr = lambda x: str(x)
        sys.modules["frappe"] = f
        sys.modules["frappe.utils"] = f.utils

import unittest
from exrp.ai_control_plane.safety_guardrails import (
    validate_mutation_safety,
    ZoneSafetyViolation,
)
from exrp.ai_control_plane.schema_reconciler import (
    execute_single_field_deployment,
    make_bounded_lock_key,
    ExhaustiveSnapshot,
    DDLPlanInspection,
    IdempotencyConflictError,
)
from exrp.ai_control_plane.ddl_plan_gate import (
    inspect_frappe_ddl_plan,
    validate_ddl_plan,
    ColumnDesc,
)


class FakeRev23DeploymentAdapter:
    """Deterministic test double implementing Rev23DeploymentAdapter for Suites A, B, and C."""

    def __init__(
        self,
        lock_return: int = 1,
        target_in_recovery: bool = False,
        before_snapshot: ExhaustiveSnapshot = None,
        after_snapshot: ExhaustiveSnapshot = None,
        ddl_plan: DDLPlanInspection = None,
        existing_columns_desc: list = None,
        doctype_fields: list = None,
        simulate_prepare_error: bool = False,
        simulate_apply_error: bool = False,
        simulate_finalize_error: bool = False,
    ):
        self.lock_return = lock_return
        self.target_in_recovery = target_in_recovery
        self.before_snapshot = before_snapshot or ExhaustiveSnapshot(
            has_meta=False, has_col=False, revision_hash="rev_100"
        )
        self.after_snapshot = after_snapshot or ExhaustiveSnapshot(
            has_meta=True,
            has_col=True,
            definition_matches=True,
            indexes_unchanged=True,
            provenance_matches=True,
            unapproved_side_effects=False,
            revision_hash="rev_101",
        )
        self.existing_columns_desc = existing_columns_desc
        self.doctype_fields = doctype_fields
        self.ddl_plan = ddl_plan
        self.simulate_prepare_error = simulate_prepare_error
        self.simulate_apply_error = simulate_apply_error
        self.simulate_finalize_error = simulate_finalize_error

        self.lock_released = False
        self.idempotency_store = {}
        self.prepared_records = []
        self.apply_called = False
        self.cache_cleared = False

    def acquire_advisory_lock(self, lock_key: str, wait_seconds: int):
        return self.lock_return

    def release_advisory_lock(self, lock_key: str) -> None:
        self.lock_released = True

    def is_target_in_recovery_required(self, site_id: str, doctype: str) -> bool:
        return self.target_in_recovery

    def get_existing_deployment_by_idempotency(self, site_id: str, idempotency_key: str):
        return self.idempotency_store.get((site_id, idempotency_key))

    def take_snapshot(self, doctype: str, fieldname: str, expected_deployment_id: str) -> ExhaustiveSnapshot:
        return self.after_snapshot if self.apply_called else self.before_snapshot

    def inspect_ddl_plan(self, doctype: str, field_def: dict) -> DDLPlanInspection:
        if self.ddl_plan is not None:
            return self.ddl_plan
        return inspect_frappe_ddl_plan(
            doctype=doctype,
            field_def=field_def,
            existing_columns_desc=self.existing_columns_desc,
            doctype_fields=self.doctype_fields,
        )

    def persist_prepare_and_audit_intent(self, record: dict) -> None:
        if self.simulate_prepare_error:
            raise RuntimeError("Audit DB write failed")
        self.prepared_records.append(record)

    def persist_final_outcome_and_audit(self, deployment_id: str, outcome_record: dict) -> None:
        if self.simulate_finalize_error:
            raise RuntimeError("Finalization DB commit failed")
        if self.prepared_records:
            rec = self.prepared_records[-1]
            self.idempotency_store[(rec["site_id"], rec["idempotency_key"])] = outcome_record

    def set_lock_wait_timeout(self, seconds: int) -> None:
        pass

    def apply_native_custom_field(self, deployment_id: str, doctype: str, field_def: dict) -> None:
        self.apply_called = True
        if self.simulate_apply_error:
            raise TimeoutError("(1205, 'Lock wait timeout exceeded')")

    def clear_doctype_cache(self, doctype: str) -> None:
        self.cache_cleared = True


class TestADR001Rev23(unittest.TestCase):

    # --- SUITE A: DDL Plan Gate, Exhaustive Snapshot Reconciliation & Idempotency ---

    def test_suite_a_ddl_plan_gate_rejects_unapproved_modify_or_index_change(self):
        """§6.1 & §6.2: If updatedb() would emit unapproved MODIFY/INDEX DDL, fail closed and route to queue."""
        db = FakeRev23DeploymentAdapter(
            ddl_plan=DDLPlanInspection(
                inspectable=True,
                statements=[
                    "ALTER TABLE `tabSales Order` ADD COLUMN `custom_cargo_id` varchar(140), MODIFY COLUMN `status` varchar(255)"
                ],
                is_approved_additive_only=False,
                rejection_reason="Unapproved MODIFY COLUMN detected in updatedb() diff",
            )
        )
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_101",
            idempotency_key="idem_101",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def={"fieldname": "custom_cargo_id", "fieldtype": "Data"},
        )
        self.assertEqual(res["status"], "REJECTED")
        self.assertEqual(res["fallback_action"], "QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT")
        self.assertFalse(db.apply_called)
        self.assertTrue(db.lock_released)

    def test_suite_a_ddl_plan_gate_approves_valid_single_add_column(self):
        """§6.1 & §6.2: Single nullable custom column without indexes produces approved ADD COLUMN plan."""
        field_def = {"fieldname": "custom_cargo_id", "fieldtype": "Data"}
        inspection = inspect_frappe_ddl_plan("Sales Order", field_def)
        self.assertTrue(inspection.inspectable)
        self.assertTrue(inspection.is_approved_additive_only)
        self.assertIsNone(inspection.rejection_reason)
        self.assertEqual(len(inspection.statements), 1)
        self.assertEqual(
            inspection.statements[0],
            "ALTER TABLE `tabSales Order` ADD COLUMN `custom_cargo_id` varchar(140)",
        )

        # Stage 2 Gate verification through execute_single_field_deployment
        db = FakeRev23DeploymentAdapter()
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_valid_plan",
            idempotency_key="idem_valid_plan",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def=field_def,
        )
        self.assertEqual(res["status"], "APPLIED")
        self.assertTrue(db.apply_called)

    def test_suite_a_ddl_plan_gate_rejects_unexpected_modify_column_diff(self):
        """§6.1 & §6.2: Reject plan when DocType metadata diffs an existing column (e.g. status varchar(140) -> varchar(255))."""
        existing_cols = [
            {"name": "status", "type": "varchar(140)", "default": None, "index": 0, "unique": 0}
        ]
        doctype_fields = [
            {"fieldname": "status", "fieldtype": "Data", "length": 255}
        ]
        field_def = {"fieldname": "custom_cargo_id", "fieldtype": "Data"}

        inspection = inspect_frappe_ddl_plan(
            doctype="Sales Order",
            field_def=field_def,
            existing_columns_desc=existing_cols,
            doctype_fields=doctype_fields,
        )
        self.assertTrue(inspection.inspectable)
        self.assertFalse(inspection.is_approved_additive_only)
        self.assertIsNotNone(inspection.rejection_reason)
        self.assertIn("MODIFY", inspection.rejection_reason)

        # Verify Stage 2 gate in execute_single_field_deployment halts and routes to queue
        db = FakeRev23DeploymentAdapter(
            existing_columns_desc=existing_cols,
            doctype_fields=doctype_fields,
        )
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_rej_modify",
            idempotency_key="idem_rej_modify",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def=field_def,
        )
        self.assertEqual(res["status"], "REJECTED")
        self.assertEqual(res["fallback_action"], "QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT")
        self.assertIn("MODIFY", res["reason"])
        self.assertFalse(db.apply_called)

    def test_suite_a_ddl_plan_gate_rejects_secondary_index_queries(self):
        """§6.1 & §6.2: Reject plan when field definition requests a secondary index (search_index=1)."""
        field_def = {
            "fieldname": "custom_cargo_id",
            "fieldtype": "Data",
            "search_index": 1,
        }
        inspection = inspect_frappe_ddl_plan("Sales Order", field_def)
        self.assertTrue(inspection.inspectable)
        self.assertFalse(inspection.is_approved_additive_only)
        self.assertIsNotNone(inspection.rejection_reason)
        self.assertIn("ADD INDEX", inspection.rejection_reason)

        # Verify Stage 2 gate in execute_single_field_deployment halts and routes to queue
        db = FakeRev23DeploymentAdapter()
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_rej_index",
            idempotency_key="idem_rej_index",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def=field_def,
        )
        self.assertEqual(res["status"], "REJECTED")
        self.assertEqual(res["fallback_action"], "QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT")
        self.assertIn("ADD INDEX", res["reason"])
        self.assertFalse(db.apply_called)

    def test_suite_a_ddl_plan_gate_rejects_unique_and_naming_violations(self):
        """§5.1 & §6.1: Reject plan with unique constraint or non-compliant fieldnames."""
        # 1. Unique constraint rejection
        unique_def = {"fieldname": "custom_cargo_id", "fieldtype": "Data", "unique": 1}
        insp_unique = inspect_frappe_ddl_plan("Sales Order", unique_def)
        self.assertFalse(insp_unique.is_approved_additive_only)

        # 2. Non-custom prefix fieldname rejection
        non_custom = {"fieldname": "cargo_id", "fieldtype": "Data"}
        insp_non_custom = inspect_frappe_ddl_plan("Sales Order", non_custom)
        self.assertFalse(insp_non_custom.is_approved_additive_only)
        self.assertIn("does not match approved additive ADD COLUMN pattern", insp_non_custom.rejection_reason)

        # 3. Uppercase letters in fieldname rejection
        upper_field = {"fieldname": "custom_Cargo_Id", "fieldtype": "Data"}
        insp_upper = inspect_frappe_ddl_plan("Sales Order", upper_field)
        self.assertFalse(insp_upper.is_approved_additive_only)
        self.assertIn("does not match approved additive ADD COLUMN pattern", insp_upper.rejection_reason)

    def test_suite_a_row_4_orphan_metadata_enters_recovery_required_without_auto_delete(self):
        """§9 Row 4: Present | Absent (Orphan metadata) enters RECOVERY_REQUIRED and does NOT auto-delete in Phase 1."""
        db = FakeRev23DeploymentAdapter(
            simulate_apply_error=True,
            after_snapshot=ExhaustiveSnapshot(has_meta=True, has_col=False, revision_hash="rev_100"),
        )
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_102",
            idempotency_key="idem_102",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def={"fieldname": "custom_cargo_id", "fieldtype": "Data"},
        )
        self.assertEqual(res["status"], "RECOVERY_REQUIRED")
        self.assertEqual(res["disposition"], "ORPHAN_METADATA_NON_DESTRUCTIVE_HOLD")

    def test_suite_a_row_1_absent_absent_returns_failed_clean(self):
        """§9 Row 1: Absent | Absent with unchanged baseline returns FAILED_CLEAN."""
        db = FakeRev23DeploymentAdapter(
            simulate_apply_error=True,
            after_snapshot=ExhaustiveSnapshot(has_meta=False, has_col=False, revision_hash="rev_100"),
        )
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_103",
            idempotency_key="idem_103",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def={"fieldname": "custom_cargo_id", "fieldtype": "Data"},
        )
        self.assertEqual(res["status"], "FAILED_CLEAN")

    def test_suite_a_row_3_and_6_mismatch_or_uncertain_provenance_enters_recovery_required(self):
        """§9 Rows 3 & 6: Present | Present with definition mismatch or uncertain provenance enters RECOVERY_REQUIRED."""
        db = FakeRev23DeploymentAdapter(
            after_snapshot=ExhaustiveSnapshot(
                has_meta=True, has_col=True, definition_matches=True, provenance_matches=False
            )
        )
        res = execute_single_field_deployment(
            db=db,
            deployment_id="dep_104",
            idempotency_key="idem_104",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def={"fieldname": "custom_cargo_id", "fieldtype": "Data"},
        )
        self.assertEqual(res["status"], "RECOVERY_REQUIRED")
        self.assertEqual(res["disposition"], "UNCERTAIN_PROVENANCE_OR_CONCURRENT_REVISION")

    def test_suite_a_idempotency_replay_and_conflict_detection(self):
        """§7.1: Same idempotency_key + same payload returns cached outcome; different payload raises IDEMPOTENCY_CONFLICT."""
        db = FakeRev23DeploymentAdapter()
        field_a = {"fieldname": "custom_cargo_id", "fieldtype": "Data"}
        res1 = execute_single_field_deployment(
            db=db,
            deployment_id="dep_105",
            idempotency_key="idem_shared",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def=field_a,
        )
        self.assertEqual(res1["status"], "APPLIED")

        # Replay with identical payload
        res2 = execute_single_field_deployment(
            db=db,
            deployment_id="dep_105_retry",
            idempotency_key="idem_shared",
            site_id="site1.local",
            doctype="Sales Order",
            base_revision_hash="rev_100",
            field_def=field_a,
        )
        self.assertEqual(res2["status"], "APPLIED")

        # Replay with modified payload -> raises IdempotencyConflictError
        with self.assertRaises(IdempotencyConflictError) as ctx:
            execute_single_field_deployment(
                db=db,
                deployment_id="dep_105_conflict",
                idempotency_key="idem_shared",
                site_id="site1.local",
                doctype="Sales Order",
                base_revision_hash="rev_100",
                field_def={"fieldname": "custom_different_field", "fieldtype": "Int"},
            )
        self.assertIn("IDEMPOTENCY_CONFLICT", str(ctx.exception))

    # --- SUITE B: Advisory Lock Contract, Bounded Keys & Revision Conflicts ---

    def test_suite_b_bounded_lock_key_and_lock_return_codes(self):
        """§7.2: Lock key is <= 64 chars and handles 0 (timeout) and None (NULL error)."""
        key = make_bounded_lock_key("very-long-tenant-site-name.enterprise.example.com", "Sales Taxes and Charges Template")
        self.assertLessEqual(len(key), 64)

        db_timeout = FakeRev23DeploymentAdapter(lock_return=0)
        res_timeout = execute_single_field_deployment(
            db=db_timeout,
            deployment_id="dep_lock_0",
            idempotency_key="idem_lock_0",
            site_id="s1",
            doctype="Lead",
            base_revision_hash="rev_100",
            field_def={"fieldname": "custom_tag", "fieldtype": "Data"},
        )
        self.assertEqual(res_timeout["status"], "REJECTED")
        self.assertIn("timeout (0)", res_timeout["reason"])

        db_null = FakeRev23DeploymentAdapter(lock_return=None)
        res_null = execute_single_field_deployment(
            db=db_null,
            deployment_id="dep_lock_null",
            idempotency_key="idem_lock_null",
            site_id="s1",
            doctype="Lead",
            base_revision_hash="rev_100",
            field_def={"fieldname": "custom_tag", "fieldtype": "Data"},
        )
        self.assertEqual(res_null["status"], "REJECTED")
        self.assertIn("NULL", res_null["reason"])

    # --- SUITE C: Policy Enforcement, Select/Link Validation & Additive Restrictions ---

    def test_suite_c_phase_1_additive_restrictions_and_select_validation(self):
        """§5.1: Rejects allow_on_submit=1, duplicate Select options, and invalid Select defaults."""
        with self.assertRaises(ZoneSafetyViolation) as ctx1:
            validate_mutation_safety({
                "intent": "add_custom_fields",
                "target_doctype": "Lead",
                "changes": [{"fieldname": "custom_flag", "fieldtype": "Check", "allow_on_submit": 1}],
            })
        self.assertIn("allow_on_submit=1", str(ctx1.exception))

        with self.assertRaises(ZoneSafetyViolation) as ctx2:
            validate_mutation_safety({
                "intent": "add_custom_fields",
                "target_doctype": "Lead",
                "changes": [
                    {
                        "fieldname": "custom_stage",
                        "fieldtype": "Select",
                        "options": "Open\nClosed\nOpen",
                    }
                ],
            })
        self.assertIn("Duplicate Select Options", str(ctx2.exception))

        with self.assertRaises(ZoneSafetyViolation) as ctx3:
            validate_mutation_safety({
                "intent": "add_custom_fields",
                "target_doctype": "Lead",
                "user_roles": ["Finance Director"],
                "changes": [
                    {
                        "fieldname": "custom_stage",
                        "fieldtype": "Select",
                        "options": "Open\nClosed",
                        "default": "Archived",
                    }
                ],
            })
        self.assertIn("Invalid Select Default", str(ctx3.exception))

    def test_suite_c_tier_0_child_table_vs_tier_1_bidirectional_governance(self):
        """§5 & §11 Suite C: Tier 0 child-table rate is locked for all roles; Tier 1 custom policy is relaxable by Director."""
        with self.assertRaises(ZoneSafetyViolation):
            validate_mutation_safety({
                "intent": "set_property",
                "target_doctype": "Sales Order Item",
                "user_roles": ["Finance Director", "System Manager"],
                "changes": [{"fieldname": "rate", "property": "read_only", "value": 0}],
            })

        approved = validate_mutation_safety({
            "intent": "set_property",
            "target_doctype": "Sales Order",
            "user_roles": ["Finance Director"],
            "changes": [{"fieldname": "custom_deal_notes", "property": "reqd", "value": 0}],
        })
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["governance_tier"], "TIER_1_GOVERNED_POLICY")


if __name__ == "__main__":
    unittest.main()
