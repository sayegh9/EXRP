"""
EXRP Two-Axis Policy Compiler, Protected Invariant Registry & Phase 1 Additive Field Validator
Implements ADR-001 (Rev 2.3) Section 5 & Section 5.1:
- Axis 1 (Storage Impact): METADATA_ONLY, ONLINE_ADDITIVE_DDL, DATA_SEMANTIC, DESTRUCTIVE_DDL
- Axis 2 (Governance Tier):
  * TIER_0_IMMUTABLE_INVARIANT: Protected ERP invariants (parent + child DocTypes)
  * TIER_1_GOVERNED_POLICY: EXRP-created approval thresholds/policies (tightened or relaxed with authority)
  * TIER_2_ORDINARY_CONFIG: Safe optional fields and low-impact presentation changes
- Phase 1 Additive Restrictions (§5.1):
  * One new physical field per deployment unit; nullable, non-unique, no index creation,
    no `allow_on_submit` or `is_virtual`.
  * Candidate subset: `Data`, `Check`, `Int`, `Float`, `Date`, `Datetime`, `Select`, `Link`.
  * Validates `Select` choices (duplicates, defaults) and `Link` target resolution.
"""

import re
from typing import Dict, Any, Set


class ZoneSafetyViolation(Exception):
    """Raised when an AI proposal violates compiler, storage-impact, invariant, or authority rules."""
    pass


TIER_1_GOVERNANCE_ROLES: Set[str] = {
    "System Manager",
    "Finance Director",
    "Operations Director",
}

ZONE_2_LOCKED_DOCTYPES: Set[str] = {
    "GL Entry",
    "Payment Ledger Entry",
    "Journal Entry",
    "Journal Entry Account",
    "Fiscal Year",
    "Period Closing Voucher",
    "Chart of Accounts",
    "Account",
    "Mode of Payment",
    "Tax Rule",
    "Tax Category",
    "Sales Taxes and Charges Template",
    "Purchase Taxes and Charges Template",
    "Sales Taxes and Charges",
    "Purchase Taxes and Charges",
    "Customer Credit Limit",
    "Payment Schedule",
    "Version",
    "Activity Log",
    "Audit Trail",
    "EXRP Audit Log",
    "EXRP Deployment",
    "EXRP Field Provenance",
    "DocShare",
    "DocPerm",
    "Custom DocPerm",
    "User",
    "Role",
    "System Settings",
    "EXRP Settings",
}

PROTECTED_STANDARD_FIELDS: Set[str] = {
    # Parent Financial & Tax Totals
    "total",
    "net_total",
    "grand_total",
    "base_total",
    "base_net_total",
    "base_grand_total",
    "rounded_total",
    "rounding_adjustment",
    "total_taxes_and_charges",
    "base_total_taxes_and_charges",
    "taxes",
    "taxes_and_charges",
    "item_tax_template",
    "additional_discount_percentage",
    "discount_amount",
    "apply_discount_on",

    # Child-Table Line-Item Pricing, Rate, Discount & Source Link Fields
    "rate",
    "amount",
    "base_rate",
    "base_amount",
    "net_rate",
    "net_amount",
    "price_list_rate",
    "margin_type",
    "margin_rate_or_amount",
    "rate_with_margin",
    "discount_percentage",
    "distributed_discount_amount",
    "item_tax_rate",
    "valuation_rate",
    "stock_qty",
    "conversion_factor",
    "sales_order",
    "so_detail",
    "delivery_note",
    "dn_detail",
    "prevdoc_docname",

    # Credit Limit & Accounting Controls
    "credit_limits",
    "credit_limit",
    "bypass_credit_limit_check",
    "is_frozen",
    "disabled",
    "debit_to",
    "credit_to",
    "cost_center",
    "party_account_currency",
    "conversion_rate",
    "plc_conversion_rate",

    # Document Lifecycle & Billing Invariants
    "docstatus",
    "status",
    "per_billed",
    "per_delivered",
    "billed_amt",
    "delivered_qty",
    "billing_status",
    "delivery_status",
    "amended_from",
}

RESERVED_FIELD_SUFFIXES: Set[str] = {
    "name",
    "owner",
    "creation",
    "modified",
    "modified_by",
    "docstatus",
    "idx",
    "parent",
    "parentfield",
    "parenttype",
}

