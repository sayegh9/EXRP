"""
EXRP Cross-Document Policy Catalog (ADR-006 Companion Requirement)
Validates referential and business state constraints across related Frappe documents:
- LINKED_DOC_MUST_BE_SUBMITTED: E.g., Delivery Note requires linked Sales Order to be submitted (docstatus == 1).
- LINKED_DOC_CANNOT_BE_CANCELLED: E.g., Sales Invoice cannot link to cancelled Sales Order (docstatus != 2).
- AMOUNT_CANNOT_EXCEED_LINKED: E.g., Payment Entry / Delivery Note cannot exceed linked Sales Order grand total.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Union

from .policy_enforcer import PolicyEvaluationResult


@dataclass
class CrossDocPolicy:
    """
    Cross-document lifecycle integrity policy.
    """
    policy_id: str
    source_doctype: str
    linked_doctype: str
    link_field: str
    rule_type: str  # 'LINKED_DOC_MUST_BE_SUBMITTED', 'LINKED_DOC_CANNOT_BE_CANCELLED', 'AMOUNT_CANNOT_EXCEED_LINKED'
    error_message: str
    active: bool = True
    stage: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


class CrossDocPolicyCatalog:
    """
    Catalog and evaluator for Cross-Document Referential Integrity Policies.
    """
    def __init__(self):
        self._policies: Dict[str, List[CrossDocPolicy]] = {}
        self._mock_docs: Dict[tuple, Dict[str, Any]] = {}
        self._bootstrap_default_policies()

    def _bootstrap_default_policies(self) -> None:
        # Default policy 1: Delivery Note requires linked Sales Order submitted (docstatus == 1)
        self.register_policy(
            CrossDocPolicy(
                policy_id="XDOC_DN_SO_MUST_BE_SUBMITTED",
                source_doctype="Delivery Note",
                linked_doctype="Sales Order",
                link_field="against_sales_order",
                rule_type="LINKED_DOC_MUST_BE_SUBMITTED",
                error_message="Delivery Note requires linked Sales Order to be submitted (docstatus == 1). Linked Sales Order must be submitted.",
                active=True,
            )
        )
        # Default policy 2: Sales Invoice linked Sales Order cannot be cancelled (docstatus != 2)
        self.register_policy(
            CrossDocPolicy(
                policy_id="XDOC_SI_SO_CANNOT_BE_CANCELLED",
                source_doctype="Sales Invoice",
                linked_doctype="Sales Order",
                link_field="sales_order",
                rule_type="LINKED_DOC_CANNOT_BE_CANCELLED",
                error_message="Sales Invoice cannot be linked to a cancelled Sales Order (docstatus != 2).",
                active=True,
            )
        )

    def register_policy(self, policy: CrossDocPolicy) -> None:
        """Registers or replaces a policy in the catalog."""
        pol_list = self._policies.setdefault(policy.source_doctype, [])
        for idx, p in enumerate(pol_list):
            if p.policy_id == policy.policy_id:
                pol_list[idx] = policy
                return
        pol_list.append(policy)

    def unregister_policy(self, policy_id: str, source_doctype: Optional[str] = None) -> bool:
        """Removes a policy by ID."""
        removed = False
        doctypes = [source_doctype] if source_doctype else list(self._policies.keys())
        for dt in doctypes:
            if dt in self._policies:
                initial_len = len(self._policies[dt])
                self._policies[dt] = [p for p in self._policies[dt] if p.policy_id != policy_id]
                if len(self._policies[dt]) < initial_len:
                    removed = True
        return removed

    def set_mock_document(self, doctype: str, name: str, data: Dict[str, Any]) -> None:
        """Sets a mock document for offline/test environments."""
        self._mock_docs[(doctype, name)] = data

    def clear_mock_documents(self) -> None:
        """Clears all mock documents."""
        self._mock_docs.clear()

    def get_linked_document(self, doctype: str, name: str, db: Any = None) -> Optional[Dict[str, Any]]:
        """Resolves a linked document from db adapter, mock store, or Frappe runtime."""
        # 1. db adapter
        if db is not None:
            if hasattr(db, "get_document") and callable(getattr(db, "get_document", None)):
                d = db.get_document(doctype, name)
                if d is not None:
                    return d
            if hasattr(db, "get_doc") and callable(getattr(db, "get_doc", None)):
                try:
                    d = db.get_doc(doctype, name)
                    if d is not None:
                        return d.as_dict() if hasattr(d, "as_dict") else dict(d)
                except Exception:
                    pass
            if hasattr(db, "documents") and isinstance(db.documents, dict):
                d = db.documents.get((doctype, name))
                if d is not None:
                    return d
            if isinstance(db, dict):
                d = db.get((doctype, name)) or db.get(name)
                if d is not None:
                    return d

        # 2. catalog mock store
        if (doctype, name) in self._mock_docs:
            return self._mock_docs[(doctype, name)]

        # 3. frappe runtime
        try:
            import frappe
            if hasattr(frappe, "db") and hasattr(frappe.db, "exists") and frappe.db.exists(doctype, name):
                if hasattr(frappe, "get_doc"):
                    doc = frappe.get_doc(doctype, name)
                    return doc.as_dict() if hasattr(doc, "as_dict") else dict(doc)
                if hasattr(frappe.db, "get_value"):
                    return frappe.db.get_value(doctype, name, ["name", "docstatus", "grand_total"], as_dict=True)
        except Exception:
            pass

        return None

    def _extract_linked_names(self, doc: Any, policy: CrossDocPolicy) -> List[str]:
        names: List[str] = []
        candidates = [policy.link_field]
        if policy.link_field in ("against_sales_order", "sales_order"):
            candidates.extend(["against_sales_order", "sales_order", "sales_order_id"])

        for fld in candidates:
            val = getattr(doc, fld, None) if hasattr(doc, fld) else (doc.get(fld) if isinstance(doc, dict) else None)
            if val and isinstance(val, str) and val.strip():
                names.append(val.strip())

        items = getattr(doc, "items", None) if hasattr(doc, "items") else (doc.get("items") if isinstance(doc, dict) else None)
        if isinstance(items, list):
            for item in items:
                for fld in candidates:
                    val = getattr(item, fld, None) if hasattr(item, fld) else (item.get(fld) if isinstance(item, dict) else None)
                    if val and isinstance(val, str) and val.strip():
                        names.append(val.strip())

        seen = set()
        res = []
        for n in names:
            if n not in seen:
                seen.add(n)
                res.append(n)
        return res

    def evaluate_cross_doc_policies(
        self,
        doc: Any,
        stage: str = "validate",
        db: Any = None,
    ) -> PolicyEvaluationResult:
        """
        Evaluates active cross-document policies against the provided document.
        """
        doctype = getattr(doc, "doctype", None) if hasattr(doc, "doctype") else (doc.get("doctype") if isinstance(doc, dict) else None)
        if not doctype or doctype not in self._policies:
            return PolicyEvaluationResult(allowed=True, violated_policies=[], reasons=[])

        violated_policies: List[str] = []
        reasons: List[str] = []

        norm_stage = (stage or "validate").lower()

        for policy in self._policies.get(doctype, []):
            if not policy.active:
                continue
            if policy.stage and policy.stage.lower() != norm_stage:
                continue

            linked_names = self._extract_linked_names(doc, policy)
            if not linked_names:
                continue

            for l_name in linked_names:
                linked_doc = self.get_linked_document(policy.linked_doctype, l_name, db=db)
                if linked_doc is None:
                    violated_policies.append(policy.policy_id)
                    msg = policy.error_message or f"Linked {policy.linked_doctype} '{l_name}' not found."
                    reasons.append(msg)
                    continue

                docstatus = linked_doc.get("docstatus", 0) if isinstance(linked_doc, dict) else getattr(linked_doc, "docstatus", 0)

                if policy.rule_type == "LINKED_DOC_MUST_BE_SUBMITTED":
                    if docstatus != 1:
                        violated_policies.append(policy.policy_id)
                        reasons.append(
                            policy.error_message or f"Linked {policy.linked_doctype} '{l_name}' must be submitted (docstatus == 1). Current docstatus: {docstatus}."
                        )

                elif policy.rule_type == "LINKED_DOC_CANNOT_BE_CANCELLED":
                    if docstatus == 2:
                        violated_policies.append(policy.policy_id)
                        reasons.append(
                            policy.error_message or f"Linked {policy.linked_doctype} '{l_name}' cannot be cancelled (docstatus == 2)."
                        )

                elif policy.rule_type == "AMOUNT_CANNOT_EXCEED_LINKED":
                    doc_amt = getattr(doc, "grand_total", getattr(doc, "total", 0.0)) if hasattr(doc, "grand_total") or hasattr(doc, "total") else (doc.get("grand_total") or doc.get("total") or 0.0)
                    linked_amt = getattr(linked_doc, "grand_total", getattr(linked_doc, "total", 0.0)) if hasattr(linked_doc, "grand_total") or hasattr(linked_doc, "total") else (linked_doc.get("grand_total") or linked_doc.get("total") or 0.0)
                    if float(doc_amt or 0) > float(linked_amt or 0):
                        violated_policies.append(policy.policy_id)
                        reasons.append(
                            policy.error_message or f"Amount ({doc_amt}) cannot exceed linked {policy.linked_doctype} amount ({linked_amt})."
                        )

        allowed = (len(violated_policies) == 0)
        return PolicyEvaluationResult(allowed=allowed, violated_policies=violated_policies, reasons=reasons)


# Global singleton catalog instance
cross_doc_catalog = CrossDocPolicyCatalog()


def evaluate_cross_doc_policies(
    doc: Any,
    stage: str = "validate",
    db: Any = None,
) -> PolicyEvaluationResult:
    """Convenience module-level evaluation function."""
    return cross_doc_catalog.evaluate_cross_doc_policies(doc, stage=stage, db=db)
