"""
Comprehensive Unit Tests for EXRP LLM Conversational Planner (ADR-001 Rev 2.3)
Verifies:
- Test 1: Valid user prompt generates approved single-field proposal.
- Test 2: Invariant attack prompt triggers self-correction feedback loop or refusal cleanly.
- Test 3: Multiple field prompt triggers single-field Phase 1 constraint enforcement.
- Test 4: Full flow via exrp.api.control_plane.propose_configuration_change.
- Test 5: DDL Gate rejection triggers automated self-correction loop.
- Test 6: Google GenAI Interactions API client structured generation contract.
- Test 7: Pydantic model validation and serialization contracts.
"""

import os
import sys
import json
import types
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "frappe" not in sys.modules:
    try:
        import frappe
    except ImportError:
        f = types.ModuleType("frappe")
        f.utils = types.ModuleType("frappe.utils")
        f.utils.cstr = lambda x: str(x)
        sys.modules["frappe"] = f
        sys.modules["frappe.utils"] = f.utils

from exrp.ai_control_plane.planner import (
    ProposedFieldChange,
    ConfigurationProposal,
    PlannerResult,
    AIConfigurationPlanner,
)
from exrp.ai_control_plane.ddl_plan_gate import DDLPlanInspection
from exrp.api.control_plane import (
    propose_configuration_change,
    apply_configuration_change,
)


