# PRD: EXRP Conversational Customization Engine (v1)
**Status**: Approved for Implementation  
**Author**: Alex (Product Manager) & Software Architect  
**Version**: 1.0  

---

## 1. Problem Statement & Product Thesis
Mid-market operations and revenue teams outgrow static CRM/ERP forms weekly, yet customizing ERPNext typically requires a technical administrator who understands DocTypes, Custom Fields, Property Setters, and Workflows—plus the risk of breaking live forms or accounting rules.

**EXRP** embeds an **AI Architect Sidecar** directly inside the ERP workspace. Non-technical users describe how their business works in plain language, inspect an **instant, zero-downtime live preview**, and publish validated declarative customizations with 1-click rollback and strict accounting guardrails.

---

## 2. Goals & Success Metrics
| Goal | Metric | Baseline | v1 Target |
| :--- | :--- | :--- | :--- |
| **Zero-Latency Preview** | Time from LLM response to interactive form preview | N/A | **< 100ms** (Virtual JSON Merge, 0 DB DDL) |
| **Zero-Downtime Publish** | Table lock duration when publishing new fields/layouts | Synchronous `ALTER TABLE` | **0ms lock** (`Property Setter` + MariaDB `ALGORITHM=INSTANT` nullable columns) |
| **Safe Reversibility** | Time to revert a published customization | Manual DB cleanup | **< 1 second** (1-click Soft-Undo via `hidden=1`) |
| **Compliance Integrity** | Unauthorized AI edits to Zone 2 Accounting Ledger | N/A | **0 permitted** (100% intercepted by guardrails) |

---

## 3. Explicit Non-Goals for v1 (Protecting Scope)
1. **No Full Replacement of Frappe Desk**: We are not rewriting ERPNext's 50,000+ lines of client-side form scripts (`transaction.js`, `taxes_and_charges.js`). We embed our AI Sidecar and Virtual Preview Renderer directly into Frappe Desk / Frappe UI.
2. **No Arbitrary Code Generation (`Server Script` / `Client Script`)**: v1 is strictly constrained to **4 Declarative Primitives**:
   - `Custom Field` (Additive nullable fields)
   - `Property Setter` (Labels, visibility, mandatory rules, defaults, select options, layout order)
   - `Workflow` (Approval state machines & role-based transitions)
   - `Report` / Filter Views (Read-only filtered views)
3. **No Physical `DROP COLUMN` or Destructive DDL**: Field removal in v1 is strictly a soft-hide (`hidden = 1`, `reqd = 0`) to guarantee zero data loss and instant rollback.

---

## 4. End-to-End User Experience Flow

1. **Contextual Prompt**: User opens a `Delivery Note` or `Opportunity` in Frappe Desk, opens the EXRP AI Sidecar, and types: *"Add Container Number (required) and Customs Status (Pending, In Inspection, Cleared, Held)."*
2. **0ms Virtual Preview**:
   - Backend calls `exrp.api.control_plane.propose_change(doctype, prompt)`.
   - Validates Zone 1 compliance and additive-only rules.
   - Merges `[Base DocType Meta + Draft Operations]` in memory (`virtual_merger.py`).
   - Desk UI renders the previewed fields in-place with a `[PREVIEW]` badge—zero database DDL executed.
3. **Instant Publish**:
   - User clicks **"Publish Changes"**.
   - Backend writes `Custom Field` (MariaDB `ALGORITHM=INSTANT`) and `Property Setter` rows, clears DocType cache, and stores an `EXRP Change Audit` snapshot.
4. **1-Click Undo**:
   - User can click **"Revert"** at any time to restore prior `Property Setter` states and soft-hide (`hidden = 1, reqd = 0`) added fields.
