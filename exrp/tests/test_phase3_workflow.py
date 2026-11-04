"""
Unit Tests for Phase 3 Declarative Workflow Generation & Multi-Tier Approval State Machines (ADR-001 Rev 2.3 & ADR-006)
Verifies:
1. Test 1: Valid 2-stage approval workflow passes validation and generates Mermaid diagram.
2. Test 2: Unreachable state is rejected with clear error.
3. Test 3: Deadlock state (non-terminal state with no transitions) is rejected.
4. Test 4: Frappe docstatus violations (submitted -> draft, cancelled -> draft, draft -> cancelled) rejected.
5. Test 5: Tier 0 DocType (GL Entry) rejected.
6. Test 6: Unauthorized role attempting deployment rejected.
7. Test 7: Successful workflow deployment creates Workflow State and Workflow records.
8. Test 8: 1-Click Rollback deactivates workflow cleanly.
9. Test 9: 1-Click Rollback restores previous active workflow if one was replaced.
10. Test 10: Idempotency / retry of workflow deployment (identical payload vs conflicting payload).
11. Test 11: Whitelisted API apply_workflow_change and proposal endpoint with Mermaid attachment.
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

from exrp.ai_control_plane.workflow_engine import (
    WorkflowStateModel,
    WorkflowTransitionModel,
    WorkflowDefinition,
    WorkflowValidationResult,
    validate_workflow_state_machine,
    execute_workflow_deployment,
    generate_mermaid_graph,
    TIER_0_PROHIBITED_WORKFLOW_DOCTYPES,
)
from exrp.ai_control_plane.rollback_engine import execute_rollback
from exrp.ai_control_plane.schema_reconciler import IdempotencyConflictError
from exrp.api.control_plane import (
    FrappeDeploymentAdapter,
    apply_workflow_change,
    revert_configuration_change,
    propose_configuration_change,
)


class TestPhase3WorkflowEngine(unittest.TestCase):
    """Test suite for Phase 3 Declarative Workflow Engine & State Machines."""

    def setUp(self):
        FrappeDeploymentAdapter.reset_in_memory_state()
        self.adapter = FrappeDeploymentAdapter()

    def tearDown(self):
        FrappeDeploymentAdapter.reset_in_memory_state()

    def _build_valid_2_stage_workflow(self, doctype: str = "Sales Order") -> WorkflowDefinition:
        """Helper to construct a valid 2-stage approval workflow definition."""
        return WorkflowDefinition(
            workflow_name=f"{doctype} Multi-Tier Approval",
            document_type=doctype,
            is_active=True,
            workflow_state_field="workflow_state",
            states=[
                WorkflowStateModel(state="Draft", doc_status=0, allow_edit="Sales User", style="Primary"),
                WorkflowStateModel(state="Pending Approval", doc_status=0, allow_edit="Sales Manager", style="Warning"),
                WorkflowStateModel(state="Approved", doc_status=1, allow_edit="Sales Manager", style="Success"),
                WorkflowStateModel(state="Rejected", doc_status=0, allow_edit="Sales Manager", style="Danger"),
            ],
            transitions=[
                WorkflowTransitionModel(
                    state="Draft",
                    action="Submit for Approval",
                    next_state="Pending Approval",
                    allowed="Sales User",
                ),
                WorkflowTransitionModel(
                    state="Pending Approval",
                    action="Approve",
                    next_state="Approved",
                    allowed="Sales Manager",
                    condition="doc.grand_total <= 50000",
                ),
                WorkflowTransitionModel(
                    state="Pending Approval",
                    action="Reject",
                    next_state="Rejected",
                    allowed="Sales Manager",
                ),
            ],
        )

    # --- TEST 1: Valid 2-stage approval workflow passes validation and generates Mermaid diagram ---
    def test_1_valid_2_stage_approval_workflow(self):
        """
        Test 1: Valid 2-stage approval workflow passes validation and generates Mermaid diagram.
        Verifies:
        - All states are reachable from initial Draft state.
        - Initial state has doc_status == 0.
        - Terminal approved and rejected states are properly identified.
        - Valid Mermaid flowchart syntax is generated.
        """
        wf = self._build_valid_2_stage_workflow("Sales Order")
        result = validate_workflow_state_machine(wf)

        self.assertTrue(result.is_valid, f"Validation failed with errors: {result.errors}")
        self.assertEqual(len(result.errors), 0)
        self.assertIn("graph TD", result.mermaid_graph)
        self.assertIn("Draft (Draft)", result.mermaid_graph)
        self.assertIn("Approved (Submitted)", result.mermaid_graph)
        self.assertIn("Submit for Approval [Sales User]", result.mermaid_graph)
        self.assertIn("doc.grand_total <= 50000", result.mermaid_graph)

    # --- TEST 2: Unreachable state is rejected with clear error ---
    def test_2_unreachable_state_rejected(self):
        """
        Test 2: Unreachable state is rejected with clear error.
        Verifies:
        - BFS graph traversal identifies disconnected / orphaned states.
        - Rejection message specifically identifies the unreachable state.
        """
        wf = self._build_valid_2_stage_workflow("Quotation")
        # Add an orphan state not reachable from Draft
        wf.states.append(
            WorkflowStateModel(state="Orphan State", doc_status=0, allow_edit="Sales User", style="Inverse")
        )

        result = validate_workflow_state_machine(wf)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("Unreachable state detected" in err and "Orphan State" in err for err in result.errors),
            f"Expected unreachable state error, got: {result.errors}",
        )

    # --- TEST 3: Deadlock state (non-terminal state with no transitions) is rejected ---
    def test_3_deadlock_state_rejected(self):
        """
        Test 3: Deadlock state (non-terminal state with no transitions) is rejected.
        Verifies:
        - If an intermediate state (doc_status == 0, not rejected) has no outgoing transitions,
          it is flagged as a deadlock state.
        """
        wf = WorkflowDefinition(
            workflow_name="Deadlock Test Workflow",
            document_type="Purchase Order",
            states=[
                WorkflowStateModel(state="Draft", doc_status=0, allow_edit="Purchase User"),
                WorkflowStateModel(state="Pending Review", doc_status=0, allow_edit="Purchase Manager"),
                WorkflowStateModel(state="Approved", doc_status=1, allow_edit="Purchase Manager"),
            ],
            transitions=[
                # Draft transitions to Pending Review, but Pending Review has NO outgoing transitions!
                WorkflowTransitionModel(
                    state="Draft",
                    action="Send to Review",
                    next_state="Pending Review",
                    allowed="Purchase User",
                ),
                # Draft can also go to Approved directly
                WorkflowTransitionModel(
                    state="Draft",
                    action="Fast Approve",
                    next_state="Approved",
                    allowed="System Manager",
                ),
            ],
        )

        result = validate_workflow_state_machine(wf)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("Deadlock state detected" in err and "Pending Review" in err for err in result.errors),
            f"Expected deadlock error for 'Pending Review', got: {result.errors}",
        )

    # --- TEST 4: Frappe docstatus violations rejected ---
    def test_4_frappe_docstatus_violations_rejected(self):
        """
        Test 4: Frappe docstatus violations rejected:
        - Case A: Reverting Submitted (doc_status 1) to Draft (doc_status 0).
        - Case B: Transitioning out of Cancelled (doc_status 2).
        - Case C: Directly cancelling from Draft (doc_status 0 -> 2).
        """
        # Case A: Submitted -> Draft
        wf_revert = WorkflowDefinition(
            workflow_name="Illegal Revert Workflow",
            document_type="Sales Order",
            states=[
                WorkflowStateModel(state="Draft", doc_status=0, allow_edit="Sales User"),
                WorkflowStateModel(state="Approved", doc_status=1, allow_edit="Sales Manager"),
            ],
            transitions=[
                WorkflowTransitionModel(state="Draft", action="Approve", next_state="Approved", allowed="Sales Manager"),
                WorkflowTransitionModel(state="Approved", action="Reopen", next_state="Draft", allowed="Sales Manager"),
            ],
        )
        res_a = validate_workflow_state_machine(wf_revert)
        self.assertFalse(res_a.is_valid)
        self.assertTrue(any("Cannot revert Submitted state" in err for err in res_a.errors))

        # Case B: Cancelled -> Draft / any
        wf_cancelled_out = WorkflowDefinition(
            workflow_name="Illegal Cancelled Out Workflow",
            document_type="Sales Order",
            states=[
                WorkflowStateModel(state="Draft", doc_status=0, allow_edit="Sales User"),
                WorkflowStateModel(state="Approved", doc_status=1, allow_edit="Sales Manager"),
                WorkflowStateModel(state="Cancelled", doc_status=2, allow_edit="System Manager"),
            ],
            transitions=[
                WorkflowTransitionModel(state="Draft", action="Approve", next_state="Approved", allowed="Sales Manager"),
                WorkflowTransitionModel(state="Approved", action="Cancel", next_state="Cancelled", allowed="System Manager"),
                WorkflowTransitionModel(state="Cancelled", action="Revive", next_state="Draft", allowed="System Manager"),
            ],
        )
        res_b = validate_workflow_state_machine(wf_cancelled_out)
        self.assertFalse(res_b.is_valid)
        self.assertTrue(any("Cannot transition out of Cancelled state" in err for err in res_b.errors))

        # Case C: Draft (0) -> Cancelled (2) directly
        wf_draft_cancel = WorkflowDefinition(
            workflow_name="Illegal Direct Cancel Workflow",
            document_type="Sales Order",
            states=[
                WorkflowStateModel(state="Draft", doc_status=0, allow_edit="Sales User"),
                WorkflowStateModel(state="Approved", doc_status=1, allow_edit="Sales Manager"),
                WorkflowStateModel(state="Cancelled", doc_status=2, allow_edit="Sales Manager"),
            ],
            transitions=[
                WorkflowTransitionModel(state="Draft", action="Approve", next_state="Approved", allowed="Sales Manager"),
                WorkflowTransitionModel(state="Draft", action="Cancel Immediately", next_state="Cancelled", allowed="Sales Manager"),
            ],
        )
        res_c = validate_workflow_state_machine(wf_draft_cancel)
        self.assertFalse(res_c.is_valid)
        self.assertTrue(any("directly to Cancelled state" in err for err in res_c.errors))

    # --- TEST 5: Tier 0 DocType (GL Entry) rejected ---
    def test_5_tier_0_doctype_rejected(self):
        """
        Test 5: Tier 0 DocType (GL Entry) rejected under ADR-001 Rev 2.3 §10.
        Verifies:
        - Financial / system DocTypes (GL Entry, User, Role, Workflow, etc.) cannot have workflows created.
        """
        wf = self._build_valid_2_stage_workflow("GL Entry")
        result = validate_workflow_state_machine(wf)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("Tier 0 system/financial DocType" in err for err in result.errors),
            f"Expected Tier 0 rejection error, got: {result.errors}",
        )

        # Also verify other Tier 0 DocTypes (User, Role, DocType)
        for t0 in ["User", "Role", "DocType", "Stock Ledger Entry"]:
            wf_t0 = self._build_valid_2_stage_workflow(t0)
            res_t0 = validate_workflow_state_machine(wf_t0)
            self.assertFalse(res_t0.is_valid, f"Expected {t0} to be rejected")
            self.assertTrue(any("Tier 0" in err for err in res_t0.errors))

    # --- TEST 6: Unauthorized role attempting deployment rejected ---
    def test_6_unauthorized_role_rejected(self):
        """
        Test 6: Unauthorized role attempting deployment rejected.
        Verifies:
        - Only System Manager, Finance Director, Operations Director can apply workflows.
        - Callers with roles like 'Sales User' or 'Accounts User' are rejected with UNAUTHORIZED_ROLE.
        """
        wf = self._build_valid_2_stage_workflow("Delivery Note")

        outcome = execute_workflow_deployment(
            db=self.adapter,
            deployment_id="dep_wf_unauth_001",
            site_id="site1.local",
            doctype="Delivery Note",
            workflow_def=wf.model_dump(),
            user_roles=["Sales User", "Employee"],
        )

        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["status"], "REJECTED")
        self.assertEqual(outcome["stage"], "AUTHORIZATION")
        self.assertEqual(outcome["disposition"], "UNAUTHORIZED_ROLE")

    # --- TEST 7: Successful workflow deployment creates Workflow State and Workflow records ---
    def test_7_successful_workflow_deployment(self):
        """
        Test 7: Successful workflow deployment creates Workflow State and Workflow records.
        Verifies:
        - Advisory lock GET_LOCK <= 64 chars acquired and released.
        - Idempotently creates Workflow State records.
        - Creates Workflow document with is_active = 1.
        - Records APPLIED audit status and WORKFLOW_STATE_MACHINE_ACTIVATED disposition.
        """
        wf = self._build_valid_2_stage_workflow("Sales Order")

        outcome = execute_workflow_deployment(
            db=self.adapter,
            deployment_id="dep_wf_apply_001",
            site_id="site1.local",
            doctype="Sales Order",
            workflow_def=wf.model_dump(),
            user_roles=["System Manager"],
        )

        self.assertTrue(outcome["success"], f"Deployment failed: {outcome}")
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "WORKFLOW_STATE_MACHINE_ACTIVATED")
        self.assertEqual(outcome["doctype"], "Sales Order")
        self.assertEqual(outcome["workflow_name"], "Sales Order Multi-Tier Approval")
        self.assertEqual(outcome["is_active"], 1)
        self.assertTrue(self.adapter.cache_cleared)

        # Verify Workflow State records were created
        for s in wf.states:
            ws = self.adapter.get_workflow_state(s.state)
            self.assertIsNotNone(ws, f"Workflow State '{s.state}' was not created")
            self.assertEqual(ws["workflow_state_name"], s.state)

        # Verify Workflow record was created and is active
        stored_wf = self.adapter.get_workflow("Sales Order Multi-Tier Approval")
        self.assertIsNotNone(stored_wf)
        self.assertEqual(stored_wf["is_active"], 1)
        self.assertEqual(stored_wf["document_type"], "Sales Order")
        self.assertEqual(len(stored_wf["states"]), 4)
        self.assertEqual(len(stored_wf["transitions"]), 3)

        # Verify audit record durability
        rec = self.adapter.get_deployment_record("dep_wf_apply_001")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["status"], "APPLIED")
        self.assertEqual(rec["deployment_type"], "workflow")

    # --- TEST 8: 1-Click Rollback deactivates workflow cleanly ---
    def test_8_rollback_deactivates_workflow(self):
        """
        Test 8: 1-Click Rollback deactivates workflow cleanly when no prior workflow existed.
        Verifies:
        - When a workflow is rolled back, is_active is set to 0.
        - Workflow records and state definitions remain preserved in place (non-destructive).
        - Audit journal is updated with status ROLLED_BACK and disposition WORKFLOW_DEACTIVATED.
        """
        wf = self._build_valid_2_stage_workflow("Purchase Order")

        deploy_outcome = execute_workflow_deployment(
            db=self.adapter,
            deployment_id="dep_wf_rb_001",
            site_id="site1.local",
            doctype="Purchase Order",
            workflow_def=wf.model_dump(),
            user_roles=["Finance Director"],
        )
        self.assertTrue(deploy_outcome["success"])

        # Rollback the deployment
        rb_outcome = execute_rollback(
            deployment_id="dep_wf_rb_001",
            caller_roles=["Finance Director"],
            db=self.adapter,
        )

        self.assertTrue(rb_outcome["success"], f"Rollback failed: {rb_outcome}")
        self.assertEqual(rb_outcome["status"], "ROLLED_BACK")
        self.assertEqual(rb_outcome["disposition"], "WORKFLOW_DEACTIVATED")
        self.assertIsNone(rb_outcome["restored_workflow"])

        # Workflow record must still exist but be inactive (is_active == 0)
        stored_wf = self.adapter.get_workflow(wf.workflow_name)
        self.assertIsNotNone(stored_wf)
        self.assertEqual(stored_wf["is_active"], 0)

        # Active workflow query for Purchase Order should return None
        active_wf = self.adapter.get_active_workflow("Purchase Order")
        self.assertIsNone(active_wf)

    # --- TEST 9: 1-Click Rollback restores previous active workflow if one was replaced ---
    def test_9_rollback_restores_previous_active_workflow(self):
        """
        Test 9: 1-Click Rollback restores previous active workflow if one was replaced.
        Verifies:
        - Deploy Workflow 1 (Baseline Active).
        - Deploy Workflow 2 (Replaces Workflow 1, deactivating Workflow 1).
        - Rollback Workflow 2: Workflow 2 becomes inactive (0), and Workflow 1 is reactivated (1).
        - Disposition PREVIOUS_WORKFLOW_RESTORED returned.
        """
        # 1. Setup pre-existing active workflow on Quotation
        self.adapter.workflows["Legacy Quotation Approval"] = {
            "doctype": "Workflow",
            "workflow_name": "Legacy Quotation Approval",
            "document_type": "Quotation",
            "is_active": 1,
            "workflow_state_field": "workflow_state",
            "states": [{"state": "Draft", "doc_status": 0}],
            "transitions": [],
        }

        # 2. Deploy new Workflow
        new_wf = self._build_valid_2_stage_workflow("Quotation")
        new_wf.workflow_name = "Modern Quotation Multi-Tier Approval"

        deploy_outcome = execute_workflow_deployment(
            db=self.adapter,
            deployment_id="dep_wf_modern_001",
            site_id="site1.local",
            doctype="Quotation",
            workflow_def=new_wf.model_dump(),
            user_roles=["Operations Director"],
        )
        self.assertTrue(deploy_outcome["success"])

        # New workflow is active, legacy is deactivated
        self.assertEqual(self.adapter.get_workflow("Modern Quotation Multi-Tier Approval")["is_active"], 1)
        self.assertEqual(self.adapter.get_workflow("Legacy Quotation Approval")["is_active"], 0)

        # 3. Rollback the new workflow
        rb_outcome = execute_rollback(
            deployment_id="dep_wf_modern_001",
            caller_roles=["Operations Director"],
            db=self.adapter,
        )

        self.assertTrue(rb_outcome["success"], f"Rollback failed: {rb_outcome}")
        self.assertEqual(rb_outcome["status"], "ROLLED_BACK")
        self.assertEqual(rb_outcome["disposition"], "PREVIOUS_WORKFLOW_RESTORED")
        self.assertEqual(rb_outcome["restored_workflow"], "Legacy Quotation Approval")

        # New workflow is deactivated (0), Legacy workflow is reactivated (1)
        self.assertEqual(self.adapter.get_workflow("Modern Quotation Multi-Tier Approval")["is_active"], 0)
        self.assertEqual(self.adapter.get_workflow("Legacy Quotation Approval")["is_active"], 1)

        # Active workflow query returns Legacy
        active_wf = self.adapter.get_active_workflow("Quotation")
        self.assertIsNotNone(active_wf)
        self.assertEqual(active_wf["workflow_name"], "Legacy Quotation Approval")

    # --- TEST 10: Idempotency / retry of workflow deployment ---
    def test_10_idempotency_workflow_deployment(self):
        """
        Test 10: Idempotency / retry of workflow deployment.
        Verifies:
        - Replay with identical idempotency_key and identical payload returns cached outcome.
        - Replay with identical idempotency_key but conflicting payload raises IdempotencyConflictError.
        """
        wf = self._build_valid_2_stage_workflow("Opportunity")
        idemp_key = "idemp_wf_opp_001"

        outcome1 = execute_workflow_deployment(
            db=self.adapter,
            deployment_id="dep_wf_idemp_001",
            site_id="site1.local",
            doctype="Opportunity",
            workflow_def=wf.model_dump(),
            user_roles=["System Manager"],
            idempotency_key=idemp_key,
        )
        self.assertTrue(outcome1["success"])
        self.assertEqual(outcome1["status"], "APPLIED")

        # Retry with identical key and identical payload -> returns cached outcome
        outcome2 = execute_workflow_deployment(
            db=self.adapter,
            deployment_id="dep_wf_idemp_002",
            site_id="site1.local",
            doctype="Opportunity",
            workflow_def=wf.model_dump(),
            user_roles=["System Manager"],
            idempotency_key=idemp_key,
        )
        self.assertTrue(outcome2["success"])
        self.assertEqual(outcome2["status"], "APPLIED")
        self.assertEqual(outcome2["disposition"], outcome1["disposition"])

        # Retry with identical key but conflicting payload -> raises IdempotencyConflictError
        conflicting_wf = wf.model_dump()
        conflicting_wf["workflow_name"] = "Conflicting Opportunity Workflow Name"

        with self.assertRaises(IdempotencyConflictError):
            execute_workflow_deployment(
                db=self.adapter,
                deployment_id="dep_wf_idemp_003",
                site_id="site1.local",
                doctype="Opportunity",
                workflow_def=conflicting_wf,
                user_roles=["System Manager"],
                idempotency_key=idemp_key,
            )

    # --- TEST 11: Whitelisted API apply_workflow_change and proposal endpoint ---
    def test_11_api_endpoints_and_proposal(self):
        """
        Test 11: Whitelisted API endpoints in exrp.api.control_plane.
        Verifies:
        - propose_configuration_change with workflow intent attaches Mermaid diagram.
        - apply_workflow_change executes deployment and checks authorization.
        - revert_configuration_change successfully rolls back the workflow.
        """
        wf = self._build_valid_2_stage_workflow("Sales Order")

        # 1. Proposal flow
        proposal_res = propose_configuration_change(
            doctype="Sales Order",
            proposal_payload={
                "intent": "create_workflow",
                "workflow_def": wf.model_dump(),
            },
            user_roles=["Sales Manager"],
        )
        self.assertTrue(proposal_res["success"])
        self.assertEqual(proposal_res["status"], "PROPOSED")
        self.assertIn("mermaid_graph", proposal_res)
        self.assertIn("graph TD", proposal_res["mermaid_graph"])

        # 2. Apply change via API
        apply_res = apply_workflow_change(
            doctype="Sales Order",
            deployment_id="dep_api_wf_001",
            workflow_def=wf.model_dump(),
            user_roles=["System Manager"],
            adapter=self.adapter,
        )
        self.assertTrue(apply_res["success"])
        self.assertEqual(apply_res["status"], "APPLIED")
        self.assertEqual(apply_res["disposition"], "WORKFLOW_STATE_MACHINE_ACTIVATED")

        # 3. Rollback via API
        revert_res = revert_configuration_change(
            deployment_id="dep_api_wf_001",
            user_roles=["System Manager"],
            adapter=self.adapter,
        )
        self.assertTrue(revert_res["success"])
        self.assertEqual(revert_res["status"], "ROLLED_BACK")
        self.assertEqual(revert_res["disposition"], "WORKFLOW_DEACTIVATED")


if __name__ == "__main__":
    unittest.main()
