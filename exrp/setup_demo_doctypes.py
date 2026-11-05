"""
Idempotent full-ERP seed utility to provision 20 core ERP business DocTypes,
governance roles, and 140+ interconnected sample records across CRM, Selling,
Buying/Procurement, Inventory/Warehouse, Finance/Accounting, HR, Projects,
and Tier 0 Protected Ledgers in the active Frappe site for live EXRP Copilot testing.
"""

from typing import List, Dict, Any


def ensure_demo_erp_doctypes() -> Dict[str, Any]:
    import frappe

    created_roles: List[str] = []
    created_doctypes: List[str] = []
    seeded_records: List[str] = []

    # 1. Ensure Governance & Operational Roles exist
    erp_roles = [
        "Finance Director",
        "Operations Director",
        "Credit Controller",
        "Sales Manager",
        "Sales User",
        "Purchase Manager",
        "HR Manager",
        "Projects Manager",
        "Stock Manager",
    ]
    for role_name in erp_roles:
        if not frappe.db.exists("Role", role_name):
            r_doc = frappe.get_doc({
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": 1,
            })
            r_doc.insert(ignore_permissions=True)
            created_roles.append(role_name)

    # Ensure Administrator has the governance roles for testing Tier 1 approvals
    if frappe.db.exists("User", "Administrator"):
        admin_doc = frappe.get_doc("User", "Administrator")
        existing_admin_roles = {r.role for r in (admin_doc.roles or [])}
        added_role = False
        for r_name in erp_roles:
            if r_name not in existing_admin_roles:
                admin_doc.append("roles", {"role": r_name})
                added_role = True
        if added_role:
            admin_doc.save(ignore_permissions=True)

    submittable_perms = [
        {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1},
        {"role": "Sales Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1},
        {"role": "Purchase Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1},
        {"role": "Sales User", "read": 1, "write": 1, "create": 1},
        {"role": "Finance Director", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1},
        {"role": "Operations Director", "read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1},
    ]

    master_perms = [
        {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "Sales Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "Purchase Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "HR Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        {"role": "Sales User", "read": 1, "write": 1, "create": 1},
        {"role": "Finance Director", "read": 1, "write": 1, "create": 1},
        {"role": "Operations Director", "read": 1, "write": 1, "create": 1},
    ]

    # 2. Define 20 Full-ERP DocTypes (Child tables first so parent Table fields resolve)
    doctype_specs = [
        # --- Child Table: Sales Order Item (Tier 0 Protected rate field) ---
        {
            "name": "Sales Order Item",
            "istable": 1,
            "is_submittable": 0,
            "autoname": "hash",
            "permissions": [],
            "fields": [
                {"fieldname": "item_code", "label": "Item Code", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "item_name", "label": "Item Name", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "qty", "label": "Quantity", "fieldtype": "Float", "default": "1", "reqd": 1, "in_list_view": 1},
                {"fieldname": "rate", "label": "Unit Rate (Tier 0 Protected)", "fieldtype": "Currency", "default": "0", "reqd": 1, "in_list_view": 1},
                {"fieldname": "amount", "label": "Line Amount", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
        # --- CRM & Selling ---
        {
            "name": "Lead",
            "is_submittable": 0,
            "autoname": "format:CRM-LEAD-2026-{####}",
            "title_field": "company_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "lead_name", "label": "Contact Person", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "company_name", "label": "Organization Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Lead\nOpen\nContacted\nInterested\nOpportunity\nConverted\nDo Not Contact", "default": "Open", "in_list_view": 1},
                {"fieldname": "source", "label": "Lead Source", "fieldtype": "Select", "options": "Website\nTrade Show\nPartner Referral\nOutbound Campaign\nRFP Tender", "default": "Website", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "territory", "label": "Territory", "fieldtype": "Data", "default": "North America", "in_list_view": 1},
                {"fieldname": "annual_revenue", "label": "Estimated Annual Revenue", "fieldtype": "Currency", "default": "0"},
                {"fieldname": "email_id", "label": "Email Address", "fieldtype": "Data"},
            ],
        },
        {
            "name": "Opportunity",
            "is_submittable": 0,
            "autoname": "format:CRM-OPP-2026-{####}",
            "title_field": "party_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "party_name", "label": "Account / Prospect Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "opportunity_type", "label": "Opportunity Type", "fieldtype": "Select", "options": "Sales\nSupport Contract\nEnterprise Renewal\nExpansion", "default": "Sales", "in_list_view": 1},
                {"fieldname": "sales_stage", "label": "Sales Stage", "fieldtype": "Select", "options": "Qualification\nNeeds Analysis\nValue Proposition\nProposal/Price Quote\nNegotiation/Review\nClosed Won\nClosed Lost", "default": "Qualification", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Open\nQuotation\nConverted\nLost\nClosed", "default": "Open", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "opportunity_amount", "label": "Deal Value", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "probability", "label": "Win Probability (%)", "fieldtype": "Int", "default": "50"},
                {"fieldname": "expected_closing", "label": "Expected Close Date", "fieldtype": "Date", "default": "Today"},
            ],
        },
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
            "name": "Quotation",
            "is_submittable": 1,
            "autoname": "format:QTN-2026-{####}",
            "title_field": "party_name",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "party_name", "label": "Customer / Lead Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "transaction_date", "label": "Quotation Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "valid_till", "label": "Valid Till", "fieldtype": "Date"},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nOpen\nOrdered\nLost\nCancelled", "default": "Open", "in_list_view": 1},
                {"fieldname": "grand_total", "label": "Grand Total", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
        {
            "name": "Sales Order",
            "is_submittable": 1,
            "autoname": "format:SO-2026-{####}",
            "title_field": "customer",
            "permissions": submittable_perms,
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
                {"fieldname": "section_break_items", "label": "Order Line Items", "fieldtype": "Section Break"},
                {"fieldname": "items", "label": "Items", "fieldtype": "Table", "options": "Sales Order Item"},
            ],
        },
        {
            "name": "Delivery Note",
            "is_submittable": 1,
            "autoname": "format:DN-2026-{####}",
            "title_field": "customer",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "sales_order", "label": "Linked Sales Order", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "warehouse", "label": "Source Warehouse", "fieldtype": "Data", "default": "Rotterdam Hub"},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nTo Bill\nCompleted\nCancelled", "default": "Draft", "in_list_view": 1},
                {"fieldname": "grand_total", "label": "Total Value", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
        # --- Buying & Procurement ---
        {
            "name": "Supplier",
            "is_submittable": 0,
            "autoname": "field:supplier_name",
            "title_field": "supplier_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "supplier_name", "label": "Supplier Name", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
                {"fieldname": "supplier_group", "label": "Supplier Group", "fieldtype": "Select", "options": "Hardware\nRaw Material\nLogistics\nCloud Services\nDistributor", "default": "Hardware", "in_list_view": 1},
                {"fieldname": "country", "label": "Country", "fieldtype": "Data", "default": "Germany", "in_list_view": 1},
                {"fieldname": "on_hold", "label": "Payment On Hold", "fieldtype": "Check", "default": "0"},
                {"fieldname": "disabled", "label": "Disabled", "fieldtype": "Check", "default": "0"},
            ],
        },
        {
            "name": "Material Request",
            "is_submittable": 1,
            "autoname": "format:MAT-REQ-2026-{####}",
            "title_field": "title",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "title", "label": "Requisition Title", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "material_request_type", "label": "Request Type", "fieldtype": "Select", "options": "Purchase\nMaterial Transfer\nMaterial Issue\nManufacture", "default": "Purchase", "in_list_view": 1},
                {"fieldname": "transaction_date", "label": "Request Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "schedule_date", "label": "Required By Date", "fieldtype": "Date", "default": "Today"},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "department", "label": "Requesting Department", "fieldtype": "Data", "default": "Operations", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nPending\nPartially Ordered\nOrdered\nTransferred\nCancelled", "default": "Pending", "in_list_view": 1},
                {"fieldname": "estimated_cost", "label": "Estimated Cost", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
        {
            "name": "Purchase Order",
            "is_submittable": 1,
            "autoname": "format:PO-2026-{####}",
            "title_field": "supplier",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "supplier", "label": "Supplier", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "transaction_date", "label": "Order Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "schedule_date", "label": "Expected Delivery Date", "fieldtype": "Date", "default": "Today", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nPending\nTo Receive and Bill\nCompleted\nOn Hold\nCancelled", "default": "Pending", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "company", "label": "Company", "fieldtype": "Data", "default": "EXRP Global Enterprises"},
                {"fieldname": "currency", "label": "Currency", "fieldtype": "Data", "default": "USD"},
                {"fieldname": "grand_total", "label": "Grand Total", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "is_subcontracted", "label": "Is Subcontracted", "fieldtype": "Check", "default": "0"},
            ],
        },
        {
            "name": "Purchase Receipt",
            "is_submittable": 1,
            "autoname": "format:PREC-2026-{####}",
            "title_field": "supplier",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "supplier", "label": "Supplier", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Receipt Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "purchase_order", "label": "Linked Purchase Order", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "warehouse", "label": "Accepted Warehouse", "fieldtype": "Data", "default": "Rotterdam Hub", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nTo Bill\nCompleted\nReturn Issued\nCancelled", "default": "To Bill", "in_list_view": 1},
                {"fieldname": "grand_total", "label": "Total Received Value", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
            ],
        },
        # --- Inventory & Warehouse ---
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
            "name": "Warehouse",
            "is_submittable": 0,
            "autoname": "field:warehouse_name",
            "title_field": "warehouse_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "warehouse_name", "label": "Warehouse Name", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
                {"fieldname": "warehouse_type", "label": "Warehouse Type", "fieldtype": "Select", "options": "Distribution Hub\nCold Storage\nBonded FreeZone\nRaw Material\nTransit", "default": "Distribution Hub", "in_list_view": 1},
                {"fieldname": "city", "label": "City / Port", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "capacity_cbm", "label": "Max Capacity (CBM)", "fieldtype": "Int", "default": "25000", "in_list_view": 1},
                {"fieldname": "disabled", "label": "Disabled", "fieldtype": "Check", "default": "0"},
            ],
        },
        {
            "name": "Stock Ledger Entry",
            "is_submittable": 0,
            "autoname": "format:SLE-2026-{#####}",
            "title_field": "item_code",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "item_code", "label": "Item Code", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "warehouse", "label": "Warehouse", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "actual_qty", "label": "Qty Change", "fieldtype": "Float", "default": "0", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "valuation_rate", "label": "Valuation Rate", "fieldtype": "Currency", "default": "0"},
                {"fieldname": "stock_value_difference", "label": "Value Difference", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "voucher_type", "label": "Voucher Type", "fieldtype": "Data", "default": "Delivery Note"},
                {"fieldname": "voucher_no", "label": "Voucher No", "fieldtype": "Data"},
            ],
        },
        # --- Finance & Accounting (Tier 0 Protected Ledgers & Cross-Doc Invoices) ---
        {
            "name": "Sales Invoice",
            "is_submittable": 1,
            "autoname": "format:SINV-2026-{####}",
            "title_field": "customer",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "due_date", "label": "Payment Due Date", "fieldtype": "Date", "default": "Today", "in_list_view": 1},
                {"fieldname": "sales_order", "label": "Linked Sales Order", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nUnpaid\nOverdue\nPaid\nPartly Paid\nCancelled", "default": "Unpaid", "in_list_view": 1},
                {"fieldname": "currency", "label": "Currency", "fieldtype": "Data", "default": "USD"},
                {"fieldname": "grand_total", "label": "Invoice Total", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "outstanding_amount", "label": "Outstanding Balance", "fieldtype": "Currency", "default": "0"},
            ],
        },
        {
            "name": "Payment Entry",
            "is_submittable": 1,
            "autoname": "format:PAY-2026-{####}",
            "title_field": "party",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "payment_type", "label": "Payment Type", "fieldtype": "Select", "options": "Receive\nPay\nInternal Transfer", "default": "Receive", "reqd": 1, "in_list_view": 1},
                {"fieldname": "party_type", "label": "Party Type", "fieldtype": "Select", "options": "Customer\nSupplier\nEmployee", "default": "Customer", "in_list_view": 1},
                {"fieldname": "party", "label": "Party Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Payment Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "mode_of_payment", "label": "Mode of Payment", "fieldtype": "Select", "options": "Wire Transfer\nACH\nCorporate Card\nLetter of Credit", "default": "Wire Transfer", "in_list_view": 1},
                {"fieldname": "paid_amount", "label": "Paid Amount", "fieldtype": "Currency", "default": "0", "reqd": 1, "in_list_view": 1},
                {"fieldname": "reference_no", "label": "Bank Reference / SWIFT", "fieldtype": "Data"},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nSubmitted\nReconciled\nCancelled", "default": "Submitted", "in_list_view": 1},
            ],
        },
        {
            "name": "GL Entry",
            "is_submittable": 0,
            "autoname": "format:GLE-2026-{#####}",
            "title_field": "account",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "posting_date", "label": "Posting Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "account", "label": "GL Account", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "party_type", "label": "Party Type", "fieldtype": "Data"},
                {"fieldname": "party", "label": "Party", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "debit", "label": "Debit (USD)", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "credit", "label": "Credit (USD)", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
                {"fieldname": "voucher_type", "label": "Voucher Type", "fieldtype": "Data"},
                {"fieldname": "voucher_no", "label": "Voucher No", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "remarks", "label": "Audit Remarks", "fieldtype": "Data"},
            ],
        },
        # --- HR & Projects ---
        {
            "name": "Employee",
            "is_submittable": 0,
            "autoname": "format:EMP-{####}",
            "title_field": "employee_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "employee_name", "label": "Full Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "department", "label": "Department", "fieldtype": "Select", "options": "Operations\nSales\nFinance\nEngineering\nSupply Chain\nExecutive", "default": "Operations", "in_list_view": 1},
                {"fieldname": "designation", "label": "Job Title", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "status", "label": "Employment Status", "fieldtype": "Select", "options": "Active\nOn Leave\nProbation\nLeft", "default": "Active", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "branch", "label": "Office Location", "fieldtype": "Data", "default": "Amsterdam HQ", "in_list_view": 1},
                {"fieldname": "date_of_joining", "label": "Date of Joining", "fieldtype": "Date", "default": "2024-01-15"},
                {"fieldname": "ctc", "label": "Annual Compensation (USD)", "fieldtype": "Currency", "default": "110000"},
            ],
        },
        {
            "name": "Expense Claim",
            "is_submittable": 1,
            "autoname": "format:EXP-2026-{####}",
            "title_field": "employee_name",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "employee_name", "label": "Employee Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "department", "label": "Department", "fieldtype": "Data", "default": "Sales", "in_list_view": 1},
                {"fieldname": "posting_date", "label": "Claim Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "expense_type", "label": "Expense Category", "fieldtype": "Select", "options": "Airfare & Travel\nClient Hospitality\nCloud & Software\nField Equipment\nConference", "default": "Airfare & Travel", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "total_claimed_amount", "label": "Claimed Amount", "fieldtype": "Currency", "default": "0", "reqd": 1, "in_list_view": 1},
                {"fieldname": "approval_status", "label": "Approval Status", "fieldtype": "Select", "options": "Draft\nPending Approval\nApproved\nRejected", "default": "Pending Approval", "in_list_view": 1},
                {"fieldname": "status", "label": "Payment Status", "fieldtype": "Select", "options": "Draft\nSubmitted\nPaid\nRejected\nCancelled", "default": "Draft"},
            ],
        },
        {
            "name": "Project",
            "is_submittable": 0,
            "autoname": "format:PROJ-2026-{###}",
            "title_field": "project_name",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "project_name", "label": "Project Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "customer", "label": "Client / Sponsor", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "project_type", "label": "Project Type", "fieldtype": "Select", "options": "External Client\nSupply Chain Rollout\nInternal Infrastructure\nR&D", "default": "External Client", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Open\nCompleted\nOn Hold\nOverdue\nCancelled", "default": "Open", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "priority", "label": "Priority", "fieldtype": "Select", "options": "Low\nMedium\nHigh\nCritical", "default": "High", "in_list_view": 1},
                {"fieldname": "estimated_costing", "label": "Project Budget (USD)", "fieldtype": "Currency", "default": "50000", "in_list_view": 1},
                {"fieldname": "percent_complete", "label": "Completion (%)", "fieldtype": "Int", "default": "25"},
            ],
        },
        # --- Manufacturing & Production ---
        {
            "name": "BOM",
            "is_submittable": 1,
            "autoname": "format:BOM-{####}",
            "title_field": "item",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "item", "label": "Finished Item", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "quantity", "label": "Output Quantity", "fieldtype": "Float", "default": "1", "reqd": 1, "in_list_view": 1},
                {"fieldname": "is_active", "label": "Is Active", "fieldtype": "Check", "default": "1", "in_list_view": 1},
                {"fieldname": "is_default", "label": "Is Default BOM", "fieldtype": "Check", "default": "1"},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "total_cost", "label": "Estimated Unit Cost", "fieldtype": "Currency", "default": "1500", "in_list_view": 1},
                {"fieldname": "currency", "label": "Currency", "fieldtype": "Data", "default": "USD"},
            ],
        },
        {
            "name": "Work Order",
            "is_submittable": 1,
            "autoname": "format:MFG-WO-2026-{####}",
            "title_field": "production_item",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "production_item", "label": "Item to Produce", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "qty", "label": "Qty to Produce", "fieldtype": "Float", "default": "10", "reqd": 1, "in_list_view": 1},
                {"fieldname": "bom_no", "label": "BOM Reference", "fieldtype": "Data", "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nNot Started\nIn Process\nCompleted\nStopped\nCancelled", "default": "In Process", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "planned_start_date", "label": "Planned Start Date", "fieldtype": "Date", "default": "Today", "in_list_view": 1},
                {"fieldname": "target_warehouse", "label": "Destination Warehouse", "fieldtype": "Data", "default": "Rotterdam Hub"},
                {"fieldname": "produced_qty", "label": "Produced Qty", "fieldtype": "Float", "default": "0"},
            ],
        },
        # --- Support & Customer Success ---
        {
            "name": "Issue",
            "is_submittable": 0,
            "autoname": "format:ISS-2026-{####}",
            "title_field": "subject",
            "permissions": master_perms,
            "fields": [
                {"fieldname": "subject", "label": "Issue Subject", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Open\nReplied\nOn Hold\nResolved\nClosed", "default": "Open", "in_list_view": 1},
                {"fieldname": "priority", "label": "Priority", "fieldtype": "Select", "options": "Low\nMedium\nHigh\nUrgent", "default": "Medium", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "issue_type", "label": "Issue Category", "fieldtype": "Select", "options": "Hardware Fault\nFirmware Telemetry\nLate Shipment\nBilling Dispute\nSLA Breach", "default": "Hardware Fault", "in_list_view": 1},
                {"fieldname": "opening_date", "label": "Reported Date", "fieldtype": "Date", "default": "Today"},
                {"fieldname": "resolution_time", "label": "Target SLA (Hours)", "fieldtype": "Int", "default": "24"},
            ],
        },
        {
            "name": "Warranty Claim",
            "is_submittable": 1,
            "autoname": "format:WC-2026-{####}",
            "title_field": "customer",
            "permissions": submittable_perms,
            "fields": [
                {"fieldname": "customer", "label": "Customer", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "item_code", "label": "Serialized Item", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "claim_date", "label": "Claim Date", "fieldtype": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
                {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nOpen\nUnder Inspection\nApproved\nRejected\nCancelled", "default": "Open", "in_list_view": 1},
                {"fieldname": "column_break_1", "fieldtype": "Column Break"},
                {"fieldname": "resolution_type", "label": "Proposed Resolution", "fieldtype": "Select", "options": "Replacement Unit\nBoard Repair\nFull Refund\nCredit Memo", "default": "Replacement Unit", "in_list_view": 1},
                {"fieldname": "claim_amount", "label": "Claim Value", "fieldtype": "Currency", "default": "1850"},
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
                "istable": spec.get("istable", 0),
                "is_submittable": spec.get("is_submittable", 0),
                "autoname": spec["autoname"],
                "title_field": spec.get("title_field"),
                "fields": spec["fields"],
                "permissions": spec.get("permissions", []),
            })
            doc.insert(ignore_permissions=True)
            created_doctypes.append(dt_name)
        elif dt_name == "Sales Order":
            # Ensure Sales Order has the child table field 'items' if it was created earlier
            so_meta = frappe.get_doc("DocType", "Sales Order")
            existing_fnames = {f.fieldname for f in so_meta.fields}
            if "items" not in existing_fnames:
                so_meta.append("fields", {"fieldname": "section_break_items", "label": "Order Line Items", "fieldtype": "Section Break"})
                so_meta.append("fields", {"fieldname": "items", "label": "Items", "fieldtype": "Table", "options": "Sales Order Item"})
                so_meta.save(ignore_permissions=True)

    frappe.db.commit()

    # 3. Seed Customers (10 enterprise accounts)
    sample_customers = [
        {"customer_name": "Acme Logistics Corp", "customer_group": "Enterprise", "territory": "North America", "credit_limit": 250000},
        {"customer_name": "Global Freight Partners", "customer_group": "Enterprise", "territory": "Europe", "credit_limit": 500000},
        {"customer_name": "Pacific Rim Supply Co", "customer_group": "Commercial", "territory": "APAC", "credit_limit": 150000},
        {"customer_name": "Nordic Maritime Group", "customer_group": "Enterprise", "territory": "Europe", "credit_limit": 420000},
        {"customer_name": "Apex Semiconductor Inc", "customer_group": "Enterprise", "territory": "North America", "credit_limit": 750000},
        {"customer_name": "Gulf Oasis Trading LLC", "customer_group": "Commercial", "territory": "Middle East", "credit_limit": 300000},
        {"customer_name": "Federal Defense Logistics", "customer_group": "Government", "territory": "North America", "credit_limit": 1200000},
        {"customer_name": "Tokyo Robotics K.K.", "customer_group": "Enterprise", "territory": "APAC", "credit_limit": 600000},
        {"customer_name": "Andes Mining & Minerals", "customer_group": "Commercial", "territory": "LATAM", "credit_limit": 220000},
        {"customer_name": "Rhine Valley Pharma AG", "customer_group": "Enterprise", "territory": "Europe", "credit_limit": 850000},
    ]
    for cust in sample_customers:
        if not frappe.db.exists("Customer", cust["customer_name"]):
            d = frappe.get_doc({"doctype": "Customer", **cust})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Customer:{d.name}")

    # 4. Seed Suppliers (8 global vendors)
    sample_suppliers = [
        {"supplier_name": "ShenZhen Precision Components", "supplier_group": "Hardware", "country": "China", "on_hold": 0},
        {"supplier_name": "EuroSteel Industrial Works", "supplier_group": "Raw Material", "country": "Germany", "on_hold": 0},
        {"supplier_name": "Alpine Cold-Chain Logistics AG", "supplier_group": "Logistics", "country": "Switzerland", "on_hold": 0},
        {"supplier_name": "HyperScale Cloud Systems", "supplier_group": "Cloud Services", "country": "United States", "on_hold": 0},
        {"supplier_name": "Rotterdam Port Terminal BV", "supplier_group": "Logistics", "country": "Netherlands", "on_hold": 0},
        {"supplier_name": "Taiwan Wafer Foundry Corp", "supplier_group": "Hardware", "country": "Taiwan", "on_hold": 0},
        {"supplier_name": "Baltic Timber & Packaging", "supplier_group": "Raw Material", "country": "Sweden", "on_hold": 1},
        {"supplier_name": "Continental Industrial Supply", "supplier_group": "Distributor", "country": "United Kingdom", "on_hold": 0},
    ]
    for sup in sample_suppliers:
        if not frappe.db.exists("Supplier", sup["supplier_name"]):
            d = frappe.get_doc({"doctype": "Supplier", **sup})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Supplier:{d.name}")

    # 5. Seed Items (12 SKUs)
    sample_items = [
        {"item_code": "SKU-IOT-400", "item_name": "CryoSense Cold-Chain Telemetry Gateway", "item_group": "Products", "standard_rate": 1850, "valuation_rate": 1120},
        {"item_code": "SKU-RACK-9U", "item_name": "Industrial Edge Server Enclosure 9U", "item_group": "Products", "standard_rate": 4200, "valuation_rate": 2950},
        {"item_code": "SKU-RFID-PRO", "item_name": "UHF Port Container Scanner Array", "item_group": "Products", "standard_rate": 6500, "valuation_rate": 4100},
        {"item_code": "SKU-LITH-200", "item_name": "Marine-Grade LiFePO4 Backup Pack 20kWh", "item_group": "Sub Assemblies", "standard_rate": 9800, "valuation_rate": 6800},
        {"item_code": "SKU-STEEL-CR", "item_name": "Cold-Rolled Galvanized Coil (Metric Ton)", "item_group": "Raw Material", "standard_rate": 1450, "valuation_rate": 1080},
        {"item_code": "SKU-PLC-X8", "item_name": "Programmable Warehouse Conveyor Controller", "item_group": "Products", "standard_rate": 3100, "valuation_rate": 1950},
        {"item_code": "SKU-SAAS-ENT", "item_name": "EXRP Fleet Control Enterprise License (Annual)", "item_group": "Services", "standard_rate": 24000, "valuation_rate": 2000},
        {"item_code": "SKU-VALVE-HP", "item_name": "High-Pressure Cryogenic Manifold Valve", "item_group": "Sub Assemblies", "standard_rate": 1250, "valuation_rate": 780},
        {"item_code": "SKU-DRONE-INV", "item_name": "Autonomous Aisle Inventory Drone Unit", "item_group": "Products", "standard_rate": 14500, "valuation_rate": 9400},
        {"item_code": "SKU-FIBER-10G", "item_name": "Armored Industrial Fiber Trunk 500m", "item_group": "Raw Material", "standard_rate": 890, "valuation_rate": 540},
    ]
    for it in sample_items:
        if not frappe.db.exists("Item", it["item_code"]):
            d = frappe.get_doc({"doctype": "Item", **it})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Item:{d.name}")

    # 6. Seed Warehouses (6 global facilities)
    sample_warehouses = [
        {"warehouse_name": "Rotterdam Hub", "warehouse_type": "Distribution Hub", "city": "Rotterdam", "capacity_cbm": 85000},
        {"warehouse_name": "Singapore FreeZone", "warehouse_type": "Bonded FreeZone", "city": "Singapore", "capacity_cbm": 62000},
        {"warehouse_name": "Newark Distribution Center", "warehouse_type": "Distribution Hub", "city": "Newark, NJ", "capacity_cbm": 74000},
        {"warehouse_name": "Frankfurt Cold Storage", "warehouse_type": "Cold Storage", "city": "Frankfurt", "capacity_cbm": 32000},
        {"warehouse_name": "Dubai Jebel Ali Depot", "warehouse_type": "Bonded FreeZone", "city": "Dubai", "capacity_cbm": 55000},
        {"warehouse_name": "Tokyo Automated Depot", "warehouse_type": "Distribution Hub", "city": "Tokyo", "capacity_cbm": 48000},
    ]
    for wh in sample_warehouses:
        if not frappe.db.exists("Warehouse", wh["warehouse_name"]):
            d = frappe.get_doc({"doctype": "Warehouse", **wh})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Warehouse:{d.name}")

    # 7. Seed CRM Leads (8 records)
    if frappe.db.count("Lead") < 5:
        sample_leads = [
            {"lead_name": "Henrik Lindqvist", "company_name": "ScandiPort Automation AB", "status": "Interested", "source": "Trade Show", "territory": "Europe", "annual_revenue": 45000000, "email_id": "h.lindqvist@scandiport.se"},
            {"lead_name": "Elena Rostova", "company_name": "Vanguard BioLogistics", "status": "Open", "source": "Website", "territory": "North America", "annual_revenue": 120000000, "email_id": "erostova@vanguardbio.com"},
            {"lead_name": "Kenji Takahashi", "company_name": "Osaka Heavy Cranes Ltd", "status": "Opportunity", "source": "Partner Referral", "territory": "APAC", "annual_revenue": 310000000, "email_id": "k.takahashi@osakacranes.jp"},
            {"lead_name": "Tariq Al-Mansoor", "company_name": "Crescent Petrochem Logistics", "status": "Interested", "source": "RFP Tender", "territory": "Middle East", "annual_revenue": 580000000, "email_id": "t.mansoor@crescentpetro.ae"},
            {"lead_name": "Clara Von Berg", "company_name": "Bavaria Auto Parts GmbH", "status": "Converted", "source": "Outbound Campaign", "territory": "Europe", "annual_revenue": 215000000, "email_id": "cvonberg@bavaria-parts.de"},
            {"lead_name": "Marcus Vance", "company_name": "Great Lakes Intermodal", "status": "Contacted", "source": "Website", "territory": "North America", "annual_revenue": 88000000, "email_id": "mvance@glintermodal.com"},
            {"lead_name": "Sofia Mendoza", "company_name": "Mercosur Cold Freight SA", "status": "Interested", "source": "Trade Show", "territory": "LATAM", "annual_revenue": 64000000, "email_id": "smendoza@mercosurcold.ar"},
            {"lead_name": "Liam O'Connor", "company_name": "Celtic Semi Packaging", "status": "Open", "source": "Partner Referral", "territory": "Europe", "annual_revenue": 95000000, "email_id": "loconnor@celticsemi.ie"},
        ]
        for ld in sample_leads:
            d = frappe.get_doc({"doctype": "Lead", **ld})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Lead:{d.name}")

    # 8. Seed CRM Opportunities (8 records)
    if frappe.db.count("Opportunity") < 5:
        sample_opps = [
            {"party_name": "Rhine Valley Pharma AG", "opportunity_type": "Sales", "sales_stage": "Negotiation/Review", "status": "Open", "opportunity_amount": 340000, "probability": 80, "expected_closing": "2026-11-28"},
            {"party_name": "Federal Defense Logistics", "opportunity_type": "Enterprise Renewal", "sales_stage": "Proposal/Price Quote", "status": "Quotation", "opportunity_amount": 680000, "probability": 70, "expected_closing": "2026-12-10"},
            {"party_name": "Apex Semiconductor Inc", "opportunity_type": "Expansion", "sales_stage": "Value Proposition", "status": "Open", "opportunity_amount": 290000, "probability": 60, "expected_closing": "2026-12-15"},
            {"party_name": "Nordic Maritime Group", "opportunity_type": "Sales", "sales_stage": "Closed Won", "status": "Converted", "opportunity_amount": 185000, "probability": 100, "expected_closing": "2026-11-05"},
            {"party_name": "Tokyo Robotics K.K.", "opportunity_type": "Support Contract", "sales_stage": "Needs Analysis", "status": "Open", "opportunity_amount": 145000, "probability": 45, "expected_closing": "2026-12-22"},
            {"party_name": "Gulf Oasis Trading LLC", "opportunity_type": "Sales", "sales_stage": "Proposal/Price Quote", "status": "Quotation", "opportunity_amount": 210000, "probability": 65, "expected_closing": "2026-11-30"},
            {"party_name": "ScandiPort Automation AB", "opportunity_type": "Sales", "sales_stage": "Qualification", "status": "Open", "opportunity_amount": 95000, "probability": 30, "expected_closing": "2027-01-15"},
            {"party_name": "Andes Mining & Minerals", "opportunity_type": "Sales", "sales_stage": "Closed Lost", "status": "Lost", "opportunity_amount": 115000, "probability": 0, "expected_closing": "2026-11-01"},
        ]
        for opp in sample_opps:
            d = frappe.get_doc({"doctype": "Opportunity", **opp})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Opportunity:{d.name}")

    # 9. Seed Quotations (8 records)
    if frappe.db.count("Quotation") < 6:
        sample_qtns = [
            {"party_name": "Rhine Valley Pharma AG", "transaction_date": "2026-11-02", "valid_till": "2026-12-02", "status": "Open", "grand_total": 340000},
            {"party_name": "Federal Defense Logistics", "transaction_date": "2026-11-03", "valid_till": "2026-12-15", "status": "Open", "grand_total": 680000},
            {"party_name": "Nordic Maritime Group", "transaction_date": "2026-11-01", "valid_till": "2026-12-01", "status": "Ordered", "grand_total": 185000},
            {"party_name": "Gulf Oasis Trading LLC", "transaction_date": "2026-11-04", "valid_till": "2026-12-04", "status": "Open", "grand_total": 210000},
            {"party_name": "Apex Semiconductor Inc", "transaction_date": "2026-11-04", "valid_till": "2026-12-10", "status": "Open", "grand_total": 290000},
            {"party_name": "Tokyo Robotics K.K.", "transaction_date": "2026-11-05", "valid_till": "2026-12-05", "status": "Draft", "grand_total": 145000},
        ]
        for qtn in sample_qtns:
            d = frappe.get_doc({"doctype": "Quotation", **qtn})
            d.insert(ignore_permissions=True)
            if qtn["status"] in ("Open", "Ordered"):
                d.submit()
            seeded_records.append(f"Quotation:{d.name}")

    # 10. Seed Sales Orders (15 total orders with child line items)
    if frappe.db.count("Sales Order") < 12:
        more_orders = [
            {
                "customer": "Nordic Maritime Group",
                "transaction_date": "2026-11-01",
                "delivery_date": "2026-11-18",
                "status": "To Deliver and Bill",
                "grand_total": 185000,
                "submit": True,
                "items": [
                    {"item_code": "SKU-IOT-400", "item_name": "CryoSense Cold-Chain Telemetry Gateway", "qty": 50, "rate": 1850, "amount": 92500},
                    {"item_code": "SKU-LITH-200", "item_name": "Marine-Grade LiFePO4 Backup Pack 20kWh", "qty": 10, "rate": 9250, "amount": 92500},
                ],
            },
            {
                "customer": "Apex Semiconductor Inc",
                "transaction_date": "2026-11-02",
                "delivery_date": "2026-11-22",
                "status": "Pending",
                "grand_total": 294000,
                "submit": True,
                "items": [
                    {"item_code": "SKU-RACK-9U", "item_name": "Industrial Edge Server Enclosure 9U", "qty": 40, "rate": 4200, "amount": 168000},
                    {"item_code": "SKU-DRONE-INV", "item_name": "Autonomous Aisle Inventory Drone Unit", "qty": 9, "rate": 14000, "amount": 126000},
                ],
            },
            {
                "customer": "Rhine Valley Pharma AG",
                "transaction_date": "2026-11-03",
                "delivery_date": "2026-11-24",
                "status": "Pending",
                "grand_total": 340000,
                "submit": False,
                "items": [
                    {"item_code": "SKU-IOT-400", "item_name": "CryoSense Cold-Chain Telemetry Gateway", "qty": 100, "rate": 1850, "amount": 185000},
                    {"item_code": "SKU-VALVE-HP", "item_name": "High-Pressure Cryogenic Manifold Valve", "qty": 124, "rate": 1250, "amount": 155000},
                ],
            },
            {
                "customer": "Federal Defense Logistics",
                "transaction_date": "2026-11-03",
                "delivery_date": "2026-12-01",
                "status": "Pending",
                "grand_total": 480000,
                "submit": False,
                "items": [
                    {"item_code": "SKU-RFID-PRO", "item_name": "UHF Port Container Scanner Array", "qty": 60, "rate": 6500, "amount": 390000},
                    {"item_code": "SKU-SAAS-ENT", "item_name": "EXRP Fleet Control Enterprise License (Annual)", "qty": 4, "rate": 22500, "amount": 90000},
                ],
            },
            {
                "customer": "Gulf Oasis Trading LLC",
                "transaction_date": "2026-11-04",
                "delivery_date": "2026-11-26",
                "status": "To Deliver and Bill",
                "grand_total": 96500,
                "submit": True,
                "items": [
                    {"item_code": "SKU-PLC-X8", "item_name": "Programmable Warehouse Conveyor Controller", "qty": 25, "rate": 3100, "amount": 77500},
                    {"item_code": "SKU-FIBER-10G", "item_name": "Armored Industrial Fiber Trunk 500m", "qty": 20, "rate": 950, "amount": 19000},
                ],
            },
            {
                "customer": "Tokyo Robotics K.K.",
                "transaction_date": "2026-11-04",
                "delivery_date": "2026-11-29",
                "status": "Completed",
                "grand_total": 145000,
                "submit": True,
                "items": [
                    {"item_code": "SKU-DRONE-INV", "item_name": "Autonomous Aisle Inventory Drone Unit", "qty": 10, "rate": 14500, "amount": 145000},
                ],
            },
            {
                "customer": "Andes Mining & Minerals",
                "transaction_date": "2026-11-05",
                "delivery_date": "2026-12-05",
                "status": "Draft",
                "grand_total": 58000,
                "submit": False,
                "items": [
                    {"item_code": "SKU-STEEL-CR", "item_name": "Cold-Rolled Galvanized Coil (Metric Ton)", "qty": 40, "rate": 1450, "amount": 58000},
                ],
            },
            {
                "customer": "Pacific Rim Supply Co",
                "transaction_date": "2026-11-05",
                "delivery_date": "2026-11-27",
                "status": "Pending",
                "grand_total": 112000,
                "submit": False,
                "items": [
                    {"item_code": "SKU-RACK-9U", "item_name": "Industrial Edge Server Enclosure 9U", "qty": 20, "rate": 4200, "amount": 84000},
                    {"item_code": "SKU-SAAS-ENT", "item_name": "EXRP Fleet Control Enterprise License (Annual)", "qty": 1, "rate": 28000, "amount": 28000},
                ],
            },
        ]
        for so in more_orders:
            should_submit = so.pop("submit", False)
            d = frappe.get_doc({"doctype": "Sales Order", **so})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Sales Order:{d.name}")

    # Backfill child items on any earlier Sales Orders that have 0 child items
    for so_row in frappe.get_all("Sales Order", fields=["name", "grand_total"]):
        if frappe.db.count("Sales Order Item", {"parent": so_row.name}) == 0:
            so_doc = frappe.get_doc("Sales Order", so_row.name)
            amt = float(so_row.grand_total or 48500)
            row_doc = frappe.get_doc({
                "doctype": "Sales Order Item",
                "parent": so_doc.name,
                "parenttype": "Sales Order",
                "parentfield": "items",
                "idx": 1,
                "item_code": "SKU-IOT-400",
                "item_name": "CryoSense Cold-Chain Telemetry Gateway",
                "qty": 10,
                "rate": amt / 10.0,
                "amount": amt,
            })
            row_doc.db_insert()

    # 11. Seed Delivery Notes (6 total)
    submitted_sos = [r.name for r in frappe.get_all("Sales Order", filters={"docstatus": 1}, limit=6)]
    if frappe.db.count("Delivery Note") < 6 and submitted_sos:
        extra_dns = [
            {"customer": "Nordic Maritime Group", "posting_date": "2026-11-04", "sales_order": submitted_sos[0], "warehouse": "Rotterdam Hub", "status": "Completed", "grand_total": 185000, "submit": True},
            {"customer": "Apex Semiconductor Inc", "posting_date": "2026-11-05", "sales_order": submitted_sos[min(1, len(submitted_sos) - 1)], "warehouse": "Newark Distribution Center", "status": "To Bill", "grand_total": 294000, "submit": True},
            {"customer": "Gulf Oasis Trading LLC", "posting_date": "2026-11-05", "sales_order": submitted_sos[min(2, len(submitted_sos) - 1)], "warehouse": "Dubai Jebel Ali Depot", "status": "Draft", "grand_total": 96500, "submit": False},
            {"customer": "Tokyo Robotics K.K.", "posting_date": "2026-11-05", "sales_order": submitted_sos[min(3, len(submitted_sos) - 1)], "warehouse": "Tokyo Automated Depot", "status": "Completed", "grand_total": 145000, "submit": True},
        ]
        for dn in extra_dns:
            should_submit = dn.pop("submit", False)
            d = frappe.get_doc({"doctype": "Delivery Note", **dn})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Delivery Note:{d.name}")

    # 12. Seed Material Requests (6 records)
    if frappe.db.count("Material Request") == 0:
        sample_mrs = [
            {"title": "Q4 CryoSense Sensor Replenishment", "material_request_type": "Purchase", "transaction_date": "2026-11-01", "schedule_date": "2026-11-15", "department": "Supply Chain", "status": "Ordered", "estimated_cost": 112000, "submit": True},
            {"title": "Frankfurt Cold-Storage Backup Battery Upgrade", "material_request_type": "Purchase", "transaction_date": "2026-11-02", "schedule_date": "2026-11-20", "department": "Operations", "status": "Pending", "estimated_cost": 68000, "submit": True},
            {"title": "Inter-Hub Transfer Rotterdam to Newark", "material_request_type": "Material Transfer", "transaction_date": "2026-11-03", "schedule_date": "2026-11-18", "department": "Operations", "status": "Partially Ordered", "estimated_cost": 42000, "submit": True},
            {"title": "Taiwan Wafer Controller Batch #14", "material_request_type": "Purchase", "transaction_date": "2026-11-04", "schedule_date": "2026-11-28", "department": "Engineering", "status": "Pending", "estimated_cost": 195000, "submit": False},
            {"title": "Galvanized Coil Restock for Server Racks", "material_request_type": "Purchase", "transaction_date": "2026-11-05", "schedule_date": "2026-11-25", "department": "Supply Chain", "status": "Draft", "estimated_cost": 54000, "submit": False},
            {"title": "Tokyo Depot Autonomous Drone Spare Parts", "material_request_type": "Material Issue", "transaction_date": "2026-11-05", "schedule_date": "2026-11-12", "department": "Operations", "status": "Pending", "estimated_cost": 28500, "submit": True},
        ]
        for mr in sample_mrs:
            should_submit = mr.pop("submit", False)
            d = frappe.get_doc({"doctype": "Material Request", **mr})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Material Request:{d.name}")

    # 13. Seed Purchase Orders (8 records)
    created_pos: List[str] = []
    if frappe.db.count("Purchase Order") == 0:
        sample_pos = [
            {"supplier": "ShenZhen Precision Components", "transaction_date": "2026-11-01", "schedule_date": "2026-11-16", "status": "To Receive and Bill", "grand_total": 112000, "is_subcontracted": 0, "submit": True},
            {"supplier": "EuroSteel Industrial Works", "transaction_date": "2026-11-01", "schedule_date": "2026-11-14", "status": "Completed", "grand_total": 86400, "is_subcontracted": 0, "submit": True},
            {"supplier": "Taiwan Wafer Foundry Corp", "transaction_date": "2026-11-02", "schedule_date": "2026-11-22", "status": "To Receive and Bill", "grand_total": 245000, "is_subcontracted": 1, "submit": True},
            {"supplier": "Alpine Cold-Chain Logistics AG", "transaction_date": "2026-11-03", "schedule_date": "2026-11-19", "status": "Pending", "grand_total": 38500, "is_subcontracted": 0, "submit": False},
            {"supplier": "HyperScale Cloud Systems", "transaction_date": "2026-11-03", "schedule_date": "2026-11-10", "status": "Completed", "grand_total": 64000, "is_subcontracted": 0, "submit": True},
            {"supplier": "Rotterdam Port Terminal BV", "transaction_date": "2026-11-04", "schedule_date": "2026-11-20", "status": "Pending", "grand_total": 29000, "is_subcontracted": 0, "submit": False},
            {"supplier": "Continental Industrial Supply", "transaction_date": "2026-11-04", "schedule_date": "2026-11-25", "status": "Pending", "grand_total": 152000, "is_subcontracted": 0, "submit": False},
            {"supplier": "Baltic Timber & Packaging", "transaction_date": "2026-11-05", "schedule_date": "2026-11-30", "status": "On Hold", "grand_total": 18900, "is_subcontracted": 0, "submit": False},
        ]
        for po in sample_pos:
            should_submit = po.pop("submit", False)
            d = frappe.get_doc({"doctype": "Purchase Order", **po})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            created_pos.append(d.name)
            seeded_records.append(f"Purchase Order:{d.name}")
    else:
        created_pos = [r.name for r in frappe.get_all("Purchase Order", limit=5)]

    # 14. Seed Purchase Receipts (5 records)
    if frappe.db.count("Purchase Receipt") == 0 and created_pos:
        sample_precs = [
            {"supplier": "ShenZhen Precision Components", "posting_date": "2026-11-03", "purchase_order": created_pos[0], "warehouse": "Singapore FreeZone", "status": "To Bill", "grand_total": 112000, "submit": True},
            {"supplier": "EuroSteel Industrial Works", "posting_date": "2026-11-03", "purchase_order": created_pos[min(1, len(created_pos) - 1)], "warehouse": "Rotterdam Hub", "status": "Completed", "grand_total": 86400, "submit": True},
            {"supplier": "Taiwan Wafer Foundry Corp", "posting_date": "2026-11-04", "purchase_order": created_pos[min(2, len(created_pos) - 1)], "warehouse": "Tokyo Automated Depot", "status": "To Bill", "grand_total": 245000, "submit": True},
            {"supplier": "Continental Industrial Supply", "posting_date": "2026-11-05", "purchase_order": created_pos[min(3, len(created_pos) - 1)], "warehouse": "Newark Distribution Center", "status": "Draft", "grand_total": 152000, "submit": False},
        ]
        for pr in sample_precs:
            should_submit = pr.pop("submit", False)
            d = frappe.get_doc({"doctype": "Purchase Receipt", **pr})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Purchase Receipt:{d.name}")

    # 15. Seed Sales Invoices (8 records linked to submitted Sales Orders)
    if frappe.db.count("Sales Invoice") == 0 and submitted_sos:
        sample_sinvs = [
            {"customer": "Acme Logistics Corp", "posting_date": "2026-11-02", "due_date": "2026-12-02", "sales_order": submitted_sos[0], "status": "Paid", "grand_total": 48500, "outstanding_amount": 0, "submit": True},
            {"customer": "Global Freight Partners", "posting_date": "2026-11-02", "due_date": "2026-12-02", "sales_order": submitted_sos[min(1, len(submitted_sos) - 1)], "status": "Unpaid", "grand_total": 125000, "outstanding_amount": 125000, "submit": True},
            {"customer": "Nordic Maritime Group", "posting_date": "2026-11-03", "due_date": "2026-12-03", "sales_order": submitted_sos[min(2, len(submitted_sos) - 1)], "status": "Paid", "grand_total": 185000, "outstanding_amount": 0, "submit": True},
            {"customer": "Apex Semiconductor Inc", "posting_date": "2026-11-04", "due_date": "2026-11-15", "sales_order": submitted_sos[min(3, len(submitted_sos) - 1)], "status": "Overdue", "grand_total": 294000, "outstanding_amount": 294000, "submit": True},
            {"customer": "Gulf Oasis Trading LLC", "posting_date": "2026-11-04", "due_date": "2026-12-04", "sales_order": submitted_sos[min(4, len(submitted_sos) - 1)], "status": "Partly Paid", "grand_total": 96500, "outstanding_amount": 46500, "submit": True},
            {"customer": "Tokyo Robotics K.K.", "posting_date": "2026-11-05", "due_date": "2026-12-05", "sales_order": submitted_sos[min(5, len(submitted_sos) - 1)], "status": "Paid", "grand_total": 145000, "outstanding_amount": 0, "submit": True},
            {"customer": "Rhine Valley Pharma AG", "posting_date": "2026-11-05", "due_date": "2026-12-05", "sales_order": submitted_sos[0], "status": "Draft", "grand_total": 340000, "outstanding_amount": 340000, "submit": False},
        ]
        for sinv in sample_sinvs:
            should_submit = sinv.pop("submit", False)
            d = frappe.get_doc({"doctype": "Sales Invoice", **sinv})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Sales Invoice:{d.name}")

    # 16. Seed Payment Entries (6 records)
    if frappe.db.count("Payment Entry") == 0:
        sample_pays = [
            {"payment_type": "Receive", "party_type": "Customer", "party": "Acme Logistics Corp", "posting_date": "2026-11-03", "mode_of_payment": "Wire Transfer", "paid_amount": 48500, "reference_no": "SWIFT-CHASUS33-88291", "status": "Reconciled", "submit": True},
            {"payment_type": "Receive", "party_type": "Customer", "party": "Nordic Maritime Group", "posting_date": "2026-11-04", "mode_of_payment": "Wire Transfer", "paid_amount": 185000, "reference_no": "SWIFT-NDEASESS-44102", "status": "Reconciled", "submit": True},
            {"payment_type": "Receive", "party_type": "Customer", "party": "Gulf Oasis Trading LLC", "posting_date": "2026-11-04", "mode_of_payment": "Letter of Credit", "paid_amount": 50000, "reference_no": "LC-EMIRATES-9012", "status": "Submitted", "submit": True},
            {"payment_type": "Receive", "party_type": "Customer", "party": "Tokyo Robotics K.K.", "posting_date": "2026-11-05", "mode_of_payment": "Wire Transfer", "paid_amount": 145000, "reference_no": "SWIFT-BOTKJPJT-7731", "status": "Reconciled", "submit": True},
            {"payment_type": "Pay", "party_type": "Supplier", "party": "EuroSteel Industrial Works", "posting_date": "2026-11-04", "mode_of_payment": "Wire Transfer", "paid_amount": 86400, "reference_no": "SEPA-DEUTDEFF-3109", "status": "Reconciled", "submit": True},
            {"payment_type": "Pay", "party_type": "Supplier", "party": "HyperScale Cloud Systems", "posting_date": "2026-11-05", "mode_of_payment": "ACH", "paid_amount": 64000, "reference_no": "ACH-SVB-20261105", "status": "Submitted", "submit": True},
        ]
        for pay in sample_pays:
            should_submit = pay.pop("submit", False)
            d = frappe.get_doc({"doctype": "Payment Entry", **pay})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Payment Entry:{d.name}")

    # 17. Seed Stock Ledger Entries (Tier 0 Protected Inventory Ledger - 8 records)
    if frappe.db.count("Stock Ledger Entry") == 0:
        sample_sles = [
            {"item_code": "SKU-IOT-400", "warehouse": "Singapore FreeZone", "posting_date": "2026-11-03", "actual_qty": 100, "valuation_rate": 1120, "stock_value_difference": 112000, "voucher_type": "Purchase Receipt", "voucher_no": "PREC-2026-0001"},
            {"item_code": "SKU-STEEL-CR", "warehouse": "Rotterdam Hub", "posting_date": "2026-11-03", "actual_qty": 80, "valuation_rate": 1080, "stock_value_difference": 86400, "voucher_type": "Purchase Receipt", "voucher_no": "PREC-2026-0002"},
            {"item_code": "SKU-IOT-400", "warehouse": "Rotterdam Hub", "posting_date": "2026-11-04", "actual_qty": -50, "valuation_rate": 1120, "stock_value_difference": -56000, "voucher_type": "Delivery Note", "voucher_no": "DN-2026-0003"},
            {"item_code": "SKU-RACK-9U", "warehouse": "Newark Distribution Center", "posting_date": "2026-11-05", "actual_qty": -40, "valuation_rate": 2950, "stock_value_difference": -118000, "voucher_type": "Delivery Note", "voucher_no": "DN-2026-0004"},
            {"item_code": "SKU-DRONE-INV", "warehouse": "Tokyo Automated Depot", "posting_date": "2026-11-05", "actual_qty": -10, "valuation_rate": 9400, "stock_value_difference": -94000, "voucher_type": "Delivery Note", "voucher_no": "DN-2026-0006"},
            {"item_code": "SKU-LITH-200", "warehouse": "Frankfurt Cold Storage", "posting_date": "2026-11-05", "actual_qty": 25, "valuation_rate": 6800, "stock_value_difference": 170000, "voucher_type": "Purchase Receipt", "voucher_no": "PREC-2026-0003"},
        ]
        for sle in sample_sles:
            d = frappe.get_doc({"doctype": "Stock Ledger Entry", **sle})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Stock Ledger Entry:{d.name}")

    # 18. Seed GL Entries (Tier 0 Protected Accounting Ledger - 8 double-entry rows)
    if frappe.db.count("GL Entry") == 0:
        sample_gles = [
            {"posting_date": "2026-11-02", "account": "1100 - Accounts Receivable - EXRP", "party_type": "Customer", "party": "Acme Logistics Corp", "debit": 48500, "credit": 0, "voucher_type": "Sales Invoice", "voucher_no": "SINV-2026-0001", "remarks": "Invoice posting against SO-2026-0001"},
            {"posting_date": "2026-11-02", "account": "4100 - Product Sales Revenue - EXRP", "party_type": "Customer", "party": "Acme Logistics Corp", "debit": 0, "credit": 48500, "voucher_type": "Sales Invoice", "voucher_no": "SINV-2026-0001", "remarks": "Revenue recognition"},
            {"posting_date": "2026-11-03", "account": "1020 - Citibank Operating USD - EXRP", "party_type": "Customer", "party": "Acme Logistics Corp", "debit": 48500, "credit": 0, "voucher_type": "Payment Entry", "voucher_no": "PAY-2026-0001", "remarks": "SWIFT wire settlement"},
            {"posting_date": "2026-11-03", "account": "1100 - Accounts Receivable - EXRP", "party_type": "Customer", "party": "Acme Logistics Corp", "debit": 0, "credit": 48500, "voucher_type": "Payment Entry", "voucher_no": "PAY-2026-0001", "remarks": "AR clearance"},
            {"posting_date": "2026-11-03", "account": "1100 - Accounts Receivable - EXRP", "party_type": "Customer", "party": "Nordic Maritime Group", "debit": 185000, "credit": 0, "voucher_type": "Sales Invoice", "voucher_no": "SINV-2026-0003", "remarks": "Invoice posting"},
            {"posting_date": "2026-11-03", "account": "4100 - Product Sales Revenue - EXRP", "party_type": "Customer", "party": "Nordic Maritime Group", "debit": 0, "credit": 185000, "voucher_type": "Sales Invoice", "voucher_no": "SINV-2026-0003", "remarks": "Revenue recognition"},
            {"posting_date": "2026-11-04", "account": "2100 - Accounts Payable - EXRP", "party_type": "Supplier", "party": "EuroSteel Industrial Works", "debit": 86400, "credit": 0, "voucher_type": "Payment Entry", "voucher_no": "PAY-2026-0005", "remarks": "Supplier SEPA settlement"},
            {"posting_date": "2026-11-04", "account": "1020 - Citibank Operating USD - EXRP", "party_type": "Supplier", "party": "EuroSteel Industrial Works", "debit": 0, "credit": 86400, "voucher_type": "Payment Entry", "voucher_no": "PAY-2026-0005", "remarks": "Outgoing bank transfer"},
        ]
        for gle in sample_gles:
            d = frappe.get_doc({"doctype": "GL Entry", **gle})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"GL Entry:{d.name}")

    # 19. Seed Employees (8 records)
    if frappe.db.count("Employee") == 0:
        sample_emps = [
            {"employee_name": "pieter van der Berg", "department": "Operations", "designation": "VP Global Operations", "status": "Active", "branch": "Amsterdam HQ", "date_of_joining": "2022-03-01", "ctc": 215000},
            {"employee_name": "Amira Al-Farsi", "department": "Finance", "designation": "Global Finance Director", "status": "Active", "branch": "Dubai Hub", "date_of_joining": "2022-06-15", "ctc": 225000},
            {"employee_name": "David Chen", "department": "Supply Chain", "designation": "Head of APAC Logistics", "status": "Active", "branch": "Singapore Office", "date_of_joining": "2023-01-10", "ctc": 175000},
            {"employee_name": "Sarah Jenkins", "department": "Sales", "designation": "Enterprise Account Director", "status": "Active", "branch": "New York Office", "date_of_joining": "2023-04-20", "ctc": 190000},
            {"employee_name": "Lukas Weber", "department": "Engineering", "designation": "Principal IoT Systems Architect", "status": "Active", "branch": "Frankfurt Lab", "date_of_joining": "2023-08-01", "ctc": 182000},
            {"employee_name": "Yuki Sato", "department": "Operations", "designation": "Robotics Automation Lead", "status": "Active", "branch": "Tokyo Depot", "date_of_joining": "2024-02-12", "ctc": 160000},
            {"employee_name": "Mateo Silva", "department": "Sales", "designation": "Regional Sales Manager LATAM", "status": "On Leave", "branch": "Sao Paulo Office", "date_of_joining": "2024-05-01", "ctc": 135000},
            {"employee_name": "Hannah Johansson", "department": "Supply Chain", "designation": "Senior Procurement Specialist", "status": "Active", "branch": "Amsterdam HQ", "date_of_joining": "2024-09-15", "ctc": 120000},
        ]
        for emp in sample_emps:
            emp["employee_name"] = emp["employee_name"][0].upper() + emp["employee_name"][1:]
            d = frappe.get_doc({"doctype": "Employee", **emp})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Employee:{d.name}")

    # 20. Seed Expense Claims (6 records)
    if frappe.db.count("Expense Claim") == 0:
        sample_exps = [
            {"employee_name": "Sarah Jenkins", "department": "Sales", "posting_date": "2026-11-01", "expense_type": "Airfare & Travel", "total_claimed_amount": 4250, "approval_status": "Approved", "status": "Paid", "submit": True},
            {"employee_name": "David Chen", "department": "Supply Chain", "posting_date": "2026-11-02", "expense_type": "Client Hospitality", "total_claimed_amount": 1890, "approval_status": "Approved", "status": "Submitted", "submit": True},
            {"employee_name": "Lukas Weber", "department": "Engineering", "posting_date": "2026-11-03", "expense_type": "Field Equipment", "total_claimed_amount": 6400, "approval_status": "Pending Approval", "status": "Draft", "submit": False},
            {"employee_name": "Yuki Sato", "department": "Operations", "posting_date": "2026-11-04", "expense_type": "Conference", "total_claimed_amount": 3100, "approval_status": "Pending Approval", "status": "Draft", "submit": False},
            {"employee_name": "Hannah Johansson", "department": "Supply Chain", "posting_date": "2026-11-04", "expense_type": "Airfare & Travel", "total_claimed_amount": 2750, "approval_status": "Approved", "status": "Submitted", "submit": True},
            {"employee_name": "Sarah Jenkins", "department": "Sales", "posting_date": "2026-11-05", "expense_type": "Cloud & Software", "total_claimed_amount": 950, "approval_status": "Pending Approval", "status": "Draft", "submit": False},
        ]
        for exp in sample_exps:
            should_submit = exp.pop("submit", False)
            d = frappe.get_doc({"doctype": "Expense Claim", **exp})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Expense Claim:{d.name}")

    # 21. Seed Projects (6 records)
    if frappe.db.count("Project") == 0:
        sample_projs = [
            {"project_name": "Rotterdam Port Automated RFID Gate Rollout", "customer": "Nordic Maritime Group", "project_type": "External Client", "status": "Open", "priority": "Critical", "estimated_costing": 420000, "percent_complete": 65},
            {"project_name": "Rhine Valley Cryo-Chain Sensor Telemetry", "customer": "Rhine Valley Pharma AG", "project_type": "External Client", "status": "Open", "priority": "High", "estimated_costing": 340000, "percent_complete": 40},
            {"project_name": "Tokyo Depot Autonomous Drone Fleet Phase 2", "customer": "Tokyo Robotics K.K.", "project_type": "Supply Chain Rollout", "status": "Completed", "priority": "High", "estimated_costing": 180000, "percent_complete": 100},
            {"project_name": "Federal Defense Secure Warehouse Mesh", "customer": "Federal Defense Logistics", "project_type": "External Client", "status": "Open", "priority": "Critical", "estimated_costing": 680000, "percent_complete": 20},
            {"project_name": "Global ERP v15 AI Control Plane Deployment", "customer": "EXRP Global Enterprises", "project_type": "Internal Infrastructure", "status": "Open", "priority": "High", "estimated_costing": 150000, "percent_complete": 90},
            {"project_name": "LATAM Bonded Warehouse Feasibility Study", "customer": "Andes Mining & Minerals", "project_type": "R&D", "status": "On Hold", "priority": "Low", "estimated_costing": 45000, "percent_complete": 15},
        ]
        for prj in sample_projs:
            d = frappe.get_doc({"doctype": "Project", **prj})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Project:{d.name}")

    # 22. Seed Manufacturing records (BOM and Work Order)
    if frappe.db.count("BOM") == 0:
        sample_boms = [
            {"item": "SKU-IOT-400", "quantity": 1, "is_active": 1, "is_default": 1, "total_cost": 1120, "currency": "USD"},
            {"item": "SKU-RACK-9U", "quantity": 1, "is_active": 1, "is_default": 1, "total_cost": 2950, "currency": "USD"},
            {"item": "SKU-DRONE-INV", "quantity": 1, "is_active": 1, "is_default": 1, "total_cost": 9400, "currency": "USD"},
            {"item": "SKU-PLC-X8", "quantity": 1, "is_active": 1, "is_default": 1, "total_cost": 1950, "currency": "USD"},
        ]
        for bom in sample_boms:
            d = frappe.get_doc({"doctype": "BOM", **bom})
            d.insert(ignore_permissions=True)
            d.submit()
            seeded_records.append(f"BOM:{d.name}")

    if frappe.db.count("Work Order") == 0:
        boms = [r.name for r in frappe.get_all("BOM", limit=4)]
        sample_wos = [
            {"production_item": "SKU-IOT-400", "qty": 50, "bom_no": boms[0] if boms else "BOM-0001", "status": "In Process", "target_warehouse": "Rotterdam Hub", "produced_qty": 20, "submit": True},
            {"production_item": "SKU-RACK-9U", "qty": 25, "bom_no": boms[1] if len(boms) > 1 else "BOM-0002", "status": "Not Started", "target_warehouse": "Newark Distribution Center", "produced_qty": 0, "submit": True},
            {"production_item": "SKU-DRONE-INV", "qty": 10, "bom_no": boms[2] if len(boms) > 2 else "BOM-0003", "status": "In Process", "target_warehouse": "Tokyo Automated Depot", "produced_qty": 4, "submit": True},
            {"production_item": "SKU-PLC-X8", "qty": 30, "bom_no": boms[3] if len(boms) > 3 else "BOM-0004", "status": "Completed", "target_warehouse": "Singapore FreeZone", "produced_qty": 30, "submit": True},
            {"production_item": "SKU-IOT-400", "qty": 100, "bom_no": boms[0] if boms else "BOM-0001", "status": "Draft", "target_warehouse": "Frankfurt Cold Storage", "produced_qty": 0, "submit": False},
        ]
        for wo in sample_wos:
            should_submit = wo.pop("submit", False)
            d = frappe.get_doc({"doctype": "Work Order", **wo})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Work Order:{d.name}")

    # 23. Seed Support records (Issue and Warranty Claim)
    if frappe.db.count("Issue") == 0:
        sample_issues = [
            {"subject": "Telemetry sync timeout on CryoSense unit at Rotterdam berth 4", "customer": "Acme Logistics Corp", "status": "Open", "priority": "High", "issue_type": "Firmware Telemetry", "resolution_time": 12},
            {"subject": "Damaged container scanner bracket on maritime arrival", "customer": "Nordic Maritime Group", "status": "Replied", "priority": "Medium", "issue_type": "Hardware Fault", "resolution_time": 24},
            {"subject": "Battery cell degradation alert on backup unit #88", "customer": "Federal Defense Logistics", "status": "On Hold", "priority": "Urgent", "issue_type": "Hardware Fault", "resolution_time": 8},
            {"subject": "Freight invoice line discrepancy on SO-2026-0002", "customer": "Global Freight Partners", "status": "Resolved", "priority": "Low", "issue_type": "Billing Dispute", "resolution_time": 48},
            {"subject": "Conveyor PLC firmware heartbeat drop in Dubai Hub", "customer": "Gulf Oasis Trading LLC", "status": "Open", "priority": "Urgent", "issue_type": "SLA Breach", "resolution_time": 6},
        ]
        for iss in sample_issues:
            d = frappe.get_doc({"doctype": "Issue", **iss})
            d.insert(ignore_permissions=True)
            seeded_records.append(f"Issue:{d.name}")

    if frappe.db.count("Warranty Claim") == 0:
        sample_wcs = [
            {"customer": "Acme Logistics Corp", "item_code": "SKU-IOT-400", "status": "Under Inspection", "resolution_type": "Replacement Unit", "claim_amount": 1850, "submit": True},
            {"customer": "Nordic Maritime Group", "item_code": "SKU-LITH-200", "status": "Approved", "resolution_type": "Full Refund", "claim_amount": 9250, "submit": True},
            {"customer": "Tokyo Robotics K.K.", "item_code": "SKU-DRONE-INV", "status": "Open", "resolution_type": "Board Repair", "claim_amount": 3200, "submit": False},
            {"customer": "Gulf Oasis Trading LLC", "item_code": "SKU-PLC-X8", "status": "Approved", "resolution_type": "Replacement Unit", "claim_amount": 3100, "submit": True},
        ]
        for wc in sample_wcs:
            should_submit = wc.pop("submit", False)
            d = frappe.get_doc({"doctype": "Warranty Claim", **wc})
            d.insert(ignore_permissions=True)
            if should_submit:
                d.submit()
            seeded_records.append(f"Warranty Claim:{d.name}")

    frappe.db.commit()

    # 24. Provision Frappe Desk Workspaces so the full ERP appears in the left sidebar
    import json

    def _upsert_workspace(
        ws_name: str,
        title: str,
        icon: str,
        seq: float,
        shortcuts: List[Dict[str, Any]],
        cards: List[Dict[str, Any]],
    ) -> None:
        content_blocks: List[Dict[str, Any]] = [
            {
                "id": f"hdr_sc_{ws_name[:6].replace(' ', '_')}",
                "type": "header",
                "data": {"text": '<span class="h4"><b>Quick Access & Live Counts</b></span>', "col": 12},
            }
        ]
        ws_shortcuts: List[Dict[str, Any]] = []
        for idx, sc in enumerate(shortcuts):
            sc_label = sc["label"]
            content_blocks.append({
                "id": f"sc_{idx}_{sc_label[:8].replace(' ', '_')}",
                "type": "shortcut",
                "data": {"shortcut_name": sc_label, "col": 3},
            })
            ws_shortcuts.append({
                "label": sc_label,
                "type": "DocType",
                "link_to": sc["link_to"],
                "doc_view": sc.get("doc_view", "List"),
                "color": sc.get("color", "Blue"),
                "stats_filter": sc.get("stats_filter", "{}"),
            })

        content_blocks.append({"id": "spc_main", "type": "spacer", "data": {"col": 12}})
        content_blocks.append({
            "id": "hdr_cards",
            "type": "header",
            "data": {"text": '<span class="h4"><b>ERP Modules & Masters</b></span>', "col": 12},
        })

        ws_links: List[Dict[str, Any]] = []
        for c_idx, card in enumerate(cards):
            card_title = card["title"]
            content_blocks.append({
                "id": f"crd_{c_idx}_{card_title[:8].replace(' ', '_')}",
                "type": "card",
                "data": {"card_name": card_title, "col": 4},
            })
            ws_links.append({
                "label": card_title,
                "type": "Card Break",
                "hidden": 0,
            })
            for item_dt in card["doctypes"]:
                ws_links.append({
                    "label": item_dt,
                    "type": "Link",
                    "link_type": "DocType",
                    "link_to": item_dt,
                    "hidden": 0,
                })

        if frappe.db.exists("Workspace", ws_name):
            ws_doc = frappe.get_doc("Workspace", ws_name)
            ws_doc.title = title
            ws_doc.icon = icon
            ws_doc.sequence_id = seq
            ws_doc.public = 1
            ws_doc.is_hidden = 0
            ws_doc.module = "EXRP"
            ws_doc.content = json.dumps(content_blocks)
            ws_doc.set("shortcuts", ws_shortcuts)
            ws_doc.set("links", ws_links)
            ws_doc.save(ignore_permissions=True)
        else:
            ws_doc = frappe.get_doc({
                "doctype": "Workspace",
                "name": ws_name,
                "label": ws_name,
                "title": title,
                "icon": icon,
                "sequence_id": seq,
                "public": 1,
                "is_hidden": 0,
                "module": "EXRP",
                "content": json.dumps(content_blocks),
                "shortcuts": ws_shortcuts,
                "links": ws_links,
            })
            ws_doc.insert(ignore_permissions=True)

    _upsert_workspace(
        ws_name="EXRP Enterprise ERP",
        title="EXRP Enterprise ERP",
        icon="organization",
        seq=0.1,
        shortcuts=[
            {"label": "Sales Orders", "link_to": "Sales Order", "color": "Blue"},
            {"label": "Purchase Orders", "link_to": "Purchase Order", "color": "Orange"},
            {"label": "Customers", "link_to": "Customer", "color": "Green"},
            {"label": "Sales Invoices", "link_to": "Sales Invoice", "color": "Red"},
            {"label": "Work Orders", "link_to": "Work Order", "color": "Yellow"},
            {"label": "Support Issues", "link_to": "Issue", "color": "Pink"},
            {"label": "Inventory Items", "link_to": "Item", "color": "Cyan"},
            {"label": "EXRP Settings", "link_to": "EXRP Settings", "doc_view": "", "color": "Grey"},
        ],
        cards=[
            {"title": "Selling and CRM", "doctypes": ["Sales Order", "Quotation", "Delivery Note", "Customer", "Opportunity", "Lead"]},
            {"title": "Buying and Procurement", "doctypes": ["Purchase Order", "Material Request", "Purchase Receipt", "Supplier"]},
            {"title": "Inventory and Stock", "doctypes": ["Item", "Warehouse", "Stock Ledger Entry"]},
            {"title": "Manufacturing and Production", "doctypes": ["Work Order", "BOM"]},
            {"title": "Accounting and Finance", "doctypes": ["Sales Invoice", "Payment Entry", "GL Entry"]},
            {"title": "HR and Projects", "doctypes": ["Employee", "Expense Claim", "Project"]},
            {"title": "Support and Helpdesk", "doctypes": ["Issue", "Warranty Claim"]},
            {"title": "Settings and Administration", "doctypes": ["EXRP Settings", "Custom Field", "Property Setter", "Workflow", "Report", "User", "Role"]},
        ],
    )

    _upsert_workspace(
        ws_name="Selling and CRM",
        title="Selling and CRM",
        icon="retail",
        seq=0.2,
        shortcuts=[
            {"label": "Sales Order", "link_to": "Sales Order", "color": "Blue"},
            {"label": "Quotation", "link_to": "Quotation", "color": "Cyan"},
            {"label": "Delivery Note", "link_to": "Delivery Note", "color": "Green"},
            {"label": "Customer", "link_to": "Customer", "color": "Orange"},
        ],
        cards=[
            {"title": "Sales Transactions", "doctypes": ["Sales Order", "Quotation", "Delivery Note"]},
            {"title": "CRM Pipeline", "doctypes": ["Lead", "Opportunity", "Customer"]},
        ],
    )

    _upsert_workspace(
        ws_name="Buying and Procurement",
        title="Buying and Procurement",
        icon="buying",
        seq=0.3,
        shortcuts=[
            {"label": "Purchase Order", "link_to": "Purchase Order", "color": "Orange"},
            {"label": "Material Request", "link_to": "Material Request", "color": "Yellow"},
            {"label": "Purchase Receipt", "link_to": "Purchase Receipt", "color": "Green"},
            {"label": "Supplier", "link_to": "Supplier", "color": "Blue"},
        ],
        cards=[
            {"title": "Procurement Cycle", "doctypes": ["Material Request", "Purchase Order", "Purchase Receipt", "Supplier"]},
        ],
    )

    _upsert_workspace(
        ws_name="Inventory and Stock",
        title="Inventory and Stock",
        icon="stock",
        seq=0.4,
        shortcuts=[
            {"label": "Item", "link_to": "Item", "color": "Cyan"},
            {"label": "Warehouse", "link_to": "Warehouse", "color": "Blue"},
            {"label": "Stock Ledger Entry", "link_to": "Stock Ledger Entry", "color": "Grey"},
        ],
        cards=[
            {"title": "Stock and Warehouses", "doctypes": ["Item", "Warehouse", "Stock Ledger Entry"]},
        ],
    )

    _upsert_workspace(
        ws_name="Manufacturing and Production",
        title="Manufacturing and Production",
        icon="tool",
        seq=0.5,
        shortcuts=[
            {"label": "Work Order", "link_to": "Work Order", "color": "Orange"},
            {"label": "BOM", "link_to": "BOM", "color": "Green"},
        ],
        cards=[
            {"title": "Production Control", "doctypes": ["Work Order", "BOM", "Item", "Warehouse"]},
        ],
    )

    _upsert_workspace(
        ws_name="Accounting and Finance",
        title="Accounting and Finance",
        icon="accounting",
        seq=0.6,
        shortcuts=[
            {"label": "Sales Invoice", "link_to": "Sales Invoice", "color": "Red"},
            {"label": "Payment Entry", "link_to": "Payment Entry", "color": "Green"},
            {"label": "GL Entry", "link_to": "GL Entry", "color": "Grey"},
        ],
        cards=[
            {"title": "Ledgers and Billing", "doctypes": ["Sales Invoice", "Payment Entry", "GL Entry"]},
        ],
    )

    _upsert_workspace(
        ws_name="HR and Projects",
        title="HR and Projects",
        icon="hr",
        seq=0.7,
        shortcuts=[
            {"label": "Employee", "link_to": "Employee", "color": "Blue"},
            {"label": "Expense Claim", "link_to": "Expense Claim", "color": "Orange"},
            {"label": "Project", "link_to": "Project", "color": "Green"},
        ],
        cards=[
            {"title": "People and Delivery", "doctypes": ["Employee", "Expense Claim", "Project"]},
        ],
    )

    _upsert_workspace(
        ws_name="Support and Helpdesk",
        title="Support and Helpdesk",
        icon="support",
        seq=0.8,
        shortcuts=[
            {"label": "Support Issues", "link_to": "Issue", "color": "Red"},
            {"label": "Warranty Claims", "link_to": "Warranty Claim", "color": "Orange"},
        ],
        cards=[
            {"title": "Customer Support", "doctypes": ["Issue", "Warranty Claim", "Customer"]},
        ],
    )

    _upsert_workspace(
        ws_name="Settings and Administration",
        title="Settings and Administration",
        icon="setting-gear",
        seq=0.9,
        shortcuts=[
            {"label": "EXRP Settings", "link_to": "EXRP Settings", "doc_view": "", "color": "Blue"},
            {"label": "System Settings", "link_to": "System Settings", "doc_view": "", "color": "Grey"},
            {"label": "Users", "link_to": "User", "color": "Green"},
            {"label": "Roles", "link_to": "Role", "color": "Orange"},
            {"label": "Print Settings", "link_to": "Print Settings", "doc_view": "", "color": "Yellow"},
            {"label": "Email Accounts", "link_to": "Email Account", "color": "Cyan"},
        ],
        cards=[
            {"title": "AI Control Plane", "doctypes": ["EXRP Settings", "Custom Field", "Property Setter", "Workflow", "Report"]},
            {"title": "System and Security", "doctypes": ["System Settings", "User", "Role", "Email Account", "Print Settings"]},
        ],
    )

    # 25. Apply EXRP Official Brand and Logo Settings
    try:
        navbar_settings = frappe.get_single("Navbar Settings")
        navbar_settings.app_logo = "/assets/exrp/images/exrp-logo.svg"
        navbar_settings.save(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error updating Navbar Settings logo: {e}")

    try:
        website_settings = frappe.get_single("Website Settings")
        website_settings.app_logo = "/assets/exrp/images/exrp-logo.svg"
        website_settings.splash_image = "/assets/exrp/images/exrp-logo.svg"
        website_settings.favicon = "/assets/exrp/images/favicon.svg"
        website_settings.brand_html = '<img src="/assets/exrp/images/exrp-logo.svg" style="height: 28px;" alt="EXRP">'
        website_settings.save(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Error updating Website Settings logo: {e}")

    frappe.db.commit()

    # Collect total counts per DocType for reporting
    summary_counts = {}
    for spec in doctype_specs:
        dt = spec["name"]
        summary_counts[dt] = frappe.db.count(dt)

    return {
        "created_roles": created_roles,
        "created_doctypes": created_doctypes,
        "seeded_records_count": len(seeded_records),
        "doctype_counts": summary_counts,
        "workspaces": [
            "EXRP Enterprise ERP",
            "Selling and CRM",
            "Buying and Procurement",
            "Inventory and Stock",
            "Manufacturing and Production",
            "Accounting and Finance",
            "HR and Projects",
            "Support and Helpdesk",
            "Settings and Administration",
        ],
    }
