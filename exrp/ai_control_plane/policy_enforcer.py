"""
EXRP Runtime Policy Enforcement Engine (ADR-001 Rev 2.3 §4.2 & §5)
Implements Frappe Document Lifecycle policy checks:
- Tier 0 ERP Invariant Protection (Credit Limit bypass, GL postings, Currency integrity)
- Tier 1 Governed Business Policies (Approval threshold gates, Field constraints, Submit locks)
- Document lifecycle stages: validate, before_submit, before_update_after_submit
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import re
from typing import Any, Callable, Dict, List, Optional, Set, Union

# Safe Frappe imports or standalone fallback
try:
    import frappe
    if not hasattr(frappe, "ValidationError"):
        class _FrappeValidationError(Exception):
            pass
        frappe.ValidationError = _FrappeValidationError
    ValidationError = frappe.ValidationError
except ImportError:
    class _FrappeValidationError(Exception):
        pass
    ValidationError = _FrappeValidationError
    frappe = None


class PolicyType(str, Enum):
    """Supported Policy Types under ADR-001 Rev 2.3"""
    THRESHOLD_GATE = "THRESHOLD_GATE"
    FIELD_CONSTRAINT = "FIELD_CONSTRAINT"
    SUBMIT_LOCK = "SUBMIT_LOCK"
    INVARIANT_GUARD = "INVARIANT_GUARD"


class RuntimePolicyViolation(ValidationError):
    """
    Raised when a document lifecycle runtime policy is violated (§4.2).
    Inherits from frappe.ValidationError for seamless Frappe Desk/API integration.
    """
    def __init__(
        self,
        message: str,
        policy_id: Optional[str] = None,
        result: Optional["PolicyEvaluationResult"] = None,
    ):
        super().__init__(message)
        self.message = message
        self.policy_id = policy_id
        self.result = result

    def __str__(self) -> str:
        return self.message


@dataclass
class RuntimePolicy:
    """
    Declarative Runtime Policy definition.
    governance_tier: 0 (Protected ERP Invariant) or 1 (Governed Business Configuration)
    """
    policy_id: str
    doctype: str
    policy_type: Union[PolicyType, str]
    target_field: Optional[str] = None
    governance_tier: int = 1
    condition_expr: Optional[str] = None
    required_role: Optional[str] = None
    error_message: str = ""
    active: bool = True
    stage: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.policy_type, PolicyType):
            self.policy_type = self.policy_type.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyEvaluationResult:
    """Outcome of evaluating policies against a document."""
    allowed: bool
    violated_policies: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


# Helpers for document inspection and safe condition evaluation

class SafeDocWrapper:
    """Wraps documents or dicts to provide safe attribute access and get() support."""
    def __init__(self, doc: Any):
        self._doc = doc

    def __getattr__(self, name: str) -> Any:
        if self._doc is None:
            return None
        if hasattr(self._doc, name):
            return getattr(self._doc, name)
        if isinstance(self._doc, dict) and name in self._doc:
            return self._doc[name]
        return None

    def get(self, name: str, default: Any = None) -> Any:
        if self._doc is None:
            return default
        if hasattr(self._doc, "get") and callable(self._doc.get):
            val = self._doc.get(name, default)
            return default if val is None else val
        if hasattr(self._doc, name):
            val = getattr(self._doc, name)
            return default if val is None else val
        return default

    def __getitem__(self, item: str) -> Any:
        return self.get(item)

    def __contains__(self, item: str) -> bool:
        if isinstance(self._doc, dict):
            return item in self._doc
        return hasattr(self._doc, item)


class SafeEvalContext(dict):
    """Dictionary context that returns None for undefined names instead of raising NameError."""
    def __missing__(self, key: str) -> Any:
        return None


def is_field_changed(doc: Any, fieldname: str) -> bool:
    """
    Determines if fieldname has been modified in the current transaction.
    Inspects standard Frappe lifecycle methods (has_value_changed, get_doc_before_save)
    and handles test mocks and dicts.
    """
    if not doc or not fieldname:
        return False

    # 1. Standard Frappe Document.has_value_changed
    if hasattr(doc, "has_value_changed") and callable(doc.has_value_changed):
        try:
            return bool(doc.has_value_changed(fieldname))
        except Exception:
            pass

    # 2. Compare with doc before save
    before_doc = None
    if hasattr(doc, "get_doc_before_save") and callable(doc.get_doc_before_save):
        try:
            before_doc = doc.get_doc_before_save()
        except Exception:
            pass
    elif hasattr(doc, "_doc_before_save"):
        before_doc = getattr(doc, "_doc_before_save")

    if before_doc is not None:
        curr_val = getattr(doc, fieldname, None) if hasattr(doc, fieldname) else (doc.get(fieldname) if isinstance(doc, dict) else None)
        prev_val = getattr(before_doc, fieldname, None) if hasattr(before_doc, fieldname) else (before_doc.get(fieldname) if isinstance(before_doc, dict) else None)
        return curr_val != prev_val

    # 3. Explicit modified fields list / flags
    if hasattr(doc, "_modified_fields"):
        return fieldname in getattr(doc, "_modified_fields")
    if hasattr(doc, "flags") and hasattr(doc.flags, "modified_fields"):
        return fieldname in doc.flags.modified_fields
    if isinstance(doc, dict) and "_modified_fields" in doc:
        return fieldname in doc["_modified_fields"]

    # 4. Fallback for submitted documents: if docstatus == 1 and field has a non-None value
    docstatus = getattr(doc, "docstatus", None) if hasattr(doc, "docstatus") else (doc.get("docstatus") if isinstance(doc, dict) else 0)
    if docstatus == 1:
        val = getattr(doc, fieldname, None) if hasattr(doc, fieldname) else (doc.get(fieldname) if isinstance(doc, dict) else None)
        return val is not None

    return False


def check_user_has_required_role(user_roles: Optional[List[str]], required_role: Optional[str]) -> bool:
    """Checks whether user has at least one of the comma/semicolon-separated required roles."""
    if not required_role:
        return False
    if not user_roles:
        return False
    required_set = {r.strip().lower() for r in re.split(r"[,;]", required_role) if r.strip()}
    user_set = {r.strip().lower() for r in user_roles if r.strip()}
    return bool(required_set & user_set)


def evaluate_condition_expr(expr: str, doc: Any, user_roles: Optional[List[str]]) -> bool:
    """Safely evaluates a Python condition expression against document attributes."""
    if not expr:
        return False

    wrapped_doc = SafeDocWrapper(doc)
    ctx = SafeEvalContext()

    # Populate doc fields as top-level variables
    if isinstance(doc, dict):
        ctx.update(doc)
    elif hasattr(doc, "__dict__"):
        for k, v in doc.__dict__.items():
            if not k.startswith("_") and not callable(v):
                ctx[k] = v

    # Add helper functions and context
    ctx["doc"] = wrapped_doc
    ctx["user_roles"] = user_roles or []
    ctx["has_role"] = lambda r: check_user_has_required_role(user_roles, r)
    ctx["is_field_changed"] = lambda f: is_field_changed(doc, f)

    # Safe builtins
    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "len": len,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
    }

    try:
        res = eval(expr, {"__builtins__": safe_builtins}, ctx)
        return bool(res)
    except (TypeError, ValueError, AttributeError, NameError):
        # Gracefully treat invalid type comparisons (e.g. None > 50000) as False
        return False
    except Exception:
        return False


def normalize_stage(stage: Optional[str]) -> Optional[str]:
    """Normalizes lifecycle stage string across Frappe aliases."""
    if not stage:
        return None
    s = stage.strip().lower().replace("-", "_")
    if s in ("validate", "on_validate"):
        return "validate"
    if s in ("submit", "before_submit", "on_submit"):
        return "submit"
    if s in ("update_after_submit", "before_update_after_submit", "on_update_after_submit"):
        return "update_after_submit"
    if s in ("*", "all"):
        return None
    return s


def is_policy_applicable_to_stage(policy: RuntimePolicy, norm_stage: Optional[str]) -> bool:
    """Determines if a policy applies to a given lifecycle stage."""
    if not norm_stage:
        return True

    if policy.stage:
        policy_norm_stage = normalize_stage(policy.stage)
        if policy_norm_stage is None or policy_norm_stage == norm_stage:
            return True
        return False

    # Default stage mapping based on policy_type
    p_type = policy.policy_type
    if p_type in (PolicyType.INVARIANT_GUARD, "INVARIANT_GUARD"):
        return True
    if p_type in (PolicyType.THRESHOLD_GATE, "THRESHOLD_GATE"):
        return norm_stage in ("validate", "submit")
    if p_type in (PolicyType.FIELD_CONSTRAINT, "FIELD_CONSTRAINT"):
        return norm_stage in ("validate", "submit", "update_after_submit")
    if p_type in (PolicyType.SUBMIT_LOCK, "SUBMIT_LOCK"):
        return norm_stage == "update_after_submit"

    return True


class RuntimePolicyCatalog:
    """
    Manages active runtime policies per DocType and evaluates Frappe Document Lifecycle hooks.
    ADR-001 Rev 2.3 (§4.2 & §5).
    """

    def __init__(self, register_defaults: bool = True):
        self._policies: Dict[str, List[RuntimePolicy]] = {}
        if register_defaults:
            self._register_default_policies()

    def reset(self) -> None:
        """Resets catalog to initial built-in Tier 0 policies."""
        self._policies.clear()
        self._register_default_policies()

    def _register_default_policies(self) -> None:
        """
        Registers built-in default Tier 0 protected ERP invariants:
        - Sales Order: Credit limit bypass check protection
        - Sales Invoice: GL ledger posting and currency tampering protection
        """
        # Tier 0 Invariant: Sales Order Credit Limit Check Bypass
        self.register_policy(
            RuntimePolicy(
                policy_id="TIER0_SO_CREDIT_LIMIT_BYPASS",
                doctype="Sales Order",
                policy_type=PolicyType.INVARIANT_GUARD,
                target_field="bypass_credit_limit_check",
                governance_tier=0,
                condition_expr="bypass_credit_limit_check == 1",
                required_role="Credit Controller, System Manager",
                error_message="Unauthorized bypass of credit limit check: requires 'Credit Controller' or 'System Manager' role.",
                active=True,
            )
        )

        # Tier 0 Invariant: Sales Invoice Currency Tampering
        self.register_policy(
            RuntimePolicy(
                policy_id="TIER0_SI_CURRENCY_TAMPERING",
                doctype="Sales Invoice",
                policy_type=PolicyType.INVARIANT_GUARD,
                target_field="conversion_rate",
                governance_tier=0,
                condition_expr="conversion_rate is not None and conversion_rate <= 0",
                required_role=None,
                error_message="Invalid currency conversion rate: conversion rate must be greater than zero.",
                active=True,
            )
        )

        # Tier 0 Invariant: Sales Invoice Currency Override Authorization
        self.register_policy(
            RuntimePolicy(
                policy_id="TIER0_SI_CURRENCY_OVERRIDE",
                doctype="Sales Invoice",
                policy_type=PolicyType.INVARIANT_GUARD,
                target_field="conversion_rate",
                governance_tier=0,
                condition_expr="is_field_changed('conversion_rate') or is_field_changed('party_account_currency')",
                required_role="Accounts Manager, Finance Director, System Manager",
                error_message="Unauthorized currency tampering: modifying multi-currency exchange rates requires 'Accounts Manager', 'Finance Director', or 'System Manager' role.",
                active=True,
            )
        )

        # Tier 0 Invariant: Sales Invoice GL Ledger Posting Protection
        self.register_policy(
            RuntimePolicy(
                policy_id="TIER0_SI_GL_POSTING_PROTECTION",
                doctype="Sales Invoice",
                policy_type=PolicyType.INVARIANT_GUARD,
                target_field="debit_to",
                governance_tier=0,
                condition_expr="override_gl_posting == 1 or (docstatus == 1 and (is_field_changed('debit_to') or is_field_changed('cost_center')))",
                required_role="Accounts Manager, Finance Director, System Manager",
                error_message="General Ledger postings are protected against unauthorized modification.",
                active=True,
            )
        )

    def register_policy(self, policy: RuntimePolicy) -> None:
        """Registers or updates a policy in the catalog."""
        doctype_policies = self._policies.setdefault(policy.doctype, [])
        # Update existing policy with same policy_id if present
        for idx, existing in enumerate(doctype_policies):
            if existing.policy_id == policy.policy_id:
                doctype_policies[idx] = policy
                return
        doctype_policies.append(policy)

    def unregister_policy(self, policy_id: str, doctype: Optional[str] = None) -> bool:
        """Removes a policy from the catalog by policy_id."""
        removed = False
        doctypes = [doctype] if doctype else list(self._policies.keys())
        for dt in doctypes:
            if dt in self._policies:
                initial_len = len(self._policies[dt])
                self._policies[dt] = [p for p in self._policies[dt] if p.policy_id != policy_id]
                if len(self._policies[dt]) < initial_len:
                    removed = True
        return removed

    def get_active_policies(self, doctype: str, stage: Optional[str] = None) -> List[RuntimePolicy]:
        """Returns all active policies for the specified DocType and lifecycle stage."""
        all_policies = self._policies.get(doctype, [])
        norm_stage = normalize_stage(stage)
        return [
            p for p in all_policies
            if p.active and is_policy_applicable_to_stage(p, norm_stage)
        ]

    def _evaluate_single_policy(
        self,
        policy: RuntimePolicy,
        doc: Any,
        stage: str,
        user_roles: List[str],
    ) -> bool:
        """
        Evaluates a single policy against doc and user_roles.
        Returns True if allowed (no violation), False if violated.
        """
        # Step 1: Check whether condition triggers
        condition_triggered = False
        if policy.condition_expr:
            condition_triggered = evaluate_condition_expr(policy.condition_expr, doc, user_roles)
        else:
            if policy.policy_type in (PolicyType.SUBMIT_LOCK, "SUBMIT_LOCK"):
                condition_triggered = is_field_changed(doc, policy.target_field)
            else:
                condition_triggered = True

        if not condition_triggered:
            return True  # Condition didn't trigger -> allowed

        # Step 2: Handle policy types
        p_type = policy.policy_type

        # THRESHOLD_GATE: Satisfied if target_field is populated on doc OR caller has required_role
        if p_type in (PolicyType.THRESHOLD_GATE, "THRESHOLD_GATE"):
            if policy.target_field:
                field_val = getattr(doc, policy.target_field, None) if hasattr(doc, policy.target_field) else (doc.get(policy.target_field) if isinstance(doc, dict) else None)
                if field_val:
                    return True  # Gate satisfied by document approval field
            # Check user role authorization
            return check_user_has_required_role(user_roles, policy.required_role)

        # SUBMIT_LOCK: Prevents updating locked field after submit
        if p_type in (PolicyType.SUBMIT_LOCK, "SUBMIT_LOCK"):
            if policy.required_role:
                return check_user_has_required_role(user_roles, policy.required_role)
            return False

        # INVARIANT_GUARD / FIELD_CONSTRAINT:
        if policy.required_role:
            return check_user_has_required_role(user_roles, policy.required_role)
        # If no role can bypass this invariant/constraint, it's violated
        return False

    def _evaluate_stage(
        self,
        doc: Any,
        stage: str,
        user_roles: Optional[List[str]] = None,
        raise_exception: bool = True,
    ) -> PolicyEvaluationResult:
        """Evaluates active policies for the specified lifecycle stage."""
        doctype = getattr(doc, "doctype", None) if hasattr(doc, "doctype") else (doc.get("doctype") if isinstance(doc, dict) else None)
        if not doctype:
            return PolicyEvaluationResult(allowed=True, violated_policies=[], reasons=[])

        if user_roles is None:
            user_roles = []

        policies = self.get_active_policies(doctype, stage=stage)
        violated_policies: List[str] = []
        reasons: List[str] = []

        for policy in policies:
            allowed = self._evaluate_single_policy(policy, doc, stage, user_roles)
            if not allowed:
                violated_policies.append(policy.policy_id)
                msg = policy.error_message or f"Document violates policy {policy.policy_id}"
                reasons.append(msg)

        if violated_policies:
            result = PolicyEvaluationResult(
                allowed=False,
                violated_policies=violated_policies,
                reasons=reasons,
            )
            if raise_exception:
                primary_id = violated_policies[0]
                primary_reason = reasons[0]
                error_msg = f"Runtime Policy Violation [{primary_id}]: {primary_reason}"
                raise RuntimePolicyViolation(error_msg, policy_id=primary_id, result=result)
            return result

        return PolicyEvaluationResult(allowed=True, violated_policies=[], reasons=[])

    def evaluate_validate(
        self,
        doc: Any,
        user_roles: Optional[List[str]] = None,
        raise_exception: bool = True,
        db: Any = None,
    ) -> PolicyEvaluationResult:
        """Evaluates policies applicable to Document.validate."""
        res = self._evaluate_stage(doc, stage="validate", user_roles=user_roles, raise_exception=False)
        from .cross_doc_policy import cross_doc_catalog
        cross_res = cross_doc_catalog.evaluate_cross_doc_policies(doc, stage="validate", db=db)

        combined_violated = list(res.violated_policies) + list(cross_res.violated_policies)
        combined_reasons = list(res.reasons) + list(cross_res.reasons)
        allowed = (len(combined_violated) == 0)

        result = PolicyEvaluationResult(
            allowed=allowed,
            violated_policies=combined_violated,
            reasons=combined_reasons,
        )
        if not allowed and raise_exception:
            primary_id = combined_violated[0]
            primary_reason = combined_reasons[0]
            error_msg = f"Runtime Policy Violation [{primary_id}]: {primary_reason}"
            raise RuntimePolicyViolation(error_msg, policy_id=primary_id, result=result)
        return result

    def evaluate_submit(
        self,
        doc: Any,
        user_roles: Optional[List[str]] = None,
        raise_exception: bool = True,
        db: Any = None,
    ) -> PolicyEvaluationResult:
        """Evaluates policies applicable to Document.before_submit."""
        res = self._evaluate_stage(doc, stage="submit", user_roles=user_roles, raise_exception=False)
        from .cross_doc_policy import cross_doc_catalog
        cross_res = cross_doc_catalog.evaluate_cross_doc_policies(doc, stage="submit", db=db)

        combined_violated = list(res.violated_policies) + list(cross_res.violated_policies)
        combined_reasons = list(res.reasons) + list(cross_res.reasons)
        allowed = (len(combined_violated) == 0)

        result = PolicyEvaluationResult(
            allowed=allowed,
            violated_policies=combined_violated,
            reasons=combined_reasons,
        )
        if not allowed and raise_exception:
            primary_id = combined_violated[0]
            primary_reason = combined_reasons[0]
            error_msg = f"Runtime Policy Violation [{primary_id}]: {primary_reason}"
            raise RuntimePolicyViolation(error_msg, policy_id=primary_id, result=result)
        return result

    def evaluate_update_after_submit(
        self,
        doc: Any,
        user_roles: Optional[List[str]] = None,
        raise_exception: bool = True,
    ) -> PolicyEvaluationResult:
        """Evaluates policies applicable to Document.before_update_after_submit."""
        return self._evaluate_stage(doc, stage="update_after_submit", user_roles=user_roles, raise_exception=raise_exception)


# Global default instance
policy_catalog = RuntimePolicyCatalog()
