"""
EXRP Schema Extractor
Extracts compact, token-efficient JSON representations of DocTypes
specifically formatted for LLM context windows.
"""

from typing import Dict, Any, List
import json


def get_compact_doctype_schema(doctype_meta: Any) -> Dict[str, Any]:
    """
    Given a Frappe DocType meta object or dictionary, transforms it into
    a lean, structured JSON schema containing only semantic fields.
    """
    fields_summary = []
    
    # Extract fields either from object or dict
    raw_fields = getattr(doctype_meta, "fields", None) or (
        doctype_meta.get("fields") if isinstance(doctype_meta, dict) else []
    )

    name = getattr(doctype_meta, "name", None) or (
        doctype_meta.get("name") if isinstance(doctype_meta, dict) else "Unknown"
    )
    
    module = getattr(doctype_meta, "module", None) or (
        doctype_meta.get("module") if isinstance(doctype_meta, dict) else "Unknown"
    )

    for f in raw_fields:
        # Ignore purely visual layout elements unless needed for insertion anchoring
        fieldtype = getattr(f, "fieldtype", None) or (f.get("fieldtype") if isinstance(f, dict) else "")
        fieldname = getattr(f, "fieldname", None) or (f.get("fieldname") if isinstance(f, dict) else "")
        label = getattr(f, "label", None) or (f.get("label") if isinstance(f, dict) else "")

        if not fieldname:
            continue

        item = {
            "name": fieldname,
            "label": label or fieldname,
            "type": fieldtype,
        }

        # Include critical semantic attributes
        options = getattr(f, "options", None) or (f.get("options") if isinstance(f, dict) else None)
        if options and fieldtype in ("Select", "Link", "Table"):
            item["options"] = options

        reqd = getattr(f, "reqd", None) or (f.get("reqd") if isinstance(f, dict) else 0)
        if reqd:
            item["required"] = True

        read_only = getattr(f, "read_only", None) or (f.get("read_only") if isinstance(f, dict) else 0)
        if read_only:
            item["read_only"] = True

        fields_summary.append(item)

    return {
        "doctype": name,
        "module": module,
        "field_count": len(fields_summary),
        "fields": fields_summary
    }