# Phase 1 Explicitly Tested Simple FieldTypes (§5.1)
PHASE_1_ALLOWED_FIELDTYPES: Set[str] = {
    "Data",
    "Check",
    "Int",
    "Float",
    "Date",
    "Datetime",
    "Select",
    "Link",
}

VALID_FIELDNAME_RE = re.compile(r"^custom_[a-z][a-z0-9_]{1,50}$")

PROHIBITED_INTENTS: Set[str] = {
    "delete_doctype",
    "drop_table",
    "drop_column",
    "execute_raw_sql",
    "execute_server_script",
    "override_gl_posting",
    "delete_gl_entries",
    "modify_immutable_record",
}

PRESENTATION_ONLY_PROPERTIES: Set[str] = {
    "label",
    "description",
    "insert_after",
    "in_list_view",
    "in_standard_filter",
    "bold",
    "collapsible",
}

GOVERNED_SEMANTIC_PROPERTIES: Set[str] = {
    "default",
    "read_only",
    "reqd",
    "options",
    "hidden",
}


def validate_mutation_safety(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates a declarative proposal under ADR-001 Rev 2.3 (§5 & §5.1).
    """
    intent = payload.get("intent")
    target_doctype = payload.get("target_doctype")
    changes = payload.get("changes", [])
    user_roles: Set[str] = set(payload.get("user_roles", ["Operator"]))
    existing_fields_lower: Set[str] = {f.lower() for f in payload.get("existing_fieldnames", [])}
    allowed_link_doctypes: Set[str] = set(payload.get("allowed_link_doctypes", []))

    if not intent:
        raise ZoneSafetyViolation("Missing 'intent' in mutation payload.")

    if intent in PROHIBITED_INTENTS:
        raise ZoneSafetyViolation(
            f"Prohibited intent '{intent}' (DESTRUCTIVE_DDL / Arbitrary Code Execution blocked)."
        )

    if target_doctype in ZONE_2_LOCKED_DOCTYPES:
        raise ZoneSafetyViolation(
            f"Zone 2 Compliance Lock Violation (Tier 0 Invariant): DocType '{target_doctype}' is protected."
        )

    if intent == "add_custom_fields" and len(changes) > 1:
        raise ZoneSafetyViolation(
            "Phase 1 Single-Field Unit Rule (§5.1): Only one physical field is permitted per deployment unit."
        )

    highest_storage_impact = "METADATA_ONLY"
    highest_governance_tier = "TIER_2_ORDINARY_CONFIG"

    for change in changes:
        raw_fieldname = change.get("fieldname", "")
        fieldname_lower = raw_fieldname.lower()
        property_name = change.get("property")
        is_new_custom_field = intent == "add_custom_fields"
        is_custom_field = fieldname_lower.startswith("custom_")

        if is_new_custom_field:
            highest_storage_impact = "ONLINE_ADDITIVE_DDL"

            if not VALID_FIELDNAME_RE.match(raw_fieldname):
                raise ZoneSafetyViolation(
                    f"Canonical Fieldname Violation (§5.1): '{raw_fieldname}' must match '^custom_[a-z][a-z0-9_]{{1,50}}$'."
                )

            stripped_name = fieldname_lower[len("custom_"):]
            if fieldname_lower in PROTECTED_STANDARD_FIELDS or stripped_name in RESERVED_FIELD_SUFFIXES:
                raise ZoneSafetyViolation(
                    f"Tier 0 Invariant Violation: Cannot shadow protected or reserved field '{raw_fieldname}'."
                )

            if fieldname_lower in existing_fields_lower:
                raise ZoneSafetyViolation(
                    f"Case-Normalized Collision Violation: Field '{raw_fieldname}' collides with an existing field on '{target_doctype}'."
                )

            fieldtype = change.get("fieldtype", "")
            if fieldtype not in PHASE_1_ALLOWED_FIELDTYPES:
                raise ZoneSafetyViolation(
                    f"Phase 1 FieldType Restriction (§5.1): FieldType '{fieldtype}' is excluded in Phase 1."
                )

            # Block index creation, virtual fields, and allow_on_submit in Phase 1 (§5.1)
            for forbidden_flag in ("unique", "search_index", "in_global_search", "is_virtual", "allow_on_submit"):
                if int(change.get(forbidden_flag, 0)) == 1:
                    raise ZoneSafetyViolation(
                        f"Phase 1 Additive Restriction (§5.1): '{forbidden_flag}=1' is not permitted on '{raw_fieldname}'."
                    )

            # Validate Select choices, duplicates, and default (§5.1)
            if fieldtype == "Select":
                raw_opts = str(change.get("options", "")).strip()
                if not raw_opts:
                    raise ZoneSafetyViolation(f"Invalid Select Options: '{raw_fieldname}' requires non-empty options.")
                choices = [c.strip() for c in raw_opts.split("\n") if c.strip()]
                if len(choices) != len(set(choices)):
                    raise ZoneSafetyViolation(f"Duplicate Select Options: '{raw_fieldname}' contains duplicate choices.")
                default_val = change.get("default")
                if default_val not in (None, "") and default_val not in choices:
                    raise ZoneSafetyViolation(
                        f"Invalid Select Default: Default '{default_val}' is not in choices for '{raw_fieldname}'."
                    )

            # Validate Link target resolution (§5.1)
            if fieldtype == "Link":
                link_target = str(change.get("options", "")).strip()
                if not link_target:
                    raise ZoneSafetyViolation(f"Invalid Link Target: '{raw_fieldname}' requires a target DocType in 'options'.")
                if link_target in ZONE_2_LOCKED_DOCTYPES and link_target in ("GL Entry", "Payment Ledger Entry", "EXRP Audit Log"):
                    raise ZoneSafetyViolation(f"Restricted Link Target: Cannot link directly to ledger/audit table '{link_target}'.")
                if allowed_link_doctypes and link_target not in allowed_link_doctypes:
                    raise ZoneSafetyViolation(f"Unresolved Link Target: DocType '{link_target}' is not in allowed targets.")

            if int(change.get("permlevel", 0)) > 0:
                highest_governance_tier = "TIER_1_GOVERNED_POLICY"

            if change.get("reqd") == 1 and change.get("default") in (None, "") and not change.get("state_scoped_reqd"):
                raise ZoneSafetyViolation(
                    f"Data-Semantic Restriction (§5.1): New field '{raw_fieldname}' must be nullable/optional in Phase 1."
                )

            if change.get("default") not in (None, "") or change.get("state_scoped_reqd"):
                highest_governance_tier = "TIER_1_GOVERNED_POLICY"
            continue

        # Existing field mutation
        if not is_custom_field:
            if fieldname_lower in PROTECTED_STANDARD_FIELDS:
                if property_name not in PRESENTATION_ONLY_PROPERTIES:
                    raise ZoneSafetyViolation(
                        f"Tier 0 Invariant Protection Violation: Cannot modify '{property_name}' on protected "
                        f"ERPNext field '{target_doctype}.{raw_fieldname}'."
                    )
            if property_name == "reqd" and int(change.get("value", 1)) == 0:
                raise ZoneSafetyViolation(
                    f"Tier 0 Constraint Weakening Violation: Cannot relax mandatory requirement on standard field '{target_doctype}.{raw_fieldname}'."
                )
            if property_name == "read_only" and int(change.get("value", 1)) == 0:
                raise ZoneSafetyViolation(
                    f"Tier 0 Constraint Weakening Violation: Cannot unlock read_only constraint on standard field '{target_doctype}.{raw_fieldname}'."
                )
            if property_name in GOVERNED_SEMANTIC_PROPERTIES:
                highest_storage_impact = "DATA_SEMANTIC"
                highest_governance_tier = "TIER_1_GOVERNED_POLICY"
        else:
            if property_name in GOVERNED_SEMANTIC_PROPERTIES:
                highest_storage_impact = "DATA_SEMANTIC"
                highest_governance_tier = "TIER_1_GOVERNED_POLICY"

    if highest_governance_tier == "TIER_1_GOVERNED_POLICY":
        if not user_roles.intersection(TIER_1_GOVERNANCE_ROLES) and "user_roles" in payload:
            raise ZoneSafetyViolation(
                f"Governance Authority Violation: Modifying Tier 1 governed configuration on '{target_doctype}' "
                f"requires one of {sorted(TIER_1_GOVERNANCE_ROLES)}."
            )

    return {
        "status": "approved",
        "zone": "zone_1_customizable",
        "target_doctype": target_doctype,
        "intent": intent,
        "storage_impact": highest_storage_impact,
        "governance_tier": highest_governance_tier,
        "policy_engine_version": "2.3",
    }