class TestAIConfigurationPlanner(unittest.TestCase):

    def test_1_valid_user_prompt_generates_approved_single_field_proposal(self):
        """
        Test 1: Valid user prompt (e.g. 'Add a priority status dropdown with Low, Medium, High')
        generates an approved single-field proposal matching ADR-001 Rev 2.3 §5.1.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Add a priority status dropdown with Low, Medium, High",
        )

        self.assertTrue(result.success, f"Expected success but got error: {result.error_message}")
        self.assertIsNotNone(result.proposal)
        self.assertEqual(result.proposal.intent, "add_custom_fields")
        self.assertEqual(result.proposal.target_doctype, "Sales Order")
        self.assertEqual(len(result.proposal.changes), 1)

        change = result.proposal.changes[0]
        field_dict = change.model_dump() if hasattr(change, "model_dump") else change
        self.assertEqual(field_dict["fieldname"], "custom_priority_status")
        self.assertEqual(field_dict["fieldtype"], "Select")
        self.assertIn("Low\nMedium\nHigh", field_dict["options"])
        self.assertEqual(field_dict["reqd"], 0)
        self.assertEqual(field_dict["read_only"], 0)

        # Verify safety validation
        self.assertIsNotNone(result.validation)
        self.assertEqual(result.validation["status"], "approved")
        self.assertEqual(result.validation["storage_impact"], "ONLINE_ADDITIVE_DDL")

        # Verify DDL plan gate evidence
        self.assertIsNotNone(result.ddl_plan)
        self.assertTrue(result.ddl_plan["inspectable"])
        self.assertTrue(result.ddl_plan["is_approved_additive_only"])
        self.assertIsNone(result.ddl_plan["rejection_reason"])
        self.assertEqual(len(result.ddl_plan["statements"]), 1)
        self.assertIn("ADD COLUMN `custom_priority_status`", result.ddl_plan["statements"][0])

        # Verify 1 attempt and clean history
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(result.feedback_history), 0)

    def test_2_invariant_attack_prompt_triggers_self_correction_or_refusal_cleanly(self):
        """
        Test 2: Invariant attack prompt (e.g. 'Delete or modify the rate column on Sales Order Item')
        triggers the self-correction feedback loop and fails/refuses cleanly without weakening Tier 0 invariants.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order Item",
            user_prompt="Delete or modify the rate column on Sales Order Item",
            max_retries=2,
        )

        self.assertFalse(result.success, "Invariant attack must never succeed.")
        self.assertIsNotNone(result.error_message)
        self.assertIn("rate", result.error_message.lower())
        self.assertIn("Tier 0 Invariant", result.error_message)

        # Verify automated self-correction feedback history was populated
        self.assertGreaterEqual(len(result.feedback_history), 1)
        for fb in result.feedback_history:
            self.assertIn("Your previous proposal was rejected:", fb)
            self.assertIn("satisfy enterprise safety invariants", fb)

    def test_3_multiple_field_prompt_triggers_single_field_phase_1_enforcement(self):
        """
        Test 3: Multiple field prompt triggers single-field Phase 1 constraint enforcement.
        With default settings, attempt 1 produces 2 fields, is rejected by ZoneSafetyViolation,
        and self-corrects to 1 field in attempt 2.
        With truncate_to_single_field=True, truncates directly.
        """
        # Case A: Self-correction loop down to single field
        planner = AIConfigurationPlanner(mock_mode=True, truncate_to_single_field=False)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Add a priority status dropdown and an escalation notes text field",
            max_retries=2,
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.proposal)
        self.assertEqual(len(result.proposal.changes), 1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.feedback_history), 1)
        self.assertIn("Single-Field Unit Rule", result.feedback_history[0])

        # Case B: Direct truncation mode
        planner_trunc = AIConfigurationPlanner(mock_mode=True, truncate_to_single_field=True)
        result_trunc = planner_trunc.plan_change(
            doctype="Sales Order",
            user_prompt="Add a priority status dropdown and an escalation notes text field",
        )

        self.assertTrue(result_trunc.success)
        self.assertIsNotNone(result_trunc.proposal)
        self.assertEqual(len(result_trunc.proposal.changes), 1)
        self.assertEqual(result_trunc.attempts, 1)

    def test_4_full_flow_via_control_plane_api(self):
        """
        Test 4: Full flow via exrp.api.control_plane.propose_configuration_change
        supporting both conversational natural language prompts and raw payloads.
        """
        # Flow 4.1: Natural language conversational prompt
        resp = propose_configuration_change(
            doctype="Sales Order",
            user_prompt="Add a priority status dropdown with Low, Medium, High",
        )

        self.assertEqual(resp["status"], "PROPOSED")
        self.assertTrue(resp["success"])
        self.assertIsNotNone(resp["proposal"])
        self.assertIsNotNone(resp["validation"])
        self.assertIsNotNone(resp["ddl_plan"])
        self.assertTrue(resp["ddl_plan"]["is_approved_additive_only"])
        self.assertIn("preview_fidelity_notice", resp)

        # Flow 4.2: Adversarial natural language prompt
        resp_adv = propose_configuration_change(
            doctype="Sales Order Item",
            user_prompt="Delete or modify the rate column on Sales Order Item",
        )

        self.assertEqual(resp_adv["status"], "REJECTED")
        self.assertFalse(resp_adv["success"])
        self.assertIn("rate", resp_adv["error_message"].lower())
        self.assertGreaterEqual(len(resp_adv["feedback_history"]), 1)

        # Flow 4.3: Raw declarative configuration payload
        resp_raw = propose_configuration_change(
            doctype="Sales Order",
            proposal_payload={
                "intent": "add_custom_fields",
                "changes": [
                    {
                        "fieldname": "custom_inspection_tag",
                        "label": "Inspection Tag",
                        "fieldtype": "Data",
                    }
                ],
            },
        )

        self.assertEqual(resp_raw["status"], "PROPOSED")
        self.assertTrue(resp_raw["success"])
        self.assertTrue(resp_raw["ddl_plan"]["is_approved_additive_only"])

    def test_5_ddl_gate_rejection_triggers_self_correction_feedback_loop(self):
        """
        Test 5: If updatedb() diff produces unapproved DDL (e.g. MODIFY COLUMN),
        DDL plan gate rejects it, feeds error back to model, and attempts retry.
        """
        inspection_count = 0

        def simulated_ddl_inspector(doctype, field_def):
            nonlocal inspection_count
            inspection_count += 1
            if inspection_count == 1:
                return DDLPlanInspection(
                    inspectable=True,
                    statements=[
                        f"ALTER TABLE `tab{doctype}` ADD COLUMN `{field_def['fieldname']}` varchar(140), MODIFY COLUMN `status` varchar(255)"
                    ],
                    is_approved_additive_only=False,
                    rejection_reason="Unapproved MODIFY COLUMN detected in updatedb() diff",
                )
            else:
                return DDLPlanInspection(
                    inspectable=True,
                    statements=[
                        f"ALTER TABLE `tab{doctype}` ADD COLUMN `{field_def['fieldname']}` varchar(140)"
                    ],
                    is_approved_additive_only=True,
                    rejection_reason=None,
                )

        planner = AIConfigurationPlanner(
            mock_mode=True,
            ddl_inspector=simulated_ddl_inspector,
        )

        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Add cargo tracking id",
            max_retries=2,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.feedback_history), 1)
        self.assertIn("Unapproved MODIFY COLUMN", result.feedback_history[0])

    def test_6_gemini_interactions_client_structured_generation(self):
        """
        Test 6: Validates interactions with Google GenAI SDK Client (Interactions API):
        Verifies model name, structured JSON response format schema, and input construction.
        """
        recorded_call = {}

        class MockGeminiInteractions:
            def create(self, **kwargs):
                recorded_call.update(kwargs)
                mock_json_response = {
                    "intent": "add_custom_fields",
                    "target_doctype": "Sales Order",
                    "summary": "Add priority status select field",
                    "reasoning": "Interactions API structured output test",
                    "changes": [
                        {
                            "fieldname": "custom_priority_status",
                            "label": "Priority Status",
                            "fieldtype": "Select",
                            "options": "Low\nMedium\nHigh",
                            "reqd": 0,
                            "read_only": 0,
                            "default": "Low",
                        }
                    ],
                    "governance_tier": 1,
                }
                return types.SimpleNamespace(output_text=json.dumps(mock_json_response))

        class MockGenAIClient:
            def __init__(self):
                self.interactions = MockGeminiInteractions()

        fake_client = MockGenAIClient()
        planner = AIConfigurationPlanner(client=fake_client, model="gemini-3.8-flash")
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Add a priority status dropdown with Low, Medium, High",
        )

        self.assertTrue(result.success)
        self.assertEqual(recorded_call["model"], "gemini-3.8-flash")
        self.assertEqual(recorded_call["response_format"]["mime_type"], "application/json")
        self.assertIn("schema", recorded_call["response_format"])
        self.assertIn("Sales Order", recorded_call["input"])

    def test_7_pydantic_models_validation_and_serialization(self):
        """
        Test 7: Validates Pydantic model serialization, snake_case normalization,
        and JSON schema generation.
        """
        field = ProposedFieldChange(
            fieldname="CUSTOM_CARGO_ID",
            label="Cargo ID",
            fieldtype="Data",
        )
        self.assertEqual(field.fieldname, "custom_cargo_id")

        proposal = ConfigurationProposal(
            intent="add_custom_fields",
            target_doctype="Sales Order",
            summary="Add cargo ID",
            reasoning="Testing models",
            changes=[field],
            governance_tier=1,
        )
        schema = ConfigurationProposal.model_json_schema()
        self.assertIn("properties", schema)
        self.assertIn("intent", schema["properties"])
        self.assertIn("changes", schema["properties"])

        dumped = proposal.model_dump()
        self.assertEqual(dumped["changes"][0]["fieldname"], "custom_cargo_id")

    def test_8_apply_configuration_change_flow(self):
        """
        Test 8: Verifies apply_configuration_change applies approved proposal
        and rejects unsafe mutations according to ADR-001 Rev 2.3.
        """
        # Flow 8.1: Valid proposal deployment
        valid_res = apply_configuration_change(
            doctype="Sales Order",
            field_def={
                "fieldname": "custom_priority",
                "label": "Priority",
                "fieldtype": "Select",
                "options": "Low\nMedium\nHigh",
            },
        )
        self.assertTrue(valid_res["success"])
        self.assertEqual(valid_res["status"], "APPLIED")
        self.assertEqual(valid_res["doctype"], "Sales Order")
        self.assertEqual(valid_res["fieldname"], "custom_priority")

        # Flow 8.2: Blocked deployment on protected DocType (GL Entry)
        rejected_res = apply_configuration_change(
            doctype="GL Entry",
            field_def={
                "fieldname": "custom_unsafe_field",
                "label": "Unsafe Field",
                "fieldtype": "Data",
            },
        )
        self.assertFalse(rejected_res["success"])
        self.assertEqual(rejected_res["status"], "REJECTED")


if __name__ == "__main__":
    unittest.main()
