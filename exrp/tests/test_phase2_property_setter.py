"""
Unit Tests for Phase 2 Property Setter Mutation Engine and 1-Click Soft-Rollback / Quarantine (ADR-001 Rev 2.3)
Verifies:
1. Property Setter deployment for labels, descriptions, and reqd (§5, §8).
2. Tier 0 invariant rejection on Property Setter (cannot hide rate or credit limit, cannot unlock read_only).
3. 1-click rollback of Property Setter restoring original state (restoring baseline value or removing setter).
4. 1-click quarantine of Custom Field (setting hidden=1, reqd=0) without physically dropping the database column (§9.1).
5. Rejection of unauthorized rollback attempts (strictly enforcing System Manager, Finance Director, Operations Director).
6. Fail-closed audit durability before mutation and MariaDB GET_LOCK advisory lock protection (§7.2, §8).
7. Whitelisted API endpoints in exrp.api.control_plane (apply_property_setter_change & revert_configuration_change).
"""

import json
import os
import sys
import types
import unittest
from typing import Any, Dict, List, Optional

# Ensure repository root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Safe Frappe mocking for isolated standalone unit test runs
if "frappe" not in sys.modules:
    try:
        import frappe
    except ImportError:
        f = types.ModuleType("frappe")
        f.utils = types.ModuleType("frappe.utils")
        f.utils.cstr = lambda x: str(x)
        f.local = types.SimpleNamespace(site="test_site.local")
        sys.modules["frappe"] = f
        sys.modules["frappe.utils"] = f.utils

try:
    import frappe
    if hasattr(frappe, "local"):
        if not hasattr(frappe.local, "flags"):
            frappe.local.flags = frappe._dict() if hasattr(frappe, "_dict") else types.SimpleNamespace()
        frappe.local.flags.in_test = True
except Exception:
    pass

from exrp.ai_control_plane.safety_guardrails import (
    TIER_1_GOVERNANCE_ROLES,
    validate_mutation_safety,
    ZoneSafetyViolation,
)
from exrp.ai_control_plane.schema_reconciler import make_bounded_lock_key
from exrp.ai_control_plane.property_setter_engine import (
    execute_property_setter_deployment,
    normalize_property_value,
)
from exrp.ai_control_plane.rollback_engine import (
    AUTHORIZED_ROLLBACK_ROLES,
    execute_rollback,
)
from exrp.api.control_plane import (
    FrappeDeploymentAdapter,
    apply_configuration_change,
    apply_property_setter_change,
    revert_configuration_change,
)


