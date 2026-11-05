"""
Unit Tests for Phase 4 Declarative Report Engine, Cross-Document Policy Catalog, and 1-Click Rollback
Implements PRD-001 (Declarative Primitive 4: Report Builder) and ADR-001 / ADR-006:
1. Test 1: Valid Report Builder definition passes validation.
2. Test 2: Rejection of system internal DocTypes (User, DocType).
3. Test 3: Rejection of invalid operators / SQL injection attempt.
4. Test 4: Report preview data generation with sample rows.
5. Test 5: Successful report deployment creates Frappe Report with Report Builder JSON.
6. Test 6: Rejection of unauthorized roles.
7. Test 7: 1-Click Rollback deactivates report (disabled = 1).
8. Test 8: Cross-document policy blocks Delivery Note with unsubmitted Sales Order.
9. Test 9: Cross-document policy passes Delivery Note with submitted Sales Order.
10. Test 10: Idempotency of report deployment (identical payload vs conflicting payload).
11. Test 11: End-to-end API call via control_plane.py (propose, apply, revert).
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

from exrp.ai_control_plane.report_engine import (
    ReportColumn,
    ReportFilter,
    ReportChartConfig,
    ReportDefinition,
    ReportValidationResult,
    validate_report_definition,
    get_report_preview_data,
    execute_report_deployment,
    AUTHORIZED_REPORT_ROLES,
)
from exrp.ai_control_plane.cross_doc_policy import (
    CrossDocPolicy,
    CrossDocPolicyCatalog,
    cross_doc_catalog,
)
from exrp.ai_control_plane.policy_enforcer import policy_catalog
from exrp.ai_control_plane.rollback_engine import execute_rollback
from exrp.ai_control_plane.schema_reconciler import IdempotencyConflictError
from exrp.api.control_plane import (
    FrappeDeploymentAdapter,
    apply_report_change,
    revert_configuration_change,
    propose_configuration_change,
)


class TestPhase4ReportEngine(unittest.TestCase):
    """Test suite for Phase 4 Declarative Report Engine & Cross-Document Policies."""

    def setUp(self):
        FrappeDeploymentAdapter.reset_in_memory_state()
        cross_doc_catalog.clear_mock_documents()
        self.adapter = FrappeDeploymentAdapter()

    def tearDown(self):
        FrappeDeploymentAdapter.reset_in_memory_state()
        cross_doc_catalog.clear_mock_documents()

    def _build_valid_report_def(self, doctype: str = "Sales Order") -> ReportDefinition:
        """Helper to construct a valid ReportDefinition."""
        return ReportDefinition(
            report_name=f"{doctype} Delivery Status",
            ref_doctype=doctype,
            columns=[
                ReportColumn(fieldname="name", label="ID", fieldtype="Data"),
                ReportColumn(fieldname="customer", label="Customer", fieldtype="Link"),
                ReportColumn(fieldname="grand_total", label="Total Amount", fieldtype="Currency"),
                ReportColumn(fieldname="delivery_date", label="Delivery Date", fieldtype="Date"),
            ],
            filters=[
                ReportFilter(fieldname="docstatus", operator="=", value=1),
                ReportFilter(fieldname="grand_total", operator=">", value=1000),
            ],
            sort_by="modified",
            sort_order="desc",
            chart=ReportChartConfig(
                chart_type="Bar",
                x_field="customer",
                y_fields=["grand_total"],
            ),
            roles=["Sales Manager", "System Manager"],
            add_total_row=True,
        )

    # --- TEST 1: Valid Report Builder definition passes validation ---
    def test_1_valid_report_definition_passes_validation(self):
        """
        Test 1: Valid Report Builder definition passes validation.
        Verifies:
        - ReportDefinition parses and validates properly.
        - Result is subscriptable for dictionary access.
        - Preview data field is available.
        """
        rd = self._build_valid_report_def("Sales Order")
        result = validate_report_definition(rd, db=self.adapter)

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        # Verify subscriptable dictionary access
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["errors"], [])

    # --- TEST 2: Rejection of system internal DocTypes ---
    def test_2_rejection_of_system_internal_doctypes(self):
        """
        Test 2: Prohibits system internal DocTypes (User, Role, DocType, Custom Field, Property Setter, Workflow).
        """
        prohibited_types = ["User", "Role", "DocType", "Custom Field", "Property Setter", "Workflow"]

        for pt in prohibited_types:
            rd = ReportDefinition(
                report_name=f"{pt} Audit Report",
                ref_doctype=pt,
                columns=[ReportColumn(fieldname="name", label="Name")],
            )
            result = validate_report_definition(rd, db=self.adapter)
            self.assertFalse(result.is_valid, f"Expected {pt} to be rejected.")
            self.assertTrue(
                any("prohibited" in err.lower() for err in result.errors),
                f"Error for {pt} should mention prohibition: {result.errors}",
            )

    # --- TEST 3: Rejection of invalid operators / SQL injection attempt ---
    def test_3_rejection_of_invalid_operators_and_sql_injection(self):
        """
        Test 3: Rejection of invalid operators and SQL injection attempts.
        """
        # A. Invalid filter operator
        rd_invalid_op = ReportDefinition(
            report_name="Invalid Op Report",
            ref_doctype="Sales Order",
            columns=[ReportColumn(fieldname="name")],
            filters=[ReportFilter(fieldname="grand_total", operator="DROP TABLE", value=100)],
        )
        res_op = validate_report_definition(rd_invalid_op, db=self.adapter)
        self.assertFalse(res_op.is_valid)
        self.assertTrue(any("invalid operator" in err.lower() for err in res_op.errors))

        # B. SQL injection in column fieldname
        rd_sqli_col = ReportDefinition(
            report_name="SQLi Col Report",
            ref_doctype="Sales Order",
            columns=[ReportColumn(fieldname="customer; DROP TABLE `tabUser`--")],
        )
        res_sqli = validate_report_definition(rd_sqli_col, db=self.adapter)
        self.assertFalse(res_sqli.is_valid)
        self.assertTrue(any("invalid fieldname" in err.lower() for err in res_sqli.errors))

        # C. SQL injection in ref_doctype
        rd_sqli_dt = ReportDefinition(
            report_name="SQLi DocType Report",
            ref_doctype="Sales Order'; DROP TABLE--",
            columns=[ReportColumn(fieldname="name")],
        )
        res_sqli_dt = validate_report_definition(rd_sqli_dt, db=self.adapter)
        self.assertFalse(res_sqli_dt.is_valid)
        self.assertTrue(any("sql injection" in err.lower() for err in res_sqli_dt.errors))

    # --- TEST 4: Report preview data generation with sample rows ---
    def test_4_report_preview_data_generation(self):
        """
        Test 4: Report preview data generation with clean sample rows.
        """
        rd = self._build_valid_report_def("Sales Order")
        preview = get_report_preview_data(rd, db=self.adapter, limit=5)

        self.assertIsInstance(preview, list)
        self.assertEqual(len(preview), 5)

        # Verify columns are populated deterministically
        for row in preview:
            self.assertIn("name", row)
            self.assertIn("customer", row)
            self.assertIn("grand_total", row)
            self.assertIn("delivery_date", row)
            self.assertTrue(row["name"].startswith("SO-2026-"))
            self.assertIsInstance(row["grand_total"], float)

    # --- TEST 5: Successful report deployment creates Frappe Report with Report Builder JSON ---
    def test_5_successful_report_deployment(self):
        """
        Test 5: Successful report deployment creates Frappe Report with Report Builder JSON.
        Verifies:
        - Output dictionary includes status APPLIED, disposition REPORT_BUILDER_DEPLOYED, report_url.
        - Deployed Report doc contains valid Frappe Report Builder JSON with columns, filters, sort, roles.
        """
        rd = self._build_valid_report_def("Sales Order")
        outcome = execute_report_deployment(
            db=self.adapter,
            deployment_id="dep_rep_test_001",
            site_id="test_site.local",
            doctype="Sales Order",
            report_def=rd.model_dump(),
            user_roles=["Sales Manager"],
        )

        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "REPORT_BUILDER_DEPLOYED")
        self.assertEqual(outcome["report_name"], rd.report_name)
        self.assertEqual(outcome["report_url"], f"/app/query-report/{rd.report_name}")

        # Verify Frappe Report record in adapter
        rep_doc = self.adapter.get_report(rd.report_name)
        self.assertIsNotNone(rep_doc)
        self.assertEqual(rep_doc["report_name"], rd.report_name)
        self.assertEqual(rep_doc["ref_doctype"], "Sales Order")
        self.assertEqual(rep_doc["report_type"], "Report Builder")
        self.assertEqual(rep_doc["is_standard"], "No")
        self.assertEqual(rep_doc["module"], "EXRP")
        self.assertEqual(rep_doc["disabled"], 0)

        # Verify Report Builder JSON payload
        rep_json = json.loads(rep_doc["json"])
        self.assertIn("columns", rep_json)
        self.assertIn("filters", rep_json)
        self.assertIn("sort_by", rep_json)
        self.assertIn("sort_order", rep_json)
        self.assertIn("chart_args", rep_json)

        # Check column tuples [[fieldname, ref_doctype], ...]
        expected_cols = [
            ["name", "Sales Order"],
            ["customer", "Sales Order"],
            ["grand_total", "Sales Order"],
            ["delivery_date", "Sales Order"],
        ]
        self.assertEqual(rep_json["columns"], expected_cols)

        # Check filters tuples [[ref_doctype, fieldname, operator, value, 0], ...]
        self.assertEqual(len(rep_json["filters"]), 2)
        self.assertEqual(rep_json["filters"][0], ["Sales Order", "docstatus", "=", 1, 0])
        self.assertEqual(rep_json["filters"][1], ["Sales Order", "grand_total", ">", 1000, 0])

        # Check chart args
        self.assertEqual(rep_json["chart_args"]["chart_type"], "Bar")
        self.assertEqual(rep_json["chart_args"]["x_field"], "customer")
        self.assertEqual(rep_json["chart_args"]["y_fields"], ["grand_total"])

        # Check roles child table
        role_names = [r["role"] for r in rep_doc["roles"]]
        self.assertIn("Sales Manager", role_names)
        self.assertIn("System Manager", role_names)

    # --- TEST 6: Rejection of unauthorized roles ---
    def test_6_unauthorized_role_rejected(self):
        """
        Test 6: Callers without authorized report roles are rejected.
        Only System Manager, Finance Director, Operations Director, Sales Manager can deploy.
        """
        rd = self._build_valid_report_def("Sales Order")

        unauthorized_role_sets = [
            ["Accounts User"],
            ["Sales User"],
            ["Employee"],
            ["Guest"],
            [],
        ]

        for roles in unauthorized_role_sets:
            outcome = execute_report_deployment(
                db=self.adapter,
                deployment_id=f"dep_rep_unauth_{roles[0] if roles else 'empty'}",
                site_id="test_site.local",
                doctype="Sales Order",
                report_def=rd.model_dump(),
                user_roles=roles,
            )
            self.assertFalse(outcome["success"])
            self.assertEqual(outcome["status"], "REJECTED")
            self.assertEqual(outcome["stage"], "AUTHORIZATION")
            self.assertEqual(outcome["disposition"], "UNAUTHORIZED_ROLE")

    # --- TEST 7: 1-Click Rollback deactivates report (disabled = 1) ---
    def test_7_one_click_rollback_deactivates_report(self):
        """
        Test 7: 1-Click Rollback deactivates newly deployed report by setting disabled = 1.
        """
        rd = self._build_valid_report_def("Sales Order")
        dep_id = "dep_rep_rollback_001"

        outcome = execute_report_deployment(
            db=self.adapter,
            deployment_id=dep_id,
            site_id="test_site.local",
            doctype="Sales Order",
            report_def=rd.model_dump(),
            user_roles=["Sales Manager"],
        )
        self.assertTrue(outcome["success"])

        # Verify active initially
        rep = self.adapter.get_report(rd.report_name)
        self.assertEqual(rep["disabled"], 0)

        # Execute rollback
        rb_outcome = execute_rollback(
            deployment_id=dep_id,
            caller_roles=["Sales Manager"],
            db=self.adapter,
        )

        self.assertTrue(rb_outcome["success"])
        self.assertEqual(rb_outcome["status"], "ROLLED_BACK")
        self.assertEqual(rb_outcome["disposition"], "REPORT_DISABLED")
        self.assertEqual(rb_outcome["report_name"], rd.report_name)

        # Verify report is disabled in adapter
        rep_after = self.adapter.get_report(rd.report_name)
        self.assertEqual(rep_after["disabled"], 1)

    # --- TEST 8: Cross-document policy blocks Delivery Note with unsubmitted Sales Order ---
    def test_8_cross_doc_policy_blocks_unsubmitted_linked_doc(self):
        """
        Test 8: Cross-document policy blocks Delivery Note with unsubmitted (docstatus == 0) Sales Order.
        """
        # Setup mock unsubmitted Sales Order
        so_name = "SO-2026-TEST-DRAFT"
        self.adapter.set_document("Sales Order", so_name, {
            "name": so_name,
            "doctype": "Sales Order",
            "docstatus": 0,  # Draft
            "grand_total": 5000.0,
        })

        dn_doc = {
            "doctype": "Delivery Note",
            "name": "DN-2026-TEST-001",
            "against_sales_order": so_name,
            "grand_total": 5000.0,
        }

        # Evaluate via cross_doc_catalog
        result = cross_doc_catalog.evaluate_cross_doc_policies(dn_doc, stage="validate", db=self.adapter)
        self.assertFalse(result.allowed)
        self.assertIn("XDOC_DN_SO_MUST_BE_SUBMITTED", result.violated_policies)
        self.assertTrue(any("must be submitted" in r.lower() for r in result.reasons))

        # Also evaluate through integrated policy_catalog
        res_integrated = policy_catalog.evaluate_validate(dn_doc, db=self.adapter, raise_exception=False)
        self.assertFalse(res_integrated.allowed)
        self.assertIn("XDOC_DN_SO_MUST_BE_SUBMITTED", res_integrated.violated_policies)

    # --- TEST 9: Cross-document policy passes Delivery Note with submitted Sales Order ---
    def test_9_cross_doc_policy_passes_submitted_linked_doc(self):
        """
        Test 9: Cross-document policy passes Delivery Note with submitted (docstatus == 1) Sales Order.
        """
        # Setup mock submitted Sales Order
        so_name = "SO-2026-TEST-SUBMITTED"
        self.adapter.set_document("Sales Order", so_name, {
            "name": so_name,
            "doctype": "Sales Order",
            "docstatus": 1,  # Submitted
            "grand_total": 5000.0,
        })

        dn_doc = {
            "doctype": "Delivery Note",
            "name": "DN-2026-TEST-002",
            "against_sales_order": so_name,
            "grand_total": 5000.0,
        }

        # Evaluate via cross_doc_catalog
        result = cross_doc_catalog.evaluate_cross_doc_policies(dn_doc, stage="validate", db=self.adapter)
        self.assertTrue(result.allowed)
        self.assertEqual(len(result.violated_policies), 0)

        # Also evaluate through integrated policy_catalog
        res_integrated = policy_catalog.evaluate_validate(dn_doc, db=self.adapter, raise_exception=False)
        self.assertTrue(res_integrated.allowed)

    # --- TEST 10: Idempotency of report deployment ---
    def test_10_idempotency_of_report_deployment(self):
        """
        Test 10: Idempotency of report deployment (identical payload returns cached outcome, conflicting raises).
        """
        rd = self._build_valid_report_def("Sales Order")
        idemp_key = "idemp-rep-test-unique"

        # 1. First execution
        outcome_1 = execute_report_deployment(
            db=self.adapter,
            deployment_id="dep_rep_idemp_1",
            site_id="test_site.local",
            doctype="Sales Order",
            report_def=rd.model_dump(),
            user_roles=["Sales Manager"],
            idempotency_key=idemp_key,
        )
        self.assertEqual(outcome_1["status"], "APPLIED")
        self.assertEqual(outcome_1["disposition"], "REPORT_BUILDER_DEPLOYED")

        # 2. Re-execution with exact same payload
        outcome_2 = execute_report_deployment(
            db=self.adapter,
            deployment_id="dep_rep_idemp_2",
            site_id="test_site.local",
            doctype="Sales Order",
            report_def=rd.model_dump(),
            user_roles=["Sales Manager"],
            idempotency_key=idemp_key,
        )
        self.assertEqual(outcome_2["status"], "APPLIED")
        self.assertEqual(outcome_2["disposition"], "REPORT_BUILDER_DEPLOYED")
        self.assertEqual(outcome_2["report_name"], rd.report_name)

        # 3. Conflicting payload with same idempotency key raises IdempotencyConflictError
        rd_conflicting = self._build_valid_report_def("Sales Order")
        rd_conflicting.report_name = "Completely Different Report Name"

        with self.assertRaises(IdempotencyConflictError):
            execute_report_deployment(
                db=self.adapter,
                deployment_id="dep_rep_idemp_3",
                site_id="test_site.local",
                doctype="Sales Order",
                report_def=rd_conflicting.model_dump(),
                user_roles=["Sales Manager"],
                idempotency_key=idemp_key,
            )

    # --- TEST 11: End-to-end API call via control_plane.py ---
    def test_11_end_to_end_api_calls(self):
        """
        Test 11: End-to-end RPC calls via control_plane.py:
        - propose_configuration_change with intent 'create_report'
        - apply_report_change
        - revert_configuration_change
        """
        rd = self._build_valid_report_def("Sales Order")

        # 1. Propose configuration change
        prop_res = propose_configuration_change(
            doctype="Sales Order",
            proposal_payload={
                "intent": "create_report",
                "report_def": rd.model_dump(),
            },
            adapter=self.adapter,
            user_roles=["Sales Manager"],
        )

        self.assertTrue(prop_res["success"])
        self.assertEqual(prop_res["status"], "PROPOSED")
        self.assertIn("preview_data", prop_res)
        self.assertEqual(len(prop_res["preview_data"]), 5)

        # 2. Apply report change
        apply_res = apply_report_change(
            doctype="Sales Order",
            deployment_id="dep_rep_e2e_api",
            report_def=rd.model_dump(),
            adapter=self.adapter,
            user_roles=["Sales Manager"],
        )

        self.assertTrue(apply_res["success"])
        self.assertEqual(apply_res["status"], "APPLIED")
        self.assertEqual(apply_res["disposition"], "REPORT_BUILDER_DEPLOYED")

        # 3. Revert report change
        rev_res = revert_configuration_change(
            deployment_id="dep_rep_e2e_api",
            adapter=self.adapter,
            caller_roles=["Sales Manager"],
        )

        self.assertTrue(rev_res["success"])
        self.assertEqual(rev_res["status"], "ROLLED_BACK")
        self.assertEqual(rev_res["disposition"], "REPORT_DISABLED")


if __name__ == "__main__":
    unittest.main()
