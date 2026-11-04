"""
Unit Tests for EXRP Runtime Policy Enforcement Engine and Lifecycle Hooks (ADR-001 Rev 2.3 §4.2 & §5)
Verifies:
1. Compliant document passes on_validate and before_submit.
2. Tier 0 invariant tampering (unauthorized user setting bypass_credit_limit_check = 1) blocked with ValidationError.
3. Authorized user ('Credit Controller' / 'System Manager') passes bypass_credit_limit_check.
4. Custom approval threshold gate: High-value Sales Order (grand_total > 50000) blocked without custom_approved_by or required role.
5. Custom approval threshold passes when approved by Director.
6. before_update_after_submit prevents modifying locked custom fields after submission.
7. Integration with control_plane.py hooks.
8. Tier 0 Sales Invoice GL ledger posting and currency tampering protection.
9. Lifecycle stage filtering and policy query/management helpers.
"""

import os
import sys
import types
import unittest
from types import SimpleNamespace
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
        f.session = types.SimpleNamespace(user="Administrator")
        f.get_roles = lambda u: ["System Manager"] if u == "Administrator" else ["Sales User"]

        class _MockValidationError(Exception):
            pass

        f.ValidationError = _MockValidationError

        def _mock_throw(msg, exc=_MockValidationError):
            if isinstance(exc, type) and issubclass(exc, Exception):
                raise exc(msg)
            raise _MockValidationError(msg)

        f.throw = _mock_throw
        sys.modules["frappe"] = f
        sys.modules["frappe.utils"] = f.utils
else:
    import frappe
    if not hasattr(frappe, "ValidationError"):
        class _MockValidationError(Exception):
            pass
        frappe.ValidationError = _MockValidationError
    if not hasattr(frappe, "throw"):
        def _mock_throw(msg, exc=frappe.ValidationError):
            if isinstance(exc, type) and issubclass(exc, Exception):
                raise exc(msg)
            raise frappe.ValidationError(msg)
        frappe.throw = _mock_throw

from exrp.ai_control_plane.policy_enforcer import (
    PolicyType,
    RuntimePolicy,
    PolicyEvaluationResult,
    RuntimePolicyViolation,
    RuntimePolicyCatalog,
    policy_catalog,
)
from exrp.api.control_plane import (
    enforce_runtime_policies_on_validate,
    enforce_runtime_policies_on_submit,
    enforce_runtime_policies_on_update_after_submit,
    get_runtime_policies,
    register_runtime_policy,
    evaluate_document_policies,
    get_current_user_roles,
)


class MockFrappeDoc:
    """Mock Frappe Document supporting lifecycle inspection methods."""
    def __init__(self, doctype: str, docstatus: int = 0, **fields: Any):
        self.doctype = doctype
        self.docstatus = docstatus
        self._changed_fields = set()
        self._doc_before_save = None
        for k, v in fields.items():
            setattr(self, k, v)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        setattr(self, key, value)
        self._changed_fields.add(key)

    def has_value_changed(self, fieldname: str) -> bool:
        return fieldname in self._changed_fields

    def get_doc_before_save(self) -> Optional["MockFrappeDoc"]:
        return self._doc_before_save