class TestPhase2PropertySetterAndRollback(unittest.TestCase):
    """Test suite for Phase 2 Property Setter Engine & 1-Click Rollback/Quarantine under ADR-001 Rev 2.3."""

    def setUp(self):
        FrappeDeploymentAdapter.reset_in_memory_state()
        self.adapter = FrappeDeploymentAdapter()

    def tearDown(self):
        FrappeDeploymentAdapter.reset_in_memory_state()

    # --- 1. PROPERTY SETTER DEPLOYMENT TESTS ---

    def test_1_property_setter_deployment_label(self):
        """
        Requirement 1: Test Property Setter deployment for labels.
        Verifies:
        - Evaluates safety (Presentation property: METADATA_ONLY, TIER_2).
        - Acquires <= 64 char advisory lock.
        - Persists baseline snapshot in audit journal before mutation.
        - Applies Property Setter and clears cache.
        - Verifies effective metadata reflection and returns status APPLIED, PROPERTY_SETTER_APPLIED.
        """
        outcome = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_label_001",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="delivery_date",
            property_name="label",
            value="Target Dispatch Date",
            property_type="Data",
            user_roles=["System Manager"],
        )

        self.assertTrue(outcome["success"], f"Deployment failed: {outcome}")
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "PROPERTY_SETTER_APPLIED")
        self.assertEqual(outcome["doctype"], "Sales Order")
        self.assertEqual(outcome["fieldname"], "delivery_date")
        self.assertEqual(outcome["property_name"], "label")
        self.assertEqual(outcome["value"], "Target Dispatch Date")
        self.assertTrue(self.adapter.cache_cleared)

        # Verify reflected in adapter state
        ps = self.adapter.get_property_setter("Sales Order", "delivery_date", "label")
        self.assertIsNotNone(ps)
        self.assertEqual(ps["value"], "Target Dispatch Date")

        # Verify audit journal has baseline snapshot
        record = self.adapter.get_deployment_record("dep_ps_label_001")
        self.assertIsNotNone(record)
        self.assertIn("baseline_snapshot", record)
        self.assertEqual(record["status"], "APPLIED")

    def test_2_property_setter_deployment_description(self):
        """
        Requirement 1: Test Property Setter deployment for descriptions.
        """
        outcome = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_desc_001",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="po_no",
            property_name="description",
            value="Official Purchase Order number provided by the customer.",
            property_type="Text",
            user_roles=["Operations Director"],
        )

        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "PROPERTY_SETTER_APPLIED")
        self.assertEqual(outcome["value"], "Official Purchase Order number provided by the customer.")

        ps = self.adapter.get_property_setter("Sales Order", "po_no", "description")
        self.assertIsNotNone(ps)
        self.assertEqual(ps["value"], "Official Purchase Order number provided by the customer.")

    def test_3_property_setter_deployment_reqd(self):
        """
        Requirement 1: Test Property Setter deployment for reqd (governed semantic property).
        Verifies:
        - Setting reqd=1 requires Tier 1 authority (System Manager, Finance Director, Operations Director).
        - Successfully sets reqd=1 and normalizes Check value to 1.
        """
        # Authorized role: Finance Director -> succeeds
        outcome = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_reqd_001",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="po_no",
            property_name="reqd",
            value=1,
            property_type="Check",
            user_roles=["Finance Director"],
        )

        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "PROPERTY_SETTER_APPLIED")
        self.assertEqual(outcome["value"], 1)

        ps = self.adapter.get_property_setter("Sales Order", "po_no", "reqd")
        self.assertIsNotNone(ps)
        self.assertEqual(ps["value"], 1)

        # Unauthorized role: Operator -> rejected by policy compiler
        outcome_unauth = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_reqd_002",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="po_no",
            property_name="reqd",
            value=1,
            property_type="Check",
            user_roles=["Operator"],
        )
        self.assertFalse(outcome_unauth["success"])
        self.assertEqual(outcome_unauth["status"], "REJECTED")
        self.assertEqual(outcome_unauth["disposition"], "ZONE_SAFETY_VIOLATION")
        self.assertIn("Governance Authority Violation", outcome_unauth["reason"])

    # --- 2. TIER 0 INVARIANT REJECTION TESTS ---

    def test_4_tier_0_invariant_rejection_cannot_hide_rate_or_credit_limit(self):
        """
        Requirement 2: Test Tier 0 invariant rejection on Property Setter:
        EXRP cannot weaken or alter protected financial/security definitions (ADR-001 §5 & §11 Suite C):
        - Cannot hide 'rate' on Sales Order / child tables.
        - Cannot hide 'credit_limit' or accounting controls.
        - Cannot unlock 'read_only' or relax 'reqd' on standard protected fields.
        """
        # Attempt 1: Cannot hide 'rate'
        res_rate = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_tier0_rate",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="rate",
            property_name="hidden",
            value=1,
            property_type="Check",
            user_roles=["System Manager"],
        )
        self.assertFalse(res_rate["success"])
        self.assertEqual(res_rate["status"], "REJECTED")
        self.assertEqual(res_rate["disposition"], "ZONE_SAFETY_VIOLATION")
        self.assertIn("Tier 0 Invariant Protection Violation", res_rate["reason"])
        self.assertIn("rate", res_rate["reason"])

        # Attempt 2: Cannot hide 'credit_limit'
        res_credit = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_tier0_credit",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="credit_limit",
            property_name="hidden",
            value=1,
            property_type="Check",
            user_roles=["System Manager"],
        )
        self.assertFalse(res_credit["success"])
        self.assertEqual(res_credit["status"], "REJECTED")
        self.assertEqual(res_credit["disposition"], "ZONE_SAFETY_VIOLATION")
        self.assertIn("Tier 0 Invariant Protection Violation", res_credit["reason"])
        self.assertIn("credit_limit", res_credit["reason"])

        # Attempt 3: Cannot unlock read_only on protected field 'rate'
        res_readonly = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_tier0_readonly",
            site_id="site1.local",
            doctype="Sales Order Item",
            fieldname="rate",
            property_name="read_only",
            value=0,
            user_roles=["Finance Director"],
        )
        self.assertFalse(res_readonly["success"])
        self.assertEqual(res_readonly["status"], "REJECTED")
        self.assertIn("Tier 0", res_readonly["reason"])

        # Attempt 4: raise_on_violation=True raises ZoneSafetyViolation
        with self.assertRaises(ZoneSafetyViolation):
            execute_property_setter_deployment(
                db=self.adapter,
                deployment_id="dep_ps_tier0_raise",
                site_id="site1.local",
                doctype="Sales Order",
                fieldname="rate",
                property_name="hidden",
                value=1,
                user_roles=["System Manager"],
                raise_on_violation=True,
            )

    # --- 3. 1-CLICK ROLLBACK OF PROPERTY SETTER TESTS ---

    def test_5_rollback_property_setter_restoring_baseline_or_removing_setter(self):
        """
        Requirement 3: Test 1-click rollback of Property Setter restoring original state.
        Case A: No baseline Property Setter existed previously -> deletes the Property Setter.
        Case B: An existing Property Setter existed prior to mutation -> restores baseline value.
        """
        # --- Case A: No baseline existed previously ---
        dep_res = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_case_a",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="customer_address",
            property_name="label",
            value="Client Address",
            user_roles=["System Manager"],
        )
        self.assertTrue(dep_res["success"])
        # Confirm Property Setter was created
        ps_before_rb = self.adapter.get_property_setter("Sales Order", "customer_address", "label")
        self.assertIsNotNone(ps_before_rb)
        self.assertEqual(ps_before_rb["value"], "Client Address")

        # Rollback Case A
        rb_res = execute_rollback(
            deployment_id="dep_ps_case_a",
            caller_roles=["System Manager"],
            db=self.adapter,
        )
        self.assertTrue(rb_res["success"])
        self.assertEqual(rb_res["status"], "ROLLED_BACK")
        self.assertEqual(rb_res["disposition"], "PROPERTY_SETTER_REMOVED")
        self.assertTrue(rb_res["removed_setter"])
        self.assertTrue(self.adapter.cache_cleared)

        # Confirm Property Setter has been removed
        ps_after_rb = self.adapter.get_property_setter("Sales Order", "customer_address", "label")
        self.assertIsNone(ps_after_rb)

        # Confirm audit journal status is ROLLED_BACK
        audit_rec = self.adapter.get_deployment_record("dep_ps_case_a")
        self.assertEqual(audit_rec["status"], "ROLLED_BACK")

        # --- Case B: Baseline Property Setter already existed with prior value ---
        # Pre-seed an existing Property Setter: label = "Buyer Address"
        self.adapter.apply_property_setter(
            doctype="Sales Order",
            fieldname="shipping_address_name",
            property_name="label",
            value="Buyer Address",
            property_type="Data",
        )

        # Deploy change: label = "Consignee Address"
        dep_res_b = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_case_b",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="shipping_address_name",
            property_name="label",
            value="Consignee Address",
            user_roles=["System Manager"],
        )
        self.assertTrue(dep_res_b["success"])
        self.assertEqual(
            self.adapter.get_property_setter("Sales Order", "shipping_address_name", "label")["value"],
            "Consignee Address",
        )

        # Rollback Case B -> should restore "Buyer Address"
        rb_res_b = execute_rollback(
            deployment_id="dep_ps_case_b",
            caller_roles=["Operations Director"],
            db=self.adapter,
        )
        self.assertTrue(rb_res_b["success"])
        self.assertEqual(rb_res_b["status"], "ROLLED_BACK")
        self.assertEqual(rb_res_b["disposition"], "PROPERTY_SETTER_RESTORED_BASELINE")
        self.assertEqual(rb_res_b["restored_value"], "Buyer Address")

        # Confirm Property Setter is restored to "Buyer Address"
        restored_ps = self.adapter.get_property_setter("Sales Order", "shipping_address_name", "label")
        self.assertIsNotNone(restored_ps)
        self.assertEqual(restored_ps["value"], "Buyer Address")

    # --- 4. 1-CLICK QUARANTINE OF CUSTOM FIELD TESTS ---

    def test_6_quarantine_custom_field_without_dropping_column(self):
        """
        Requirement 4: Test 1-click quarantine of Custom Field (hidden=1, reqd=0) without dropping column.
        ADR-001 Rev 2.3 (§9.1):
        - ADR-001 strictly forbids physical DROP COLUMN in Phase 1 & 2 to prevent catastrophic data loss.
        - Soft-quarantines the field by creating Property Setters with hidden = 1 and reqd = 0.
        - Marks audit status QUARANTINED.
        - Physical table column tabSales Order.custom_tracking_code remains intact!
        """
        # Step 1: Deploy a custom field
        cf_def = {
            "fieldname": "custom_tracking_code",
            "label": "Tracking Code",
            "fieldtype": "Data",
        }
        dep_outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_cf_track_001",
            field_def=cf_def,
            adapter=self.adapter,
            user_roles=["System Manager"],
        )
        self.assertTrue(dep_outcome["success"])
        self.assertEqual(dep_outcome["status"], "APPLIED")

        # Verify physical column exists in table
        cols_before = self.adapter.get_table_columns_description("Sales Order")
        self.assertTrue(any(c.name == "custom_tracking_code" for c in cols_before))

        # Step 2: Execute 1-click rollback/quarantine
        quarantine_res = execute_rollback(
            deployment_id="dep_cf_track_001",
            caller_roles=["Finance Director"],
            db=self.adapter,
        )

        self.assertTrue(quarantine_res["success"])
        self.assertEqual(quarantine_res["status"], "QUARANTINED")
        self.assertEqual(quarantine_res["disposition"], "CUSTOM_FIELD_QUARANTINED")
        self.assertFalse(quarantine_res["physical_column_dropped"])
        self.assertEqual(quarantine_res["doctype"], "Sales Order")
        self.assertEqual(quarantine_res["fieldname"], "custom_tracking_code")

        # Verify physical database column is NOT dropped
        cols_after = self.adapter.get_table_columns_description("Sales Order")
        self.assertTrue(
            any(c.name == "custom_tracking_code" for c in cols_after),
            "Physical column must NOT be dropped on quarantine (ADR-001 §9.1)!",
        )

        # Verify Property Setters: hidden=1 and reqd=0
        ps_hidden = self.adapter.get_property_setter("Sales Order", "custom_tracking_code", "hidden")
        self.assertIsNotNone(ps_hidden)
        self.assertEqual(ps_hidden["value"], 1)

        ps_reqd = self.adapter.get_property_setter("Sales Order", "custom_tracking_code", "reqd")
        self.assertIsNotNone(ps_reqd)
        self.assertEqual(ps_reqd["value"], 0)

        # Verify audit status is QUARANTINED
        record = self.adapter.get_deployment_record("dep_cf_track_001")
        self.assertEqual(record["status"], "QUARANTINED")
        self.assertTrue(self.adapter.cache_cleared)

    # --- 5. REJECTION OF UNAUTHORIZED ROLLBACK ATTEMPTS ---

    def test_7_rejection_of_unauthorized_rollback_attempts(self):
        """
        Requirement 5: Test rejection of unauthorized rollback attempts.
        Only System Manager, Finance Director, Operations Director can revert.
        """
        # Setup a deployment record
        self.adapter.persist_prepare_and_audit_intent({
            "deployment_id": "dep_auth_test_001",
            "doctype": "Sales Order",
            "fieldname": "custom_test_field",
            "deployment_type": "custom_field",
            "status": "APPLIED",
            "site_id": "site1.local",
            "idempotency_key": "idemp_auth_001",
            "payload_hash": "hash001",
        })

        # Test Accounts User -> Rejected
        res_accounts = execute_rollback(
            deployment_id="dep_auth_test_001",
            caller_roles=["Accounts User"],
            db=self.adapter,
        )
        self.assertFalse(res_accounts["success"])
        self.assertEqual(res_accounts["status"], "REJECTED")
        self.assertEqual(res_accounts["stage"], "AUTHORIZATION")
        self.assertEqual(res_accounts["disposition"], "UNAUTHORIZED_ROLE")

        # Test Operator -> Rejected
        res_operator = execute_rollback(
            deployment_id="dep_auth_test_001",
            caller_roles=["Operator"],
            db=self.adapter,
        )
        self.assertFalse(res_operator["success"])
        self.assertEqual(res_operator["status"], "REJECTED")
        self.assertEqual(res_operator["disposition"], "UNAUTHORIZED_ROLE")

        # Test Empty roles -> Rejected
        res_empty = execute_rollback(
            deployment_id="dep_auth_test_001",
            caller_roles=[],
            db=self.adapter,
        )
        self.assertFalse(res_empty["success"])
        self.assertEqual(res_empty["status"], "REJECTED")

        # Test raise_on_unauthorized=True raises PermissionError
        with self.assertRaises(PermissionError):
            execute_rollback(
                deployment_id="dep_auth_test_001",
                caller_roles=["Guest"],
                db=self.adapter,
                raise_on_unauthorized=True,
            )

        # Test all 3 authorized roles succeed
        for role in ["System Manager", "Finance Director", "Operations Director"]:
            dep_id = f"dep_auth_{role.lower().replace(' ', '_')}"
            self.adapter.persist_prepare_and_audit_intent({
                "deployment_id": dep_id,
                "doctype": "Sales Order",
                "fieldname": f"custom_{role.lower().replace(' ', '_')}",
                "deployment_type": "custom_field",
                "status": "APPLIED",
                "site_id": "site1.local",
                "idempotency_key": f"idemp_{dep_id}",
                "payload_hash": f"hash_{dep_id}",
            })
            ok_res = execute_rollback(
                deployment_id=dep_id,
                caller_roles=[role],
                db=self.adapter,
            )
            self.assertTrue(ok_res["success"], f"Role '{role}' was unexpectedly rejected!")
            self.assertEqual(ok_res["status"], "QUARANTINED")

    # --- 6. LOCK CONTENTION, AUDIT DURABILITY & EDGE CASES ---

    def test_8_rollback_nonexistent_deployment_fails_clean(self):
        """Rollback of unknown deployment_id returns DEPLOYMENT_NOT_FOUND."""
        res = execute_rollback(
            deployment_id="dep_unknown_404",
            caller_roles=["System Manager"],
            db=self.adapter,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "REJECTED")
        self.assertEqual(res["disposition"], "DEPLOYMENT_NOT_FOUND")

    def test_9_property_setter_lock_contention(self):
        """MariaDB GET_LOCK contention rejects deployment with LOCK_CONTENTION_OR_TIMEOUT."""
        lock_key = make_bounded_lock_key("site1.local", "Sales Order")
        self.adapter.acquire_advisory_lock(lock_key, wait_seconds=5)

        res = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_lock_001",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="customer",
            property_name="label",
            value="Client Name",
            user_roles=["System Manager"],
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "REJECTED")
        self.assertEqual(res["stage"], "ACQUIRE")
        self.assertEqual(res["disposition"], "LOCK_CONTENTION_OR_TIMEOUT")

        # Release lock and retry -> succeeds
        self.adapter.release_advisory_lock(lock_key)
        res_ok = execute_property_setter_deployment(
            db=self.adapter,
            deployment_id="dep_ps_lock_002",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="customer",
            property_name="label",
            value="Client Name",
            user_roles=["System Manager"],
        )
        self.assertTrue(res_ok["success"])
        self.assertEqual(res_ok["status"], "APPLIED")

    def test_10_property_setter_fail_closed_on_prepare_audit_error(self):
        """Fail-closed: If audit DB write fails before mutation, deployment is aborted with FAILED_CLEAN."""
        fail_adapter = FrappeDeploymentAdapter(simulate_prepare_error=True)
        res = execute_property_setter_deployment(
            db=fail_adapter,
            deployment_id="dep_ps_fail_audit",
            site_id="site1.local",
            doctype="Sales Order",
            fieldname="title",
            property_name="label",
            value="Order Title",
            user_roles=["System Manager"],
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "FAILED_CLEAN")
        self.assertEqual(res["stage"], "PREPARE")
        self.assertEqual(res["disposition"], "AUDIT_PREPARE_FAILED")
        self.assertIn("Fail-closed", res["reason"])
        self.assertFalse(fail_adapter.apply_called)

    # --- 7. WHITELISTED API ENDPOINTS IN CONTROL_PLANE.PY ---

    def test_11_apply_property_setter_change_api_endpoint(self):
        """Tests apply_property_setter_change API RPC endpoint."""
        res = apply_property_setter_change(
            doctype="Sales Order",
            deployment_id="dep_api_ps_001",
            fieldname="transaction_date",
            property_name="label",
            value="Order Booking Date",
            user_roles=["System Manager"],
            adapter=self.adapter,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "APPLIED")
        self.assertEqual(res["disposition"], "PROPERTY_SETTER_APPLIED")
        self.assertIn("execution_time_ms", res)

    def test_12_revert_configuration_change_api_endpoint(self):
        """Tests revert_configuration_change API RPC endpoint."""
        # 1. Apply property setter change
        dep_res = apply_property_setter_change(
            doctype="Sales Order",
            deployment_id="dep_api_ps_revert",
            fieldname="remarks",
            property_name="label",
            value="Internal Notes",
            user_roles=["System Manager"],
            adapter=self.adapter,
        )
        self.assertTrue(dep_res["success"])

        # 2. Revert configuration change via API
        rev_res = revert_configuration_change(
            deployment_id="dep_api_ps_revert",
            caller_roles=["System Manager"],
            adapter=self.adapter,
        )
        self.assertTrue(rev_res["success"])
        self.assertEqual(rev_res["status"], "ROLLED_BACK")
        self.assertEqual(rev_res["disposition"], "PROPERTY_SETTER_REMOVED")


if __name__ == "__main__":
    unittest.main()
