"""
EXRP AI Control Plane Conversational Planner (ADR-001 Rev 2.3)
Generates structured configuration proposals using Google GenAI SDK (Interactions API),
validates against enterprise safety guardrails and DDL plan gates, and executes
an automated self-correction feedback loop.
"""

import os
import re
import json
from typing import Dict, Any, List, Optional, Literal, Union, Callable
from pydantic import BaseModel, Field, ConfigDict, ValidationError, field_validator

try:
    import frappe
except ImportError:
    frappe = None

from exrp.ai_control_plane.schema_extractor import get_compact_doctype_schema
from exrp.ai_control_plane.safety_guardrails import (
    validate_mutation_safety,
    ZoneSafetyViolation,
    ZONE_2_LOCKED_DOCTYPES,
    PROTECTED_STANDARD_FIELDS,
    PHASE_1_ALLOWED_FIELDTYPES,
)
from exrp.ai_control_plane.ddl_plan_gate import (
    inspect_frappe_ddl_plan,
    DDLPlanInspection,
)


class ProposedFieldChange(BaseModel):
    """
    Proposed single custom field definition adhering to ADR-001 Rev 2.3 §5.1.
    """
    model_config = ConfigDict(extra="allow")

    fieldname: str = Field(
        ...,
        description="Canonical lower snake_case fieldname starting with 'custom_' matching ^custom_[a-z][a-z0-9_]{1,50}$"
    )
    label: str = Field(..., description="Human-readable label for the field")
    fieldtype: str = Field(
        ...,
        description="Frappe field type: Data, Check, Int, Float, Date, Datetime, Select, Link"
    )
    options: Optional[str] = Field(
        default=None,
        description="Options for Select (newline-separated) or Link target DocType"
    )
    reqd: int = Field(
        default=0,
        description="1 if mandatory, 0 if optional. Must be 0 in Phase 1 unless default provided."
    )
    read_only: int = Field(default=0, description="1 if read-only, 0 otherwise")
    description: Optional[str] = Field(default=None, description="Help text or field description")
    insert_after: Optional[str] = Field(default=None, description="Anchor fieldname for UI placement")
    default: Optional[str] = Field(default=None, description="Default value")

    @field_validator("fieldname", mode="before")
    @classmethod
    def normalize_fieldname(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return str(v)


class ConfigurationProposal(BaseModel):
    """
    Declarative configuration change proposal produced by the AI Planner.
    Adheres strictly to ADR-001 Rev 2.3 §5.
    """
    model_config = ConfigDict(extra="allow")

    intent: Literal["add_custom_fields", "set_property", "workflow_action"] = Field(
        ...,
        description="Declarative configuration intent"
    )
    target_doctype: str = Field(..., description="Target DocType being configured")
    summary: str = Field(..., description="High-level description of proposed change")
    reasoning: str = Field(..., description="Design rationale and justification for change")
    changes: List[Union[ProposedFieldChange, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Proposed change items. Max 1 field in Phase 1 for add_custom_fields."
    )
    governance_tier: int = Field(
        default=1,
        description="Governance Tier (0=Immutable Invariant, 1=Governed Policy, 2=Ordinary Config)"
    )


class PlannerResult(BaseModel):
    """
    Outcome of an AI planning execution turn, including safety validation,
    DDL gate evidence, and full self-correction feedback history.
    """
    model_config = ConfigDict(extra="allow")

    success: bool
    proposal: Optional[ConfigurationProposal] = None
    validation: Optional[Dict[str, Any]] = None
    ddl_plan: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    attempts: int = 1
    feedback_history: List[str] = Field(default_factory=list)


def resolve_llm_config() -> Dict[str, Any]:
    """
    Resolves runtime LLM configuration adhering to ADR-001 Rev 2.3:
    1. Reads from Frappe Single DocType 'EXRP Settings' if Frappe runtime is available.
    2. Uses settings.get_password("api_key") or settings.api_key if set.
    3. Falls back to os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY").
    4. Checks settings.offline_mode or settings.llm_provider == 'Mock / Offline Test Mode'.
    """
    settings_dict: Dict[str, Any] = {}
    api_key: Optional[str] = None
    settings_doc = None

    if frappe:
        try:
            if hasattr(frappe, "get_single"):
                settings_doc = frappe.get_single("EXRP Settings")
            elif hasattr(frappe, "db") and hasattr(frappe.db, "get_singles_dict"):
                settings_dict = frappe.db.get_singles_dict("EXRP Settings") or {}
        except Exception:
            settings_doc = None
            settings_dict = {}

    if settings_doc is not None:
        if hasattr(settings_doc, "as_dict") and callable(settings_doc.as_dict):
            try:
                settings_dict = settings_doc.as_dict()
            except Exception:
                settings_dict = {}
        elif isinstance(settings_doc, dict):
            settings_dict = settings_doc
        elif hasattr(settings_doc, "__dict__"):
            settings_dict = dict(settings_doc.__dict__)

        # Resolve api_key via get_password if available
        if hasattr(settings_doc, "get_password") and callable(settings_doc.get_password):
            try:
                api_key = settings_doc.get_password("api_key", raise_exception=False)
            except Exception:
                api_key = None
        if not api_key:
            api_key = getattr(settings_doc, "api_key", None)

    if not api_key:
        api_key = settings_dict.get("api_key")

    # Fallback to environment variables
    if not api_key:
        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )

    # Provider
    llm_provider = settings_dict.get("llm_provider") or getattr(settings_doc, "llm_provider", None)
    if not llm_provider:
        if os.environ.get("GEMINI_API_KEY"):
            llm_provider = "Google Gemini"
        elif os.environ.get("OPENAI_API_KEY"):
            llm_provider = "OpenAI"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            llm_provider = "Anthropic"
        else:
            llm_provider = "Google Gemini"

    # Model name
    model_name = (
        settings_dict.get("model_name")
        or getattr(settings_doc, "model_name", None)
        or os.environ.get("EXRP_MODEL_NAME")
        or "gemini-3.8-flash"
    )

    # Custom base URL
    api_base_url = (
        settings_dict.get("api_base_url")
        or getattr(settings_doc, "api_base_url", None)
        or os.environ.get("LLM_BASE_URL")
    )

    # Numeric & boolean options
    raw_temp = settings_dict.get("temperature") if "temperature" in settings_dict else getattr(settings_doc, "temperature", 0.2)
    try:
        temperature = float(raw_temp if raw_temp is not None else 0.2)
    except (ValueError, TypeError):
        temperature = 0.2

    raw_retries = settings_dict.get("max_retries") if "max_retries" in settings_dict else getattr(settings_doc, "max_retries", 2)
    try:
        max_retries = int(raw_retries if raw_retries is not None else 2)
    except (ValueError, TypeError):
        max_retries = 2

    raw_sidecar = settings_dict.get("enable_sidecar") if "enable_sidecar" in settings_dict else getattr(settings_doc, "enable_sidecar", 1)
    enable_sidecar = bool(int(raw_sidecar if raw_sidecar is not None else 1))

    raw_offline = settings_dict.get("offline_mode") if "offline_mode" in settings_dict else getattr(settings_doc, "offline_mode", 0)
    offline_mode = bool(int(raw_offline if raw_offline is not None else 0))

    raw_lock = settings_dict.get("strict_tier0_lock") if "strict_tier0_lock" in settings_dict else getattr(settings_doc, "strict_tier0_lock", 1)
    strict_tier0_lock = bool(int(raw_lock if raw_lock is not None else 1))

    raw_timeout = settings_dict.get("lock_wait_timeout") if "lock_wait_timeout" in settings_dict else getattr(settings_doc, "lock_wait_timeout", 3)
    try:
        lock_wait_timeout = int(raw_timeout if raw_timeout is not None else 3)
    except (ValueError, TypeError):
        lock_wait_timeout = 3

    # Mock mode determination:
    # Checks settings.offline_mode or settings.llm_provider == 'Mock / Offline Test Mode'
    mock_mode = (
        offline_mode
        or (llm_provider == "Mock / Offline Test Mode")
        or (not api_key and llm_provider != "Mock / Offline Test Mode")
    )

    return {
        "llm_provider": llm_provider,
        "model_name": model_name,
        "api_key": api_key,
        "api_base_url": api_base_url,
        "temperature": temperature,
        "max_retries": max_retries,
        "enable_sidecar": enable_sidecar,
        "offline_mode": offline_mode,
        "strict_tier0_lock": strict_tier0_lock,
        "lock_wait_timeout": lock_wait_timeout,
        "mock_mode": mock_mode,
    }


class AIConfigurationPlanner:
    """
    Conversational Configuration Planner for Frappe/ERPNext.
    Adheres to ADR-001 Rev 2.3:
    - Ingests token-efficient DocType schema via get_compact_doctype_schema.
    - Generates structured proposals via Google GenAI Interactions API or deterministic mock fallback.
    - Enforces Phase 1 single-field deployment unit constraint (max 1 field per proposal).
    - Executes an automated self-correction feedback loop on safety violations or DDL rejections.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Any = None,
        mock_mode: Optional[bool] = None,
        truncate_to_single_field: bool = False,
        ddl_inspector: Optional[Callable] = None,
        temperature: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        config = resolve_llm_config()

        self.model = model or config.get("model_name") or "gemini-3.8-flash"
        self.api_key = api_key or config.get("api_key")
        self.temperature = temperature if temperature is not None else config.get("temperature", 0.2)
        self.max_retries = max_retries if max_retries is not None else config.get("max_retries", 2)
        self.provider = config.get("llm_provider", "Google Gemini")
        self.api_base_url = config.get("api_base_url")
        self.offline_mode = config.get("offline_mode", False)
        self.client = client
        self.truncate_to_single_field = truncate_to_single_field
        self.ddl_inspector = ddl_inspector

        # Determine mock mode: offline/CI default unless client or API key supplied
        if mock_mode is not None:
            self.mock_mode = mock_mode
        elif self.offline_mode or self.provider == "Mock / Offline Test Mode":
            self.mock_mode = True
        elif self.client is not None:
            self.mock_mode = False
        elif self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                self.mock_mode = False
            except Exception:
                self.client = None
                self.mock_mode = True
        else:
            self.mock_mode = True

    def plan_change(
        self,
        doctype: str,
        user_prompt: str,
        user_roles: Optional[List[str]] = None,
        max_retries: Optional[int] = None,
    ) -> PlannerResult:
        """
        Plans, validates, and gates a configuration change based on natural language input.
        If validation or DDL gating rejects the proposal, feeds the error back into the model
        for iterative self-correction up to max_retries.
        """
        user_roles = user_roles or ["System Manager"]
        compact_schema = get_compact_doctype_schema(doctype)
        effective_max_retries = max_retries if max_retries is not None else getattr(self, "max_retries", 2)

        feedback_history: List[str] = []
        attempts = 0
        last_proposal: Optional[ConfigurationProposal] = None
        last_validation: Optional[Dict[str, Any]] = None
        last_ddl_plan: Optional[Dict[str, Any]] = None
        last_error: Optional[str] = None

        while attempts <= effective_max_retries:
            attempts += 1

            # 1. Generate Proposal
            try:
                if self.mock_mode or not self.client:
                    proposal = self._generate_mock_proposal(
                        doctype=doctype,
                        user_prompt=user_prompt,
                        feedback_history=feedback_history,
                        attempt=attempts,
                    )
                else:
                    proposal = self._call_gemini_interactions(
                        doctype=doctype,
                        user_prompt=user_prompt,
                        compact_schema=compact_schema,
                        user_roles=user_roles,
                        feedback_history=feedback_history,
                    )
            except Exception as exc:
                reason = f"Generation error: {exc}"
                last_error = reason
                feedback = (
                    f"Your previous proposal was rejected: {reason}. "
                    "Correct the proposal to satisfy enterprise safety invariants."
                )
                feedback_history.append(feedback)
                if attempts > effective_max_retries:
                    return PlannerResult(
                        success=False,
                        proposal=last_proposal,
                        validation=None,
                        ddl_plan=None,
                        error_message=last_error,
                        attempts=attempts,
                        feedback_history=feedback_history,
                    )
                continue

            last_proposal = proposal

            # 2. Phase 1 Single-Field Unit Enforcement (§5.1)
            if proposal.intent == "add_custom_fields" and len(proposal.changes) > 1:
                if self.truncate_to_single_field or attempts > effective_max_retries:
                    proposal.changes = proposal.changes[:1]
                    proposal.summary += " (Phase 1 constraint: truncated to single field deployment unit)"

            # 3. Policy & Invariant Safety Evaluation
            proposal_dict = proposal.model_dump()
            proposal_dict["target_doctype"] = doctype
            proposal_dict["user_roles"] = user_roles

            try:
                validation_result = validate_mutation_safety(proposal_dict)
                last_validation = validation_result
            except ZoneSafetyViolation as exc:
                reason = str(exc)
                last_error = reason
                feedback = (
                    f"Your previous proposal was rejected: {reason}. "
                    "Correct the proposal to satisfy enterprise safety invariants."
                )
                feedback_history.append(feedback)
                if attempts > effective_max_retries:
                    return PlannerResult(
                        success=False,
                        proposal=proposal,
                        validation=None,
                        ddl_plan=None,
                        error_message=reason,
                        attempts=attempts,
                        feedback_history=feedback_history,
                    )
                continue
            except (ValidationError, ValueError) as exc:
                reason = f"Proposal schema validation error: {exc}"
                last_error = reason
                feedback = (
                    f"Your previous proposal was rejected: {reason}. "
                    "Correct the proposal to satisfy enterprise safety invariants."
                )
                feedback_history.append(feedback)
                if attempts > effective_max_retries:
                    return PlannerResult(
                        success=False,
                        proposal=proposal,
                        validation=None,
                        ddl_plan=None,
                        error_message=reason,
                        attempts=attempts,
                        feedback_history=feedback_history,
                    )
                continue

            # 4. DDL Plan Gate Inspection (Zero DDL executed)
            ddl_plan_dict = None
            if proposal.intent == "add_custom_fields":
                if not proposal.changes:
                    reason = "Intent 'add_custom_fields' requires at least one field change."
                    last_error = reason
                    feedback = (
                        f"Your previous proposal was rejected: {reason}. "
                        "Correct the proposal to satisfy enterprise safety invariants."
                    )
                    feedback_history.append(feedback)
                    if attempts > effective_max_retries:
                        return PlannerResult(
                            success=False,
                            proposal=proposal,
                            validation=validation_result,
                            ddl_plan=None,
                            error_message=reason,
                            attempts=attempts,
                            feedback_history=feedback_history,
                        )
                    continue

                field_def = proposal_dict["changes"][0]
                if self.ddl_inspector:
                    ddl_inspection = self.ddl_inspector(doctype, field_def)
                else:
                    ddl_inspection = inspect_frappe_ddl_plan(doctype, field_def)

                ddl_plan_dict = {
                    "inspectable": ddl_inspection.inspectable,
                    "statements": ddl_inspection.statements,
                    "is_approved_additive_only": ddl_inspection.is_approved_additive_only,
                    "rejection_reason": ddl_inspection.rejection_reason,
                }
                last_ddl_plan = ddl_plan_dict

                if not ddl_inspection.is_approved_additive_only:
                    reason = ddl_inspection.rejection_reason or "Unapproved DDL plan"
                    last_error = reason
                    feedback = (
                        f"Your previous proposal was rejected: {reason}. "
                        "Correct the proposal to satisfy enterprise safety invariants."
                    )
                    feedback_history.append(feedback)
                    if attempts > effective_max_retries:
                        return PlannerResult(
                            success=False,
                            proposal=proposal,
                            validation=validation_result,
                            ddl_plan=ddl_plan_dict,
                            error_message=reason,
                            attempts=attempts,
                            feedback_history=feedback_history,
                        )
                    continue

            # 5. Success: Validated and Approved
            return PlannerResult(
                success=True,
                proposal=proposal,
                validation=validation_result,
                ddl_plan=ddl_plan_dict,
                error_message=None,
                attempts=attempts,
                feedback_history=feedback_history,
            )

        # Fallback if loop ends without success
        return PlannerResult(
            success=False,
            proposal=last_proposal,
            validation=last_validation,
            ddl_plan=last_ddl_plan,
            error_message=last_error or "Max retries exceeded without valid configuration proposal",
            attempts=attempts,
            feedback_history=feedback_history,
        )

    def _call_gemini_interactions(
        self,
        doctype: str,
        user_prompt: str,
        compact_schema: Dict[str, Any],
        user_roles: List[str],
        feedback_history: List[str],
    ) -> ConfigurationProposal:
        """Invokes Google GenAI Interactions API with structured output schema."""
        system_instruction = (
            "You are the EXRP AI Configuration Planner adhering strictly to ADR-001 Rev 2.3.\n"
            "Generate a declarative configuration proposal for Frappe/ERPNext.\n"
            "Invariants and Constraints:\n"
            "1. For 'add_custom_fields', output at most ONE field in 'changes' (single-field deployment unit).\n"
            "2. Canonical fieldname must match ^custom_[a-z][a-z0-9_]{1,50}$ (lowercase snake_case starting with 'custom_').\n"
            "3. Allowed fieldtypes in Phase 1: Data, Check, Int, Float, Date, Datetime, Select, Link.\n"
            "4. New custom fields must be nullable/optional (reqd=0 unless default provided).\n"
            "5. Flags unique, search_index, is_virtual, and allow_on_submit are PROHIBITED.\n"
            "6. Invariant Protection: NEVER modify, delete, or relax protected ERP standard fields "
            "(e.g., total, rate, amount, docstatus).\n"
            "7. Compliance Lock: NEVER modify Zone 2 locked DocTypes (e.g. GL Entry, Journal Entry, User, Role).\n"
        )

        user_content = (
            f"Target DocType: {doctype}\n"
            f"User Roles: {user_roles}\n"
            f"Schema Context:\n{json.dumps(compact_schema, indent=2)}\n\n"
            f"User Request: {user_prompt}"
        )

        if feedback_history:
            user_content += "\n\nPrevious Rejections & Enterprise Feedback History:\n" + "\n".join(feedback_history)

        full_input = f"{system_instruction}\n\n{user_content}"

        response = self.client.interactions.create(
            model=self.model,
            input=full_input,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": ConfigurationProposal.model_json_schema(),
            },
        )

        raw_text = self._extract_text_from_interaction(response)
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
            data = json.loads(cleaned)

        return ConfigurationProposal.model_validate(data)

    def _extract_text_from_interaction(self, response: Any) -> str:
        """Extracts text content from Gemini Interactions response or test double."""
        if hasattr(response, "output_text") and response.output_text:
            return response.output_text
        if isinstance(response, dict) and response.get("output_text"):
            return response["output_text"]
        if hasattr(response, "text") and response.text:
            return response.text
        if isinstance(response, str):
            return response

        steps = getattr(response, "steps", None) or (response.get("steps") if isinstance(response, dict) else None)
        if steps and isinstance(steps, list):
            parts = []
            for step in steps:
                content = getattr(step, "content", None) or (step.get("content") if isinstance(step, dict) else None)
                if isinstance(content, list):
                    for item in content:
                        txt = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else None)
                        if txt:
                            parts.append(txt)
            if parts:
                return "".join(parts)

        return str(response)

    def _generate_mock_proposal(
        self,
        doctype: str,
        user_prompt: str,
        feedback_history: List[str],
        attempt: int,
    ) -> ConfigurationProposal:
        """
        Deterministic heuristic mock generator for offline and CI environments.
        Accurately parses prompts, obeys self-correction feedback history, and tests
        single-field limits, invariant protections, and DDL plan gate behaviors.
        """
        prompt_lower = user_prompt.lower()

        # 1. Invariant Attack Handling (Tier 0 Protection & Zone 2 locked DocTypes)
        is_attack_doctype = doctype in ZONE_2_LOCKED_DOCTYPES
        is_attack_action = any(
            w in prompt_lower
            for w in ("delete", "drop", "modify", "remove", "unlock", "relax", "bypass", "override")
        )
        is_attack_field = any(
            f in prompt_lower
            for f in ("rate", "amount", "total", "docstatus", "cost_center", "credit_limit")
        )

        if is_attack_doctype:
            return ConfigurationProposal(
                intent="add_custom_fields",
                target_doctype=doctype,
                summary=f"Attempted customization on protected DocType {doctype}",
                reasoning="Mock generator simulated modification on locked DocType",
                changes=[
                    ProposedFieldChange(
                        fieldname="custom_test_col",
                        label="Test Col",
                        fieldtype="Data",
                    )
                ],
                governance_tier=0,
            )

        if is_attack_action and is_attack_field:
            matched_field = "rate" if "rate" in prompt_lower else "total"
            if "delete" in prompt_lower or "drop" in prompt_lower:
                return ConfigurationProposal(
                    intent="set_property",
                    target_doctype=doctype,
                    summary=f"Attempt to drop/modify standard field {matched_field}",
                    reasoning=f"User requested dropping or modifying {matched_field}",
                    changes=[{"fieldname": matched_field, "property": "read_only", "value": 0}],
                    governance_tier=0,
                )
            else:
                return ConfigurationProposal(
                    intent="set_property",
                    target_doctype=doctype,
                    summary=f"Modify {matched_field} on {doctype}",
                    reasoning=f"User requested modifying protected standard field {matched_field}",
                    changes=[{"fieldname": matched_field, "property": "read_only", "value": 0}],
                    governance_tier=0,
                )

        # 2. Multiple Field Request Handling & Phase 1 Self-Correction
        is_multi_field = (
            (" and " in prompt_lower or " & " in prompt_lower or "two fields" in prompt_lower or "multiple" in prompt_lower)
            and not ("low, medium, high" in prompt_lower)
        )
        has_single_field_feedback = any(
            "single-field" in fb.lower() or "one physical field" in fb.lower()
            for fb in feedback_history
        )

        if is_multi_field:
            if has_single_field_feedback:
                # Self-corrected: reduce to single field
                return ConfigurationProposal(
                    intent="add_custom_fields",
                    target_doctype=doctype,
                    summary="Add priority status field (self-corrected to single field)",
                    reasoning="Self-corrected down to 1 field in response to enterprise safety invariant feedback",
                    changes=[
                        ProposedFieldChange(
                            fieldname="custom_priority_status",
                            label="Priority Status",
                            fieldtype="Select",
                            options="Low\nMedium\nHigh",
                            default="Low",
                        )
                    ],
                    governance_tier=1,
                )
            else:
                # First attempt: produce multiple fields to test constraint enforcement
                return ConfigurationProposal(
                    intent="add_custom_fields",
                    target_doctype=doctype,
                    summary="Add priority status and escalation notes fields",
                    reasoning="User requested multiple fields",
                    changes=[
                        ProposedFieldChange(
                            fieldname="custom_priority_status",
                            label="Priority Status",
                            fieldtype="Select",
                            options="Low\nMedium\nHigh",
                            default="Low",
                        ),
                        ProposedFieldChange(
                            fieldname="custom_escalation_notes",
                            label="Escalation Notes",
                            fieldtype="Data",
                        ),
                    ],
                    governance_tier=1,
                )

        # 3. DDL Gate Feedback Self-Correction Handling
        has_ddl_feedback = any(
            "unapproved" in fb.lower() or "ddl" in fb.lower() or "modify" in fb.lower()
            for fb in feedback_history
        )

        # 4. Standard Single Field Proposal Generation
        if "dropdown" in prompt_lower or "select" in prompt_lower or "priority" in prompt_lower:
            fieldtype = "Select"
            fieldname = "custom_priority_status"
            label = "Priority Status"
            options = "Low\nMedium\nHigh"
            default = "Low"
        elif "checkbox" in prompt_lower or "check" in prompt_lower or "vip" in prompt_lower:
            fieldtype = "Check"
            fieldname = "custom_is_vip"
            label = "Is VIP"
            options = None
            default = "0"
        elif "date" in prompt_lower or "delivery" in prompt_lower:
            fieldtype = "Date"
            fieldname = "custom_expected_delivery_date"
            label = "Expected Delivery Date"
            options = None
            default = None
        elif "notes" in prompt_lower or "comment" in prompt_lower:
            fieldtype = "Data"
            fieldname = "custom_dispatch_notes"
            label = "Dispatch Notes"
            options = None
            default = None
        elif "tracking" in prompt_lower or "cargo" in prompt_lower:
            fieldtype = "Data"
            fieldname = "custom_cargo_tracking_id"
            label = "Cargo Tracking ID"
            options = None
            default = None
        else:
            # Fallback slugification
            raw_words = [
                re.sub(r"[^a-z0-9]", "", w)
                for w in prompt_lower.split()
                if w not in ("add", "a", "an", "the", "field", "column", "with", "for", "to", "on", "in")
            ]
            clean_words = [w for w in raw_words if w][:3]
            slug = "_".join(clean_words) if clean_words else "custom_field"
            fieldname = f"custom_{slug}" if not slug.startswith("custom_") else slug
            label = " ".join(clean_words).title() if clean_words else "Custom Field"
            fieldtype = "Data"
            options = None
            default = None

        return ConfigurationProposal(
            intent="add_custom_fields",
            target_doctype=doctype,
            summary=f"Add {label} custom field to {doctype}",
            reasoning=f"User requested: '{user_prompt}'",
            changes=[
                ProposedFieldChange(
                    fieldname=fieldname,
                    label=label,
                    fieldtype=fieldtype,
                    options=options,
                    default=default,
                )
            ],
            governance_tier=1,
        )
