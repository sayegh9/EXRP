"""
Idempotent seed utility to ensure core ERP business DocTypes
(Customer, Item, Sales Order, Delivery Note, Quotation) and sample
records exist in the active Frappe site for live EXRP Copilot demos.
"""

from typing import List, Dict, Any


def ensure_demo_erp_doctypes() -> Dict[str, Any]:
    import frappe

    created_doctypes: List[str] = []
    seeded_records: List[str] = []

    default_perms = [
        {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1},
        {"role": "Sales Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1},
        {"role": "Sales User", "read": 1, "write": 1, "create": 1},
        {"role": "Finance Director", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1},
        {"role": "Operations Director", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1},
    ]

    master_perms = [
        {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "Sales Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "Sales User", "read": 1, "write": 1, "create": 1},
        {"role": "Finance Director", "read": 1, "write": 1, "create": 1},
        {"role": "Operations Director", "read": 1, "write": 1, "create": 1},
    ]

    doctype_specs = [
        {
            "name": "Customer",
            "is_submittable": 0,
            "autoname": "field:customer_name",
            "title_field": "customer_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "customer_name", "label": "Customer Name", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
                {"fieldname": "customer_group", "label": "Customer Group", "fieldtype": "Select", "options": "Commercial\nEnterprise\nGovernment\nIndividual", "default": "Enterprise", "in_list_view": 1},
                {"fieldname": "territory", "label": "Territory", "fieldtype": "Data", "default": "Global", "in_list_view": 1},
                {"fieldname": "credit_limit", "label": "Credit Limit", "fieldtype": "Currency", "default": "100000"},
                {"fieldname": "disabled", "label": "Disabled", "fieldtype": "Check", "default": "0"},
            ],
        },
        {
            "name": "Item",
            "is_submittable": 0,
            "autoname": "field:item_code",
            "title_field": "item_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "item_code", "label": "Item Code", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
                {"fieldname": "item_name", "label": "Item Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "item_group", "label": "Item Group", "fieldtype": "Select", "options": "Products\nRaw Material\nServices\nSub Assemblies", "default": "Products", "in_list_view": 1},
                {"fieldname": "standard_rate", "label": "Standard Selling Rate", "fieldtype": "Currency", "default": "1000", "in_list_view": 1},
                {"fieldname": "valuation_rate", "label": "Valuation Rate", "fieldtype": "Currency", "default": "700"},
                {"fieldname": "disabled", "label": "Disabled", "fieldtype": "Check", "default": "0"},
            ],
        },
        {
            "name": "Sales Order",
            "is_submittable": 1,
            "autoname": "format:SO-2026-{####}",
            "title_field": "customer",
            "permissions": default_perms,
            "fields": [
                {"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "transaction_date", "label": "Order Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "delivery_date", "label": "Delivery Date", "fieldtype": "Date", "default": "Today", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nPending\nTo Deliver and Bill\nCompleted\nCancelled", "default": "Pending", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "company", "label": "Company", "fieldtype": "Data", "default": "EXRP Global Enterprises"},
                {"fieldname": "currency", "label": "Currency", "fieldtype": "Data", "default": "USD"},
                {"fieldname": "grand_total", "label": "Grand Total", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "bypass_credit_limit_check", "label": "Bypass Credit Limit Check", "fieldtype": "Check", "default": "0"},
            ],
        },
        {
            "name": "Delivery Note",
            "is_submittable": 1,
            "autoname": "format:DN-2026-{####}",
            "title_field": "customer",
            "permissions": default_perms,
            "fields": [
                {"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "sales_order", "label": "Linked Sales Order", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nTo Bill\nCompleted\nCancelled", "default": "Draft", "in_list_view": 1},
                {"fieldname": "grand_total", "label": "Total Value", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
        {
            "name": "Quotation",
            "is_submittable": 1,
            "autoname": "format:QTN-2026-{####}",
            "title_field": "party_name",
            "permissions": default_perms,
            "fields": [
                {"fieldname": "party_name", "label": "Customer / Lead Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "transaction_date", "label": "Quotation Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "valid_till", "label": "Valid Till", "fieldtype": "Date"},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nOpen\nOrdered\nLost\nCancelled", "default": "Open", "in_list_view": 1},
                {"fieldname": "grand_total", "label": "Grand Total", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
    ]

    for spec in doctype_specs:
        dt_name = spec["name"]
        if not frappe.db.exists("DocType", dt_name):
            doc = frappe.get_doc({
                "doctype": "DocType",
                "name": dt_name,
                "module": "EXRP",
                "custom": 1,
                "is_submittable": spec["is_submittable"],
                "autoname": spec["autoname"],
                "title_field": spec["title_field"],
                "fields": spec["fields"],
                "permissions": spec["permissions"],
            })
            doc.insert(ignore_permissions=True)
            created_doctypes.append(dt_name)

    frappe.db.commit()

    # Seed sample Customer records
    sample_customers = [
        {"customer_name": "Acme Logistics Corp", "customer_group": "Enterprise", "territory": "North America", "credit_limit": 250000},
        {"customer_name": "Global Freight Partners", "customer_group": "Enterprise", "territory": "Europe", "credit_limit": 500000},
        {"customer_name": "Pacific Rim Supply Co", "customer_group": "Commercial", "territory": "APAC", "credit_limit": 150000},
    ]
    for cust in sample_customers:
        if not frappe.db.exists("Customer", cust["customer_name"]):
            d = frappe.get_doc({"doctype": "Customer", **cust})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Customer:{d.name}")

    # Seed sample Sales Order records
    if frappe.db.count("Sales Order") == 0:
        sample_orders = [
            {"customer": "Acme Logistics Corp", "transaction_date": "2026-11-01", "delivery_date": "2026-11-15", "status": "Pending", "grand_total": 48500},
            {"customer": "Global Freight Partners", "transaction_date": "2026-11-02", "delivery_date": "2026-11-18", "status": "Pending", "grand_total": 125000},
            {"customer": "Pacific Rim Supply Co", "transaction_date": "2026-11-03", "delivery_date": "2026-11-20", "status": "To Deliver and Bill", "grand_total": 19200},
            {"customer": "Acme Logistics Corp", "transaction_date": "2026-11-04", "delivery_date": "2026-11-25", "status": "Pending", "grand_total": 82400},
            {"customer": "Global Freight Partners", "transaction_date": "2026-11-05", "delivery_date": "2026-11-30", "status": "Completed", "grand_total": 34000},
        ]
        for idx, so in enumerate(sample_orders):
            d = frappe.get_doc({"doctype": "Sales Order", **so})
            d.insert(ignore_permissions=True)
            if idx < 2:
                d.submit()
            seeded_records.append(f"Sales Order:{d.name}")

    # Seed sample Delivery Note records
    if frappe.db.count("Delivery Note") == 0:
        so_names = [r.name for r in frappe.get_all("Sales Order", filters={"docstatus": 1}, limit=2)]
        if not so_names:
            for r in frappe.get_all("Sales Order", filters={"docstatus": 0}, limit=2):
                so_doc = frappe.get_doc("Sales Order", r.name)
                so_doc.submit()
                so_names.append(so_doc.name)
        so1 = so_names[0] if len(so_names) > 0 else None
        so2 = so_names[1] if len(so_names) > 1 else so1
        sample_dns = [
            {"customer": "Acme Logistics Corp", "posting_date": "2026-11-04", "sales_order": so1, "status": "To Bill", "grand_total": 48500},
            {"customer": "Global Freight Partners", "posting_date": "2026-11-05", "sales_order": so2, "status": "Draft", "grand_total": 125000},
        ]
        for dn in sample_dns:
            d = frappe.get_doc({"doctype": "Delivery Note", **dn})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Delivery Note:{d.name}")

    # Seed sample Quotation records
    if frappe.db.count("Quotation") == 0:
        sample_qtns = [
            {"party_name": "Acme Logistics Corp", "transaction_date": "2026-11-01", "valid_till": "2026-12-01", "status": "Open", "grand_total": 64000},
            {"party_name": "Pacific Rim Supply Co", "transaction_date": "2026-11-03", "valid_till": "2026-12-03", "status": "Open", "grand_total": 29500},
        ]
        for qtn in sample_qtns:
            d = frappe.get_doc({"doctype": "Quotation", **qtn})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Quotation:{d.name}")

    frappe.db.commit()
    return {
        "created_doctypes": created_doctypes,
        "seeded_records": seeded_records,
    }
