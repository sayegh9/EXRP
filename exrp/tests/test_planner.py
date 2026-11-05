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

try:
    import frappe
    if hasattr(frappe, "local"):
        if not hasattr(frappe.local, "flags"):
            frappe.local.flags = frappe._dict() if hasattr(frappe, "_dict") else types.SimpleNamespace()
        frappe.local.flags.in_test = True
except Exception:
    pass

from unittest.mock import patch, MagicMock

from exrp.ai_control_plane.planner import (
    ProposedFieldChange,
    ConfigurationProposal,
    PlannerResult,
    AIConfigurationPlanner,
    resolve_llm_config,
)
from exrp.ai_control_plane.ddl_plan_gate import DDLPlanInspection
from exrp.api.control_plane import (
    propose_configuration_change,
    apply_configuration_change,
    test_llm_connection,
    get_llm_config,
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

    def test_9_resolve_llm_config_with_settings_doc(self):
        """
        Test 9: Verifies resolve_llm_config reads from EXRP Settings Single DocType,
        extracts get_password('api_key'), and correctly maps offline_mode & provider.
        """
        mock_doc = types.SimpleNamespace(
            llm_provider="Google Gemini",
            model_name="gemini-3.8-flash",
            api_key="secret-from-doctype",
            api_base_url="https://proxy.example.com",
            temperature=0.7,
            max_retries=3,
            enable_sidecar=1,
            offline_mode=0,
            strict_tier0_lock=1,
            lock_wait_timeout=5,
            get_password=lambda field, raise_exception=False: "decrypted-secret-key" if field == "api_key" else None,
            as_dict=lambda: {
                "llm_provider": "Google Gemini",
                "model_name": "gemini-3.8-flash",
                "temperature": 0.7,
                "max_retries": 3,
                "enable_sidecar": 1,
                "offline_mode": 0,
                "strict_tier0_lock": 1,
                "lock_wait_timeout": 5,
            },
        )

        with patch("exrp.ai_control_plane.planner.frappe") as mock_frappe:
            mock_frappe.get_single.return_value = mock_doc
            config = resolve_llm_config()

            self.assertEqual(config["llm_provider"], "Google Gemini")
            self.assertEqual(config["model_name"], "gemini-3.8-flash")
            self.assertEqual(config["api_key"], "decrypted-secret-key")
            self.assertEqual(config["api_base_url"], "https://proxy.example.com")
            self.assertEqual(config["temperature"], 0.7)
            self.assertEqual(config["max_retries"], 3)
            self.assertTrue(config["enable_sidecar"])
            self.assertFalse(config["offline_mode"])
            self.assertTrue(config["strict_tier0_lock"])
            self.assertEqual(config["lock_wait_timeout"], 5)
            self.assertFalse(config["mock_mode"])

    def test_10_resolve_llm_config_offline_and_mock_mode(self):
        """
        Test 10: Verifies offline_mode and 'Mock / Offline Test Mode' enforce mock_mode=True.
        """
        # Case A: offline_mode = 1
        mock_doc_offline = types.SimpleNamespace(
            llm_provider="Google Gemini",
            offline_mode=1,
            api_key="valid-key",
            get_password=lambda field, raise_exception=False: "valid-key",
            as_dict=lambda: {"offline_mode": 1, "llm_provider": "Google Gemini"},
        )
        with patch("exrp.ai_control_plane.planner.frappe") as mock_frappe:
            mock_frappe.get_single.return_value = mock_doc_offline
            config = resolve_llm_config()
            self.assertTrue(config["offline_mode"])
            self.assertTrue(config["mock_mode"])

        # Case B: llm_provider = 'Mock / Offline Test Mode'
        mock_doc_mock = types.SimpleNamespace(
            llm_provider="Mock / Offline Test Mode",
            offline_mode=0,
            api_key="",
            get_password=lambda field, raise_exception=False: None,
            as_dict=lambda: {"offline_mode": 0, "llm_provider": "Mock / Offline Test Mode"},
        )
        with patch("exrp.ai_control_plane.planner.frappe") as mock_frappe:
            mock_frappe.get_single.return_value = mock_doc_mock
            config = resolve_llm_config()
            self.assertEqual(config["llm_provider"], "Mock / Offline Test Mode")
            self.assertTrue(config["mock_mode"])

    def test_11_resolve_llm_config_env_fallbacks(self):
        """
        Test 11: Verifies environment variable fallbacks (GEMINI_API_KEY, OPENAI_API_KEY)
        when EXRP Settings is absent or unconfigured.
        """
        with patch("exrp.ai_control_plane.planner.frappe", None):
            # Test GEMINI_API_KEY fallback
            with patch.dict(os.environ, {"GEMINI_API_KEY": "env-gemini-key", "OPENAI_API_KEY": ""}):
                config = resolve_llm_config()
                self.assertEqual(config["llm_provider"], "Google Gemini")
                self.assertEqual(config["api_key"], "env-gemini-key")
                self.assertFalse(config["mock_mode"])

            # Test OPENAI_API_KEY fallback
            clean_env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "OPENAI_API_KEY")}
            clean_env["OPENAI_API_KEY"] = "env-openai-key"
            with patch.dict(os.environ, clean_env, clear=True):
                config = resolve_llm_config()
                self.assertEqual(config["llm_provider"], "OpenAI")
                self.assertEqual(config["api_key"], "env-openai-key")
                self.assertFalse(config["mock_mode"])

            # Test no keys -> mock_mode=True
            with patch.dict(os.environ, {}, clear=True):
                config = resolve_llm_config()
                self.assertIsNone(config["api_key"])
                self.assertTrue(config["mock_mode"])

    def test_12_test_llm_connection_and_get_config(self):
        """
        Test 12: Verifies test_llm_connection RPC endpoint and get_llm_config.
        """
        # Test 12.1: Mock provider succeeds immediately
        res = test_llm_connection(provider="Mock / Offline Test Mode")
        self.assertTrue(res["success"])
        self.assertIn("verified successfully", res["message"])

        # Test 12.2: Missing API key fails cleanly
        res = test_llm_connection(provider="Google Gemini", api_key="")
        self.assertFalse(res["success"])
        self.assertIn("missing", res["message"].lower())

        # Test 12.3: Google Gemini with mocked genai client success
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            res = test_llm_connection(provider="Google Gemini", api_key="test-key", model_name="gemini-3.8-flash")
            self.assertTrue(res["success"])
            self.assertEqual(res["message"], "Connection verified successfully!")
            mock_client.models.get.assert_called_with(model="gemini-3.8-flash")

        # Test 12.4: Google Gemini with client error returns failure details
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.get.side_effect = RuntimeError("API quota exceeded")
            mock_client_cls.return_value = mock_client
            res = test_llm_connection(provider="Google Gemini", api_key="test-key")
            self.assertFalse(res["success"])
            self.assertIn("quota exceeded", res["message"])

        # Test 12.5: OpenAI connection via mocked requests
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            res = test_llm_connection(provider="OpenAI", api_key="sk-test-key")
            self.assertTrue(res["success"])

        # Test 12.6: get_llm_config returns non-sensitive config
        with patch("exrp.api.control_plane.resolve_llm_config") as mock_resolve:
            mock_resolve.return_value = {
                "llm_provider": "Google Gemini",
                "model_name": "gemini-3.8-flash",
                "api_key": "secret-super-key",
                "api_base_url": None,
                "offline_mode": False,
                "temperature": 0.2,
                "max_retries": 2,
                "enable_sidecar": True,
            }
            cfg = get_llm_config()
            self.assertEqual(cfg["provider"], "Google Gemini")
            self.assertEqual(cfg["model_name"], "gemini-3.8-flash")
            self.assertTrue(cfg["has_api_key"])
            self.assertNotIn("secret-super-key", json.dumps(cfg))

            # Test 12.7: Masked password ('*****') from Frappe Password field falls back to decrypted key
            with patch("google.genai.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client_cls.return_value = mock_client
                res_masked = test_llm_connection(
                    provider="Google Gemini",
                    api_key="*****************************************************",
                    model_name="gemini-3.5-flash-lite",
                )
                self.assertTrue(res_masked["success"])
                mock_client_cls.assert_called_with(api_key="secret-super-key")

    def test_13_planner_defaults_from_settings(self):
        """
        Test 13: Verifies AIConfigurationPlanner adopts resolved defaults
        when parameters are not explicitly passed.
        """
        with patch("exrp.ai_control_plane.planner.resolve_llm_config") as mock_resolve:
            mock_resolve.return_value = {
                "llm_provider": "Google Gemini",
                "model_name": "gemini-custom-model",
                "api_key": "custom-key",
                "api_base_url": None,
                "offline_mode": False,
                "temperature": 0.5,
                "max_retries": 4,
                "enable_sidecar": True,
                "mock_mode": False,
            }
            with patch("google.genai.Client"):
                planner = AIConfigurationPlanner()
                self.assertEqual(planner.model, "gemini-custom-model")
                self.assertEqual(planner.api_key, "custom-key")
                self.assertEqual(planner.temperature, 0.5)
                self.assertEqual(planner.max_retries, 4)

    def test_14_conversational_workflow_planning_generates_valid_reachable_states(self):
        """
        Test 14: Verifies user prompt 'Set up a multi-stage approval workflow for Sales Order for high value orders'
        generates a valid create_workflow proposal with reachable states conforming to ADR-001 Rev 2.3.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Set up a multi-stage approval workflow for Sales Order for high value orders",
        )

        self.assertTrue(result.success, f"Expected success but got: {result.error_message}")
        self.assertIsNotNone(result.proposal)
        self.assertEqual(result.proposal.intent, "create_workflow")
        self.assertEqual(result.proposal.target_doctype, "Sales Order")
        self.assertEqual(result.proposal.governance_tier, 1)

        wf = result.proposal.workflow
        self.assertIsNotNone(wf)
        self.assertEqual(wf["document_type"], "Sales Order")
        self.assertTrue(wf["is_active"])
        self.assertEqual(wf["workflow_state_field"], "workflow_state")

        # Verify states
        state_names = [s["state"] for s in wf["states"]]
        self.assertIn("Draft", state_names)
        self.assertIn("Pending Manager Approval", state_names)
        self.assertIn("Approved", state_names)
        self.assertIn("Rejected", state_names)

        # Verify initial state docstatus
        draft_state = next(s for s in wf["states"] if s["state"] == "Draft")
        self.assertEqual(draft_state["doc_status"], 0)
        self.assertEqual(draft_state["allow_edit"], "Sales User")

        # Verify approved terminal state docstatus
        appr_state = next(s for s in wf["states"] if s["state"] == "Approved")
        self.assertEqual(appr_state["doc_status"], 1)

        # Verify transitions
        trans_actions = [(t["state"], t["action"], t["next_state"]) for t in wf["transitions"]]
        self.assertIn(("Draft", "Submit for Approval", "Pending Manager Approval"), trans_actions)
        self.assertIn(("Draft", "Approve Directly", "Approved"), trans_actions)
        self.assertIn(("Pending Manager Approval", "Approve", "Approved"), trans_actions)
        self.assertIn(("Pending Manager Approval", "Reject", "Rejected"), trans_actions)

        # Verify condition on high value orders
        submit_trans = next(t for t in wf["transitions"] if t["action"] == "Submit for Approval")
        self.assertEqual(submit_trans["condition"], "doc.grand_total > 10000")

    def test_15_workflow_graph_validation_attaches_mermaid_syntax(self):
        """
        Test 15: Verifies that static graph analysis generates and attaches Mermaid diagram syntax
        to PlannerResult.validation for visualization in Frappe Desk AI Sidecar.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Set up a multi-stage approval workflow for Sales Order for high value orders",
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.validation)
        self.assertIn("mermaid_graph", result.validation)

        mermaid = result.validation["mermaid_graph"]
        self.assertTrue(mermaid.startswith("graph TD"), "Mermaid diagram must start with 'graph TD'")
        self.assertIn('Draft["Draft (Draft)"]', mermaid)
        self.assertIn('Approved["Approved (Submitted)"]', mermaid)
        self.assertIn("-->", mermaid)
        self.assertIn("Submit for Approval", mermaid)
        self.assertIn("style Approved fill:#d4edda", mermaid)

    def test_16_workflow_invariant_attack_on_tier0_gl_entry_rejected(self):
        """
        Test 16: Verifies that an invariant attack attempting to attach a workflow to Tier 0
        DocType 'GL Entry' is rejected or refused cleanly without compromising enterprise invariants.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="GL Entry",
            user_prompt="Set up a multi-stage approval workflow for GL Entry with Manager approval",
            max_retries=2,
        )

        self.assertFalse(result.success, "Workflow attachment to Tier 0 GL Entry must be rejected.")
        self.assertIsNotNone(result.error_message)
        self.assertTrue(
            "gl entry" in result.error_message.lower() or "tier 0" in result.error_message.lower(),
            f"Error message must cite GL Entry or Tier 0: {result.error_message}"
        )
        self.assertGreaterEqual(len(result.feedback_history), 1)
        self.assertIn("rejected", result.feedback_history[0].lower())

    def test_17_workflow_self_correction_feedback_loop_on_unreachable_state(self):
        """
        Test 17: Verifies that proposing an invalid workflow state machine (e.g. unreachable state)
        triggers the self-correction feedback loop and corrects to a valid state machine.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Set up an unreachable test_self_correction workflow for Sales Order",
            max_retries=2,
        )

        self.assertTrue(result.success, "Should succeed after self-correcting on attempt 2")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.feedback_history), 1)
        self.assertIn("Your previous workflow proposal was rejected:", result.feedback_history[0])
        self.assertIn("unreachable", result.feedback_history[0].lower())
        self.assertIsNotNone(result.validation)
        self.assertIn("mermaid_graph", result.validation)

    def test_18_gemini_interactions_workflow_structured_generation(self):
        """
        Test 18: Verifies Google GenAI Interactions API client structured generation contract
        when generating a create_workflow declarative proposal.
        """
        recorded_call = {}

        class MockGeminiWorkflowInteractions:
            def create(self, **kwargs):
                recorded_call.update(kwargs)
                mock_json_response = {
                    "intent": "create_workflow",
                    "target_doctype": "Sales Order",
                    "summary": "Multi-stage Sales Order approval workflow",
                    "reasoning": "Interactions API structured output test",
                    "governance_tier": 1,
                    "changes": [],
                    "workflow": {
                        "workflow_name": "Sales Order Approval",
                        "document_type": "Sales Order",
                        "is_active": True,
                        "workflow_state_field": "workflow_state",
                        "states": [
                            {"state": "Draft", "doc_status": 0, "allow_edit": "Sales User", "style": "Inverse"},
                            {"state": "Pending Approval", "doc_status": 0, "allow_edit": "Sales Manager", "style": "Warning"},
                            {"state": "Approved", "doc_status": 1, "allow_edit": "Sales Manager", "style": "Success"},
                            {"state": "Rejected", "doc_status": 0, "allow_edit": "Sales Manager", "style": "Danger"},
                        ],
                        "transitions": [
                            {"state": "Draft", "action": "Submit for Approval", "next_state": "Pending Approval", "allowed": "Sales User"},
                            {"state": "Pending Approval", "action": "Approve", "next_state": "Approved", "allowed": "Sales Manager"},
                            {"state": "Pending Approval", "action": "Reject", "next_state": "Rejected", "allowed": "Sales Manager"},
                        ],
                    },
                }
                return types.SimpleNamespace(output_text=json.dumps(mock_json_response))

        class MockGenAIClient:
            def __init__(self):
                self.interactions = MockGeminiWorkflowInteractions()

        fake_client = MockGenAIClient()
        planner = AIConfigurationPlanner(client=fake_client, model="gemini-3.8-flash")
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Create approval workflow for Sales Order",
        )

        self.assertTrue(result.success)
        self.assertEqual(recorded_call["model"], "gemini-3.8-flash")
        self.assertIn("create_workflow", recorded_call["input"])
        self.assertIn("mermaid_graph", result.validation)
        self.assertTrue(result.validation["mermaid_graph"].startswith("graph TD"))

    def test_19_conversational_report_planning_valid_proposal(self):
        """
        Test 19: User prompt 'Generate a report of all pending Sales Orders over 25000'
        produces valid create_report proposal with columns, filters, and chart.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Generate a report of all pending Sales Orders over 25000",
        )

        self.assertTrue(result.success, f"Planning failed: {result.error_message}")
        self.assertIsNotNone(result.proposal)
        self.assertEqual(result.proposal.intent, "create_report")
        self.assertEqual(result.proposal.target_doctype, "Sales Order")
        self.assertIsNotNone(result.proposal.report)

        report = result.proposal.report
        self.assertEqual(report["ref_doctype"], "Sales Order")
        self.assertEqual(report["report_name"], "Sales Order High-Value Pending Report")

        # Verify columns
        self.assertIn("columns", report)
        col_names = [c["fieldname"] if isinstance(c, dict) else c.fieldname for c in report["columns"]]
        self.assertIn("name", col_names)
        self.assertIn("customer", col_names)
        self.assertIn("status", col_names)
        self.assertIn("grand_total", col_names)

        # Verify filters
        self.assertIn("filters", report)
        self.assertEqual(len(report["filters"]), 2)
        status_filter = next(f for f in report["filters"] if (f["fieldname"] if isinstance(f, dict) else f.fieldname) == "status")
        total_filter = next(f for f in report["filters"] if (f["fieldname"] if isinstance(f, dict) else f.fieldname) == "grand_total")
        self.assertEqual(status_filter["operator"] if isinstance(status_filter, dict) else status_filter.operator, "=")
        self.assertEqual(status_filter["value"] if isinstance(status_filter, dict) else status_filter.value, "Pending")
        self.assertEqual(total_filter["operator"] if isinstance(total_filter, dict) else total_filter.operator, ">")
        self.assertEqual(total_filter["value"] if isinstance(total_filter, dict) else total_filter.value, 25000)

        # Verify chart
        self.assertIsNotNone(report.get("chart"))
        chart = report["chart"]
        self.assertEqual(chart["chart_type"], "Bar")
        self.assertEqual(chart["x_field"], "customer")
        self.assertIn("grand_total", chart["y_fields"])

    def test_20_report_validation_attaches_preview_data(self):
        """
        Test 20: Verifies that declarative report planning validation attaches
        sample preview_data to PlannerResult.validation for UI preview in Sidecar.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Generate a report of all pending Sales Orders over 25000",
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.validation)
        self.assertIn("preview_data", result.validation)
        preview_data = result.validation["preview_data"]
        self.assertIsInstance(preview_data, list)
        self.assertGreater(len(preview_data), 0)
        first_row = preview_data[0]
        self.assertIn("name", first_row)
        self.assertIn("customer", first_row)
        self.assertIn("grand_total", first_row)

    def test_21_report_invariant_attack_on_tier0_user_rejected(self):
        """
        Test 21: Verifies that an invariant attack attempting to create a report on Tier 0
        restricted DocType 'User' is rejected cleanly without compromising enterprise invariants.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="User",
            user_prompt="Generate a report of all pending User accounts",
            max_retries=2,
        )

        self.assertFalse(result.success, "Report generation on Tier 0 User DocType must be rejected.")
        self.assertIsNotNone(result.error_message)
        self.assertTrue(
            "user" in result.error_message.lower() or "tier 0" in result.error_message.lower() or "prohibited" in result.error_message.lower(),
            f"Error message must cite User or prohibited: {result.error_message}"
        )
        self.assertGreaterEqual(len(result.feedback_history), 1)
        self.assertIn("rejected", result.feedback_history[0].lower())

    def test_22_report_self_correction_feedback_loop_on_invalid_operator(self):
        """
        Test 22: Verifies that proposing an invalid report filter operator
        triggers the self-correction feedback loop and corrects to a valid report definition.
        """
        planner = AIConfigurationPlanner(mock_mode=True)
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Create a report with invalid_operator test_self_correction for Sales Order",
            max_retries=2,
        )

        self.assertTrue(result.success, "Should succeed after self-correcting on attempt 2")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.feedback_history), 1)
        self.assertIn("Your previous report proposal was rejected:", result.feedback_history[0])
        self.assertIsNotNone(result.validation)
        self.assertIn("preview_data", result.validation)

    def test_23_gemini_interactions_report_structured_generation(self):
        """
        Test 23: Verifies Google GenAI Interactions API client structured generation contract
        when generating a create_report declarative proposal.
        """
        recorded_call = {}

        class MockGeminiReportInteractions:
            def create(self, **kwargs):
                recorded_call.update(kwargs)
                mock_json_response = {
                    "intent": "create_report",
                    "target_doctype": "Sales Order",
                    "summary": "Pending high-value Sales Orders report",
                    "reasoning": "Interactions API structured output test",
                    "governance_tier": 1,
                    "changes": [],
                    "report": {
                        "report_name": "Sales Order High-Value Pending Report",
                        "ref_doctype": "Sales Order",
                        "columns": [
                            {"fieldname": "name", "label": "ID"},
                            {"fieldname": "customer", "label": "Customer"},
                            {"fieldname": "status", "label": "Status"},
                            {"fieldname": "grand_total", "label": "Grand Total"},
                        ],
                        "filters": [
                            {"fieldname": "status", "operator": "=", "value": "Pending"},
                            {"fieldname": "grand_total", "operator": ">", "value": 25000},
                        ],
                        "sort_by": "grand_total",
                        "sort_order": "desc",
                        "chart": {
                            "chart_type": "Bar",
                            "x_field": "customer",
                            "y_fields": ["grand_total"],
                        },
                        "roles": ["All"],
                    },
                }
                return types.SimpleNamespace(output_text=json.dumps(mock_json_response))

        class MockGenAIClient:
            def __init__(self):
                self.interactions = MockGeminiReportInteractions()

        fake_client = MockGenAIClient()
        planner = AIConfigurationPlanner(client=fake_client, model="gemini-3.8-flash")
        result = planner.plan_change(
            doctype="Sales Order",
            user_prompt="Generate a report of all pending Sales Orders over 25000",
        )

        self.assertTrue(result.success)
        self.assertEqual(recorded_call["model"], "gemini-3.8-flash")
        self.assertIn("create_report", recorded_call["input"])
        self.assertIn("preview_data", result.validation)
        self.assertIsInstance(result.validation["preview_data"], list)


if __name__ == "__main__":
    unittest.main()