class TestRuntimePolicyEnforcer(unittest.TestCase):
    """Comprehensive test suite for ADR-001 Rev 2.3 Runtime Policy Enforcement."""

    def setUp(self):
        # Reset the global policy catalog before each test
        policy_catalog.reset()

    def tearDown(self):
        policy_catalog.reset()

    # --------------------------------------------------------------------------
    # Test 1: Compliant document passes on_validate and before_submit
    # --------------------------------------------------------------------------
    def test_01_compliant_document_passes_validate_and_submit(self):
        """Test 1: Compliant document passes on_validate and before_submit."""
        so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=15000.0,
            bypass_credit_limit_check=0,
            currency="USD",
        )
        user_roles = ["Sales User"]

        # Validate stage
        val_result = policy_catalog.evaluate_validate(so, user_roles=user_roles)
        self.assertTrue(val_result.allowed)
        self.assertEqual(len(val_result.violated_policies), 0)

        # Submit stage
        submit_result = policy_catalog.evaluate_submit(so, user_roles=user_roles)
        self.assertTrue(submit_result.allowed)
        self.assertEqual(len(submit_result.violated_policies), 0)

    # --------------------------------------------------------------------------
    # Test 2: Tier 0 invariant tampering blocked with ValidationError
    # --------------------------------------------------------------------------
    def test_02_tier_0_invariant_tampering_blocked(self):
        """Test 2: Tier 0 invariant tampering (unauthorized bypass_credit_limit_check = 1) blocked with ValidationError."""
        so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=15000.0,
            bypass_credit_limit_check=1,
        )
        unauthorized_roles = ["Sales User", "Sales Manager"]

        # evaluate_validate should raise RuntimePolicyViolation (which inherits from frappe.ValidationError)
        with self.assertRaises(RuntimePolicyViolation) as ctx:
            policy_catalog.evaluate_validate(so, user_roles=unauthorized_roles)

        err_msg = str(ctx.exception)
        self.assertIn("TIER0_SO_CREDIT_LIMIT_BYPASS", err_msg)
        self.assertIn("Credit Controller", err_msg)

        # Confirm non-raising evaluation reflects violation
        eval_result = policy_catalog.evaluate_validate(so, user_roles=unauthorized_roles, raise_exception=False)
        self.assertFalse(eval_result.allowed)
        self.assertIn("TIER0_SO_CREDIT_LIMIT_BYPASS", eval_result.violated_policies)

    # --------------------------------------------------------------------------
    # Test 3: Authorized user passes bypass_credit_limit_check
    # --------------------------------------------------------------------------
    def test_03_authorized_user_passes_credit_limit_bypass(self):
        """Test 3: Authorized user ('Credit Controller' or 'System Manager') passes bypass_credit_limit_check."""
        so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=15000.0,
            bypass_credit_limit_check=1,
        )

        # Authorized via Credit Controller
        res_cc = policy_catalog.evaluate_validate(so, user_roles=["Credit Controller", "Sales User"])
        self.assertTrue(res_cc.allowed)

        # Authorized via System Manager
        res_sm = policy_catalog.evaluate_validate(so, user_roles=["System Manager"])
        self.assertTrue(res_sm.allowed)

    # --------------------------------------------------------------------------
    # Test 4: Custom approval threshold gate blocked without approval/role
    # --------------------------------------------------------------------------
    def test_04_custom_approval_threshold_gate_blocked(self):
        """Test 4: High-value Sales Order (grand_total > 50000) blocked without custom_approved_by or required role."""
        threshold_policy = RuntimePolicy(
            policy_id="POLICY_SO_HIGH_VALUE_THRESHOLD",
            doctype="Sales Order",
            policy_type=PolicyType.THRESHOLD_GATE,
            target_field="custom_approved_by",
            governance_tier=1,
            condition_expr="grand_total > 50000",
            required_role="Finance Director, Operations Director",
            error_message="High-value Sales Orders exceeding 50,000 require approval by an authorized Director.",
            active=True,
        )
        policy_catalog.register_policy(threshold_policy)

        # High-value order without approval or required role
        so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=75000.0,
            custom_approved_by=None,
        )
        unauthorized_roles = ["Sales User", "Accounts User"]

        with self.assertRaises(RuntimePolicyViolation) as ctx:
            policy_catalog.evaluate_submit(so, user_roles=unauthorized_roles)

        err_msg = str(ctx.exception)
        self.assertIn("POLICY_SO_HIGH_VALUE_THRESHOLD", err_msg)
        self.assertIn("Director", err_msg)

    # --------------------------------------------------------------------------
    # Test 5: Custom approval threshold passes when approved by Director
    # --------------------------------------------------------------------------
    def test_05_custom_approval_threshold_passes_when_approved(self):
        """Test 5: Custom approval threshold passes when approved by Director or caller is Director."""
        threshold_policy = RuntimePolicy(
            policy_id="POLICY_SO_HIGH_VALUE_THRESHOLD",
            doctype="Sales Order",
            policy_type=PolicyType.THRESHOLD_GATE,
            target_field="custom_approved_by",
            governance_tier=1,
            condition_expr="grand_total > 50000",
            required_role="Finance Director, Operations Director",
            error_message="High-value Sales Orders exceeding 50,000 require approval by an authorized Director.",
            active=True,
        )
        policy_catalog.register_policy(threshold_policy)

        # 5A: Approved via target_field (custom_approved_by populated by Director)
        so_with_approval = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=75000.0,
            custom_approved_by="director@example.com",
        )
        res_a = policy_catalog.evaluate_submit(so_with_approval, user_roles=["Sales User"])
        self.assertTrue(res_a.allowed)

        # 5B: Approved via caller role (Finance Director submitting)
        so_unapproved = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=75000.0,
            custom_approved_by=None,
        )
        res_b = policy_catalog.evaluate_submit(so_unapproved, user_roles=["Finance Director"])
        self.assertTrue(res_b.allowed)

        # 5C: Approved via Operations Director
        res_c = policy_catalog.evaluate_submit(so_unapproved, user_roles=["Operations Director"])
        self.assertTrue(res_c.allowed)

    # --------------------------------------------------------------------------
    # Test 6: before_update_after_submit prevents modifying locked fields
    # --------------------------------------------------------------------------
    def test_06_before_update_after_submit_prevents_modifying_locked_fields(self):
        """Test 6: before_update_after_submit prevents modifying locked custom fields after submission."""
        lock_policy = RuntimePolicy(
            policy_id="POLICY_SO_LOCK_PO_REFERENCE",
            doctype="Sales Order",
            policy_type=PolicyType.SUBMIT_LOCK,
            target_field="custom_po_reference",
            governance_tier=1,
            error_message="Cannot modify 'custom_po_reference' after Sales Order has been submitted.",
            active=True,
        )
        policy_catalog.register_policy(lock_policy)

        # Submitted document with custom_po_reference modified
        submitted_so_tampered = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=1,
            custom_po_reference="PO-NEW-TAMPERED",
        )
        # Mark field as changed
        submitted_so_tampered._changed_fields.add("custom_po_reference")

        with self.assertRaises(RuntimePolicyViolation) as ctx:
            policy_catalog.evaluate_update_after_submit(
                submitted_so_tampered,
                user_roles=["Sales User"],
            )

        err_msg = str(ctx.exception)
        self.assertIn("POLICY_SO_LOCK_PO_REFERENCE", err_msg)
        self.assertIn("Cannot modify 'custom_po_reference'", err_msg)

        # Unmodified field on submitted document passes
        submitted_so_clean = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=1,
            custom_po_reference="PO-ORIGINAL",
            notes="Updated delivery instructions only",
        )
        submitted_so_clean._changed_fields.add("notes")

        clean_res = policy_catalog.evaluate_update_after_submit(
            submitted_so_clean,
            user_roles=["Sales User"],
        )
        self.assertTrue(clean_res.allowed)

        # Ensure SUBMIT_LOCK does NOT block changes during initial draft validate
        draft_so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            custom_po_reference="PO-DRAFT",
        )
        draft_so._changed_fields.add("custom_po_reference")
        draft_res = policy_catalog.evaluate_validate(draft_so, user_roles=["Sales User"])
        self.assertTrue(draft_res.allowed)

    # --------------------------------------------------------------------------
    # Test 7: Integration with control_plane.py hooks
    # --------------------------------------------------------------------------
    def test_07_integration_with_control_plane_hooks(self):
        """Test 7: Integration with control_plane.py hooks and get_current_user_roles."""
        # 7A: Compliant document passes all hooks
        so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=10000.0,
            bypass_credit_limit_check=0,
        )
        res_v = enforce_runtime_policies_on_validate(so, user_roles=["Sales User"])
        self.assertTrue(res_v.allowed)

        res_s = enforce_runtime_policies_on_submit(so, user_roles=["Sales User"])
        self.assertTrue(res_s.allowed)

        # 7B: Tampered document raises exception via validate hook
        so_tampered = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            grand_total=10000.0,
            bypass_credit_limit_check=1,
        )
        with self.assertRaises(RuntimePolicyViolation) as ctx:
            enforce_runtime_policies_on_validate(so_tampered, user_roles=["Sales User"])
        self.assertIn("TIER0_SO_CREDIT_LIMIT_BYPASS", str(ctx.exception))

        # 7C: Tampered document raises exception via submit hook
        with self.assertRaises(RuntimePolicyViolation):
            enforce_runtime_policies_on_submit(so_tampered, user_roles=["Sales User"])

        # 7D: Update after submit hook enforcement
        lock_policy = RuntimePolicy(
            policy_id="POLICY_SO_LOCK_NOTES",
            doctype="Sales Order",
            policy_type=PolicyType.SUBMIT_LOCK,
            target_field="custom_internal_notes",
            governance_tier=1,
            error_message="Cannot modify internal notes after submission.",
            active=True,
        )
        register_runtime_policy(lock_policy)

        submitted_so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=1,
            custom_internal_notes="Unauthorized change",
        )
        submitted_so._changed_fields.add("custom_internal_notes")

        with self.assertRaises(RuntimePolicyViolation) as ctx:
            enforce_runtime_policies_on_update_after_submit(submitted_so, user_roles=["Sales User"])
        self.assertIn("POLICY_SO_LOCK_NOTES", str(ctx.exception))

    # --------------------------------------------------------------------------
    # Test 8: Tier 0 Sales Invoice GL posting & currency tampering protection
    # --------------------------------------------------------------------------
    def test_08_sales_invoice_tier_0_currency_and_gl_protection(self):
        """Test 8: Sales Invoice GL ledger posting and currency tampering protection."""
        # 8A: Compliant Sales Invoice
        si_clean = MockFrappeDoc(
            doctype="Sales Invoice",
            docstatus=0,
            conversion_rate=1.0,
            party_account_currency="USD",
            debit_to="1310 - Debtors - EX",
        )
        res_clean = policy_catalog.evaluate_validate(si_clean, user_roles=["Accounts User"])
        self.assertTrue(res_clean.allowed)

        # 8B: Currency conversion rate <= 0 tampering
        si_tampered_rate = MockFrappeDoc(
            doctype="Sales Invoice",
            docstatus=0,
            conversion_rate=-0.5,
        )
        with self.assertRaises(RuntimePolicyViolation) as ctx:
            policy_catalog.evaluate_validate(si_tampered_rate, user_roles=["Accounts User"])
        self.assertIn("TIER0_SI_CURRENCY_TAMPERING", str(ctx.exception))

        # 8C: Unauthorized user modifying currency conversion rate
        si_rate_override = MockFrappeDoc(
            doctype="Sales Invoice",
            docstatus=0,
            conversion_rate=1.45,
        )
        si_rate_override._changed_fields.add("conversion_rate")
        with self.assertRaises(RuntimePolicyViolation) as ctx:
            policy_catalog.evaluate_validate(si_rate_override, user_roles=["Sales User"])
        self.assertIn("TIER0_SI_CURRENCY_OVERRIDE", str(ctx.exception))

        # Authorized Accounts Manager can modify conversion rate
        res_mgr = policy_catalog.evaluate_validate(si_rate_override, user_roles=["Accounts Manager"])
        self.assertTrue(res_mgr.allowed)

        # 8D: GL ledger override protection
        si_gl_tampered = MockFrappeDoc(
            doctype="Sales Invoice",
            docstatus=0,
            override_gl_posting=1,
        )
        with self.assertRaises(RuntimePolicyViolation) as ctx:
            policy_catalog.evaluate_validate(si_gl_tampered, user_roles=["Accounts User"])
        self.assertIn("TIER0_SI_GL_POSTING_PROTECTION", str(ctx.exception))

    # --------------------------------------------------------------------------
    # Test 9: Policy Query & Management Helpers
    # --------------------------------------------------------------------------
    def test_09_policy_query_and_management_helpers(self):
        """Test 9: Verify get_runtime_policies and evaluate_document_policies helpers."""
        # Query policies for Sales Order
        so_policies = get_runtime_policies(doctype="Sales Order")
        self.assertTrue(len(so_policies) >= 1)
        self.assertTrue(any(p["policy_id"] == "TIER0_SO_CREDIT_LIMIT_BYPASS" for p in so_policies))

        # Query stage-filtered policies
        submit_policies = get_runtime_policies(doctype="Sales Order", stage="before_submit")
        self.assertTrue(len(submit_policies) >= 1)

        # Evaluate document preview dict without saving
        doc_preview = {
            "doctype": "Sales Order",
            "grand_total": 20000.0,
            "bypass_credit_limit_check": 1,
        }
        res_preview = evaluate_document_policies(
            doctype="Sales Order",
            doc=doc_preview,
            stage="validate",
            user_roles=["Sales User"],
        )
        self.assertFalse(res_preview["allowed"])
        self.assertIn("TIER0_SO_CREDIT_LIMIT_BYPASS", res_preview["violated_policies"])

    # --------------------------------------------------------------------------
    # Test 10: Inactive policy is skipped
    # --------------------------------------------------------------------------
    def test_10_inactive_policy_skipped(self):
        """Test 10: Inactive policies (active=False) are not evaluated."""
        inactive_policy = RuntimePolicy(
            policy_id="POLICY_INACTIVE_BLOCK",
            doctype="Sales Order",
            policy_type=PolicyType.FIELD_CONSTRAINT,
            target_field="custom_notes",
            governance_tier=1,
            condition_expr="custom_notes is not None",
            error_message="Notes are prohibited.",
            active=False,
        )
        policy_catalog.register_policy(inactive_policy)

        so = MockFrappeDoc(
            doctype="Sales Order",
            docstatus=0,
            custom_notes="Some note",
        )
        res = policy_catalog.evaluate_validate(so, user_roles=["Sales User"])
        self.assertTrue(res.allowed)


if __name__ == "__main__":
    unittest.main()
