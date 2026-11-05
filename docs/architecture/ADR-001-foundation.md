# ADR-001 (Rev 2.3): EXRP Foundation — Frappe-Native Configuration Control Plane, Guarded Schema Deployment, and Explicit Trust Boundaries

- **Status:** Accepted (Empirically Verified by POC-001)
- **Empirical Verification Report:** [POC-001: Empirical Verification & Release-Gate Report](./POC-001-empirical-evidence.md)
- **Date:** 2026-11-04 (Updated 2026-11-05 for Phases 1–4 Implementation)
- **Supersedes:** ADR-001 Rev 2.2
- **Scope:** Architecture foundation and Phases 1–4 implementation (Custom Fields, Property Setters, Workflows, Report Builder, Cross-Document Policies, and 1-Click Rollback/Quarantine); companion ADRs specify granular contracts
- **Decision owners:** EXRP engineering and product owners (Approved based on POC-001 exit criteria)

## 1. Context

EXRP is an AI-assisted configuration control plane for Frappe/ERPNext. Authorized non-technical business operators describe operational needs in natural language; EXRP proposes structured, reviewable configuration changes across four declarative primitives: custom fields (`Custom Field`), form layouts and field properties (`Property Setter`), multi-stage approval state machines (`Workflow`), and filtered analytical views (`Report` with `Report Builder` JSON). It must not expose arbitrary SQL, Python, or JavaScript execution to conversational users, nor bypass ERPNext's accounting and authorization controls.

The architecture must preserve stock Frappe/ERPNext, support safe previews, provide traceable publishing and recovery, and avoid treating database schema changes as atomic or interference-free. **An AI-generated proposal is untrusted input until validated and explicitly authorized. Business transactions must remain correct independently of the AI.**

### 1.1 Non-negotiable distinctions

1. **Preview:** inspect a proposed configuration without changing production metadata, schema, or cached metadata.
2. **Publishing:** authorize and deploy a validated revision using the native framework's supported configuration mechanisms, with observable failure states.
3. **Runtime enforcement:** apply supported business and cross-document policies to Frappe Document lifecycle write paths, without claiming that hooks constrain privileged SQL or unrelated installed code.
4. **Schema changes:** a request to add one field does **not** imply that Frappe's DocType schema synchronizer will execute only one `ADD COLUMN`; the entire generated schema diff must be considered.

## 2. Decision Summary

1. Implement `exrp` as a **standalone Frappe application**, without forking ERPNext or replacing its transactional controllers.
2. Target **Frappe/ERPNext version-15** only for the initial release; pin tested dependency versions and commit SHAs. Treat future v16 compatibility as a separate workstream, not a property of `compat.py` alone.
3. Provide a conversational **Desk sidecar** with an **isolated, request-scoped configuration preview** (in-place DOM preview for fields/properties, Mermaid state-machine graphs for workflows, and virtual read-only data tables for reports). Do not override global `frappe.get_meta()` or production metadata caches for drafts.
4. Accept only a **versioned declarative configuration DSL**; validate with a deterministic compiler, an operation allowlist, an impact classifier, and role-based publication authority.
5. Use native `Custom Field`, `Property Setter`, `Workflow`, and `Report` (`Report Builder` JSON) documents as the authoritative **persisted configuration**. EXRP never issues ad hoc independent `ALTER TABLE` statements to create its own competing schema authority.
6. **Gate synchronous physical field creation on a proven approved-only DDL plan and observed locking behavior.** Complex diffs, multi-field mutations, or index modifications are blocked from synchronous execution and routed to controlled administrative deployment (`QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT`).
7. Restrict synchronous physical schema changes to **one physical field per deployment unit**, alongside metadata-only `Property Setter` changes, validated `Workflow` state machines, and read-only `Report Builder` definitions on permitted DocTypes. Multi-field user requests consist of independently tracked units and are not atomic.
8. Use a unified durable deployment audit journal (`tabEXRP Deployment Audit`), immutable idempotency bindings, a DB-connection-scoped advisory lock, before/after snapshots, and **non-destructive reconciliation**. Uncertain outcomes enter `RECOVERY_REQUIRED` rather than being automatically declared safe.
9. Explicitly separate schema-policy protection, business-policy governance, and normal data editing. Do not interpret a protected business field as unwritable by authorized ERPNext users.
10. Anchor production reliability claims on the satisfied exit criteria of the three empirical PoC suites in §11, documented in [POC-001](./POC-001-empirical-evidence.md).

## 3. Supported Stack and Installation Boundary

| Component | Verified Specification (POC-001 Baseline) |
|---|---|
| Frappe / ERPNext | Frappe `v15.126.0`, ERPNext `v15.124.5` (pinned commit `7b471053e3`) |
| Python | `3.12.16` (host test runner) / `3.11.14` (Frappe bench container runtime) |
| Node.js | `20 LTS` (Desk asset bundling and syntax verification) |
| MariaDB | `10.6.28 / 10.11 LTS` (InnoDB online DDL & metadata locking verified) |
| Redis | `7.2.4-alpine` (cache `12000`, queue `11000`) |
| Packaging | Frappe custom app installed per site with `bench get-app` / `bench install-app` |
| UI | Existing Frappe Desk / ERPNext forms plus isolated AI Copilot sidecar |

The version matrix above is empirically verified and recorded in [POC-001](./POC-001-empirical-evidence.md) §2. A separate future compatibility matrix may target v16 with its own supported Python/Node/MariaDB requirements.

**Operational authority:** EXRP can authorize changes through its own control plane, but stock administrative interfaces and privileged code may still alter Frappe metadata. The deployment service must detect such external changes and fail on revision conflicts; a named lock does not lock non-cooperating actors.

## 4. Architecture and Trust Boundaries

```text
Operator / Approver (Frappe-authenticated, RBAC)
                   |
             Desk AI sidecar
                   |
          Untrusted AI planner
                   |
        Typed declarative proposal
                   |
     Deterministic compiler + RBAC +
        protected-invariant registry
                   |
       Isolated preview / impact review
                   |
        Explicit human authorization
                   |
     Durable deployment + reconciliation
                   |
      Native Frappe metadata + schema
                   |
       ERPNext business transactions
      [native controllers + permitted
        EXRP Document lifecycle hooks]

Privileged SQL / bench console / other apps are outside the
Document-hook enforcement boundary and need operational controls.
```

### 4.1 Configuration preview

- Read **effective** DocType metadata via the supported Frappe metadata API on the pinned version, including existing customization.
- Clone it for a **request-scoped** proposed view; apply the structured delta to the clone only.
- Render isolated UI previews in the Desk sidecar and form DOM without mutating `cur_frm.doc`, marking the document dirty, or globally caching draft metadata.
- Disclose preview fidelity: field structure, labels, order, basic controls, workflow state-machine graphs, and virtual report sample rows are rendered; full ERPNext pricing/tax client controllers, custom scripts, and server-side accounting validation are **not simulated**.
- Do not use a preview to imply that the production record will pass submit-time validation.

### 4.2 Runtime policy enforcement

For explicitly supported single-document (`RuntimePolicyCatalog` in `policy_enforcer.py`) and cross-document (`CrossDocPolicyCatalog` in `cross_doc_policy.py`) policies, use Frappe Document lifecycle hooks (`validate`, `before_submit`, `before_update_after_submit`) registered via `hooks.py`. Confirm behavior for new, amended, cancelled, and submitted documents as applicable.

The guarantee covers Desk, REST Document API, and background jobs **when they use the supported Document lifecycle**. `frappe.db.set_value`, bulk DB updates, raw SQL, privileged app code, and direct DB access may bypass these hooks. Do not claim that blocking AI-generated code blocks all privileged write paths. Control administrative permissions, app installation, server scripts, and DB credentials separately.

### 4.3 AI planner token compaction and timeout guardrails

- **Token-Compact Schema Extraction (`schema_extractor.py`):** Rather than injecting raw 15,000+ token Frappe DocType JSON definitions into LLM prompts, `get_compact_doctype_schema(doctype)` strips UI layout noise (`Column Break`, `Section Break`, print settings, permissions matrices) and emits only essential field metadata (`fieldname`, `label`, `fieldtype`, `options`, `reqd`, `is_custom`), keeping prompt context under ~1,500 tokens per turn.
- **Bounded HTTP Timeouts & Fast Model Fallback (`planner.py`):** To prevent LLM rate limits (HTTP 429) or upstream latency from stalling Gunicorn web workers past their 120-second worker timeout, `AIConfigurationPlanner` configures `HttpOptions(timeout=12000, retry_options=HttpRetryOptions(attempts=1))` with SDK internal sleep-backoff disabled (`max_retries = 0`). On HTTP `429`/`503`/`404`, the planner immediately cascades through fallback models (`gemini-3.8-flash` -> `gemini-3.5-flash-lite` -> `gemini-3-flash-preview`) and deterministic schema-valid fallback synthesis.
- **Credential Hygiene:** `resolve_llm_config()` and `test_llm_connection()` filter out Frappe client-side masked password placeholders (`*` / `•`) via `_is_masked_password()`, resolving the encrypted key exclusively from `EXRP Settings.get_password("api_key")` or environment variables.

## 5. Declarative Configuration and Policy Model

The AI outputs a versioned, schema-validated **proposal** (`ConfigurationProposal` supporting `add_custom_fields`, `set_property`, `create_workflow`, and `create_report`), not executable code. The compiler resolves DocTypes and canonical field paths from installed metadata, expands references to child tables, rejects unknown operations and properties, and applies two independent classifications:

### 5.1 Technical storage impact

| Technical/storage impact | Examples | Operational disposition |
|---|---|---|
| `METADATA_ONLY` | `Property Setter` labels/descriptions/reqd, `Workflow` state machines, `Report Builder` definitions | Allowed after policy, graph, or operator allowlist checks |
| `ONLINE_ADDITIVE_DDL` | Valid single new physical nullable `Custom Field` | Conditional: §6 DDL Plan Inspection Gate |
| `DATA_SEMANTIC` | Option removals, type conversions, retroactive mandatory constraints | Restricted; blocked unless explicitly allowlisted |
| `DESTRUCTIVE_DDL` | Drop column, shrink length, type replacement, unsafe index/unique changes | Prohibited conversationally |

### 5.2 Governance tiers

| Governance tier | Effect |
|---|---|
| **Tier 0 — Protected ERP invariants** | EXRP cannot weaken or alter protected financial/security definitions (`GL Entry`, `Stock Ledger Entry`, `Sales Invoice`, `EXRP Settings`, `Sales Order Item.rate`, `bypass_credit_limit_check`), regardless of role. |
| **Tier 1 — Governed business configuration** | EXRP-created approval thresholds, workflows, and policies may be deployed, tightened, **or relaxed** with explicit `AUTHORIZED_DEPLOYMENT_ROLES` approval, provided Tier 0 remains intact. |
| **Tier 2 — Delegated configuration** | Authorized operators may add safe optional fields, make low-impact presentation changes, and publish `Report Builder` views. |

**Protected means protected against EXRP configuration mutations**. It does not automatically prohibit users from editing ordinary business values (e.g., `Sales Order Item.rate`) under ERPNext's native permissions. Maintain a versioned, tested registry keyed by `(DocType, field path, mutation operation)` in `safety_guardrails.py`; validate actual parent/child DocType relationships from installed metadata rather than assuming that all similar field names occur on the same DocType. A field registry does not replace native accounting validations.

### 5.3 Additive-field and primitive restrictions

- One new physical field per deployment unit; nullable, non-unique, no index creation, no arbitrary code or expression, no `allow_on_submit` or `is_virtual` unless separately supported. Single DocTypes (`issingle = 1`, which have no physical `tab<DocType>` table) are blocked from physical DDL generation.
- Canonical fieldname convention: `^custom_[a-z][a-z0-9_]{1,50}$`; verified against the pinned Frappe/MariaDB stack.
- Permit only the explicitly tested `PHASE_1_ALLOWED_FIELDTYPES` allowlist (`Data`, `Check`, `Int`, `Float`, `Date`, `Datetime`, `Select`, `Link`).
- Validate `Select` choices, duplicates, defaults, and Frappe's expected serialization; validate that a `Link` target resolves to an allowed existing DocType.
- Reject target collisions in **effective metadata and the physical table**, including inconsistent pre-existing states.
- For `Report Builder` (`report_engine.py`), prohibit system DocTypes (`PROHIBITED_REPORT_DOCTYPES`: `User`, `Role`, `DocType`, `Custom Field`, `Property Setter`, `Workflow`, `GL Entry`, `Stock Ledger Entry`) and enforce strict filter operator whitelisting (`ALLOWED_OPERATORS`: `=`, `!=`, `>`, `<`, `>=`, `<=`, `like`, `not like`, `in`, `not in`, `between`, `is`) and `^[a-zA-Z0-9_]+$` fieldname validation to prevent SQL injection.

## 6. Schema-Change Safety Gate — Key Architecture Constraint

**A Frappe `Custom Field` insertion triggers `frappe.db.updatedb(doctype)`. The synchronizer (`MariaDBTable`) inspects the entire DocType against `information_schema.columns` and may alter other columns or indexes to reconcile pre-existing drift, and its generated `ALTER TABLE` statements do not append `ALGORITHM=INSTANT, LOCK=NONE`.** Consequently `len(changes) == 1` in EXRP's DSL is *not* sufficient to prove the physical execution is additive-only.

### 6.1 Verified DDL plan inspection contract

Synchronous physical field publishing is gated by the version-pinned inspection gate (`inspect_frappe_ddl_plan` in `ddl_plan_gate.py`), which enforces four invariants before any schema write occurs:

1. **Exact SQL Diff Capture:** Computes the exact SQL operations Frappe's `MariaDBTable` would issue against the current table schema and proposed effective metadata (using thread-local `frappe.local.db.sql_ddl` interception under the site advisory lock when inside Frappe, or the deterministic pure-Python column/index diff simulator). Single DocTypes (`issingle = 1`) are detected and blocked from DDL inspection.
2. **Strict Additive-Only Regex Enforcement (`APPROVED_DDL_REGEX`):** Approves the plan **only if** `len(statements) == 1` and the single statement matches:
   `^ALTER TABLE \`tab[A-Za-z0-9_ ]+\` ADD COLUMN \`custom_[a-z][a-z0-9_]{1,50}\` [A-Za-z0-9_(), ']+$`
   Any `MODIFY COLUMN`, `CHANGE COLUMN`, `DROP`, `ADD INDEX`, or `ADD UNIQUE` statement is immediately rejected.
3. **Storage & Instant-DDL Operational Boundary:** Because stock Frappe v15 emits plain `ALTER TABLE ... ADD COLUMN` without an explicit `ALGORITHM=INSTANT` clause, MariaDB InnoDB executes nullable trailing column additions instantaneously under default `DYNAMIC` row format unless the table has exhausted instant metadata slots or uses `COMPRESSED`/`REDUNDANT` row formats.
4. **Observable Post-Apply Verification:** Stage 5 (`Reconcile`) verifies that the post-apply schema matches the approved plan and sets `RECOVERY_REQUIRED` if any unapproved side effect occurred.

### 6.2 Routing for rejected or multi-statement DDL plans

When `inspect_frappe_ddl_plan` detects multiple statements, an unrelated column `MODIFY` diff, index creation, or an unprovable plan:

- **Synchronous web-worker execution is blocked immediately** (`is_approved_additive_only = False`).
- The deployment attempt is recorded in `tabEXRP Deployment Audit` with `status = "REJECTED"`, `disposition = "QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT"`, and the captured `ddl_plan_statements` JSON array.
- Instant conversational **proposal and preview** and metadata-only operations (`Property Setter`, `Workflow`, `Report Builder`) remain available.
- Queued schema changes are surfaced to `System Manager` administrators for scheduled maintenance-window execution (`bench --site <site> migrate`) under explicit advisory lock coordination. EXRP never circumvents Frappe with ad hoc raw-DDL execution.

### 6.3 MariaDB locking and concurrency controls

- MariaDB DDL implicitly commits the active transaction even when a statement fails; cross-step transactional rollback cannot be assumed.
- Metadata locks (MDL) queue `ALTER TABLE` behind active transactions on the target table, and a queued `ALTER TABLE` blocks subsequent reads and writes on that table until the DDL completes or times out.
- EXRP enforces `SET SESSION lock_wait_timeout = 3` prior to Stage 4 (`Apply`). In [POC-001](./POC-001-empirical-evidence.md) §4.2–4.3, this bounded metadata lock contention to **3.023 seconds** (aborting with MariaDB Error `1205`), with concurrent user read latency measured at **p50 = 1,248 ms**, **p95 = 2,664 ms** during the 3-second window, recovering to **0.58 ms** immediately after timeout abort, and **615 ms** total execution time on an uncontended table.
- When DDL commits on a table, MariaDB invalidates the table definition cache across connections, which can raise MariaDB Error `1412` (`Table definition has changed, please retry transaction`) on concurrent long-running transactions touching the same table; web workers retry transient read transactions or execute physical schema additions during low-contention windows.

**Service-level claim:** no *planned* application restart for supported customization; bounded 3-second metadata lock wait via `lock_wait_timeout = 3`.

## 7. Deployment Identity, Lock Ownership, and Idempotency

### 7.1 Durable records (`tabEXRP Deployment Audit`)

To prevent multi-table write skew prior to implicitly committing DDL, EXRP persists deployment intent, field provenance, baseline snapshots, and audit state in a single unified InnoDB journal table: **`tabEXRP Deployment Audit`** (with standalone fallback `exrp_deployment_journal`):

- **Schema Columns:** `name` (PK), `deployment_id` (Unique), `idempotency_key` (Unique), `payload_hash` (SHA-256 of canonical JSON payload), `site_id`, `doctype`, `fieldname`, `base_revision_hash`, `ddl_plan_statements` (JSON), `status`, `outcome_json` (JSON containing `disposition`, `baseline_snapshot`, `mutation_type`, `workflow_def` / `report_def` / `property_setter`, and `execution_time_ms`), `created_at`, and `updated_at`.
- **Idempotency Contract:** A retry with the **same `idempotency_key` and identical `payload_hash`** returns the existing verified outcome after reconciliation. A retry with the same `idempotency_key` and a different `payload_hash` raises `IdempotencyConflictError` (`IDEMPOTENCY_CONFLICT`) and never reapplies a mutation.
- **Provenance Boundary:** The `outcome_json` provenance record establishes EXRP creation intent and baseline snapshots for `execute_rollback()`, but does not prevent privileged actors outside EXRP from modifying metadata directly. Automatic destructive column dropping is disabled.

### 7.2 Advisory-lock contract

- **Bounded Lock Key Formula (`make_bounded_lock_key`):** Site and DocType names are mapped deterministically to a 56-character string (strictly within MariaDB's 64-character `GET_LOCK` limit) via:
  `exrp:v1:<sha256(f"{site_id}\x00{doctype}").hexdigest()[:48]>`
- **Single-Connection Ownership:** Acquire `SELECT GET_LOCK(lock_key, wait_seconds)` on the active database connection; verify return value `1`, and treat `0` (timeout) or `NULL` (error) as an immediate Stage 1 `REJECTED` outcome. As verified in [POC-001](./POC-001-empirical-evidence.md) §4.1, holding the advisory lock on the single verified connection ensures that an unexpected connection drop releases the lock within **0.5 ms**, whereas normal completion explicitly calls `SELECT RELEASE_LOCK(lock_key)` in the `finally` block.
- **Revision Conflict Detection:** MariaDB named locks are advisory and **do not block Frappe Customize Form or privileged writers** that do not cooperate. EXRP checks `base_revision_hash` before application and during Stage 5 reconciliation; any external modification triggers `REVISION_CONFLICT` or `RECOVERY_REQUIRED`.

## 8. Durable Deployment Sequence and Failure Semantics

Each physical field mutation runs as a separately auditable 6-stage unit (`execute_single_field_deployment` in `schema_reconciler.py`):

| Stage | Required action | Failure response |
|---|---|---|
| **1. Acquire** | Obtain verified site/DocType advisory lock (`GET_LOCK`) under single-connection ownership | `REJECTED` (`stage: ACQUIRE`) / lock failure; no mutation |
| **2. Inspect** | Check target identity, `base_revision_hash`, metadata/physical schema snapshots, and `inspect_frappe_ddl_plan` | `REJECTED` (`QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT`), `REVISION_CONFLICT`, or `RECOVERY_REQUIRED` |
| **3. Prepare** | Commit immutable deployment intent (`PREPARED`), `payload_hash`, `ddl_plan_statements`, and baseline snapshot to `tabEXRP Deployment Audit` **before mutation** | **Fail closed** (`REJECTED`, `stage: PREPARE_AUDIT`) before schema write |
| **4. Apply** | Set `SET SESSION lock_wait_timeout = 3` and execute native Frappe configuration operation (`frappe.get_doc(Custom Field).insert()`) | On exception (e.g. Error `1205`), do **not** assume rollback; continue to Stage 5 reconciliation |
| **5. Reconcile** | Compare observed `tabCustom Field` metadata, `information_schema.columns` state, indexes, and `base_revision_hash` against expected snapshot | Classify into `APPLIED`, `FAILED_CLEAN`, or `RECOVERY_REQUIRED` |
| **6. Finalize** | Persist terminal `status` and `disposition` in `tabEXRP Deployment Audit`; clear DocType cache; release `GET_LOCK` in `finally` | If finalization fails, preserve `RECOVERY_REQUIRED` journal for recovery |

Durable intent is committed **before** potentially implicitly committing DDL. Do not depend on an outer request transaction to roll back metadata and DDL together.

### 8.1 Status vocabulary

`PROPOSED`, `VALIDATED`, `PREPARED`, `APPLYING`, `VERIFYING`, `APPLIED`, `REJECTED`, `REVISION_CONFLICT`, `FAILED_CLEAN`, `RECOVERY_REQUIRED`, `QUARANTINED`, `ROLLED_BACK`.

Only `APPLIED` means the **approved** configuration and physical state were verified. `FAILED_CLEAN` means no unauthorized change remains and the baseline is verified. `ROLLED_BACK` means a reversible metadata mutation (`Property Setter`, `Workflow`, or `Report`) was restored to its pre-deployment baseline snapshot. `QUARANTINED` means an EXRP-created `Custom Field` was soft-hidden (`hidden = 1, reqd = 0`) without dropping the physical column. `RECOVERY_REQUIRED` blocks further EXRP deployments for the affected target until reconciled.

### 8.2 Crash recovery

On startup or scheduled reconciliation, scan nonterminal deployment intents (`PREPARED`, `APPLYING`, `VERIFYING`); re-observe metadata, schema, indexes, and revision identity; classify the resulting state using the §9 reconciliation matrix. **Never blindly replay native DDL based only on the last recorded status.**

## 9. Exhaustive Snapshot Reconciliation

A snapshot (`ExhaustiveSnapshot` in `schema_reconciler.py`) captures `Custom Field` record existence and properties, physical column existence/type/length/nullability/default from `information_schema.columns`, index state, DocType metadata revision hash, and EXRP provenance:

| Metadata (`tabCustom Field`) | Physical column (`information_schema`) | Other observations | Terminal Status | Disposition Code (`outcome_json.disposition`) |
|---|---|---|---|---|
| Absent | Absent | Baseline unchanged, no partial side effects | `FAILED_CLEAN` | `ABSENT_ABSENT_BASELINE_VERIFIED` |
| Present | Present | Expected definition, indexes, and provenance; no unapproved effects | `APPLIED` | `VERIFIED_CONSISTENT` |
| Present | Present | Definition mismatch or unexpected index/column side effect | `RECOVERY_REQUIRED` | `DEFINITION_MISMATCH_OR_UNAPPROVED_SIDE_EFFECT` |
| Present | Absent | Orphan metadata record without physical column | `RECOVERY_REQUIRED` | `ORPHAN_METADATA_NON_DESTRUCTIVE_HOLD` |
| Absent | Present | Orphan physical column without metadata record | `RECOVERY_REQUIRED` | `ORPHAN_PHYSICAL_COLUMN` |
| Present | Present | Definition matches but provenance or concurrent revision is uncertain | `RECOVERY_REQUIRED` | `UNCERTAIN_PROVENANCE_OR_CONCURRENT_REVISION` |

**EXRP deliberately does not auto-delete orphaned `Custom Field` metadata or drop physical columns during conversational execution.** Recovery is non-destructive. To prevent long-term schema bloat or namespace exhaustion from quarantined fields, administrators can decommission quarantined fields offline during scheduled maintenance windows after verifying zero non-null historical data.

### 9.1 Configuration rollback and quarantine (`rollback_engine.py`)

EXRP provides a role-gated 1-click configuration rollback engine (`execute_rollback` / `revert_configuration_change`) restricted to `AUTHORIZED_ROLLBACK_ROLES` (`System Manager`, `Finance Director`, `Operations Director`):

- **Reversible Metadata (`Property Setter`):** Restores the exact baseline property value captured in `tabEXRP Deployment Audit` prior to mutation (or deletes the `Property Setter` if none existed previously), transitioning status to `ROLLED_BACK` (`PROPERTY_SETTER_RESTORED` / `PROPERTY_SETTER_REMOVED`).
- **Quarantinable Physical Schema (`Custom Field`):** Because dropping physical columns risks irreversible data loss and table locks, rolling back a `Custom Field` applies a soft quarantine (`hidden = 1, reqd = 0`), preserving historical column data and transitioning status to `QUARANTINED` (`CUSTOM_FIELD_QUARANTINED_HIDDEN`).
- **Deactivatable State Machines & Reports (`Workflow` & `Report`):** Restores the previous active workflow baseline or sets `is_active = 0` (`WORKFLOW_DEACTIVATED` / `PREVIOUS_WORKFLOW_RESTORED`), and soft-disables reports via `disabled = 1` (`REPORT_DISABLED`), transitioning status to `ROLLED_BACK`.

EXRP does not perform automatic reversal of already-submitted ERPNext business transactions (`Sales Order`, `GL Entry`).

## 10. UI, Governance, and Audit Requirements

### 10.1 Preview, authorization roles, and input sanitization

- **Sidecar Preview Contract:** Present proposed target DocType (with an explicit DocType switcher and `Open ↗` navigation control in the sidecar header), exact field/workflow/report definitions, UI preview, risk tier badge, inspected SQL statement, and an explicit Approve/Deploy action.
- **Server-Side Role Authorization Matrix:**
  - *Proposal & Preview (`propose_configuration_change`):* Authenticated Desk operators (`System Manager`, `Finance Director`, `Operations Director`, `Sales Manager`, `Sales User`).
  - *Physical Schema, Property Setter, Workflow Deployment & Rollback (`AUTHORIZED_DEPLOYMENT_ROLES` / `AUTHORIZED_ROLLBACK_ROLES`):* Strictly restricted to `System Manager`, `Finance Director`, and `Operations Director`.
  - *Report Builder Deployment (`AUTHORIZED_REPORT_ROLES`):* Restricted to `System Manager`, `Finance Director`, `Operations Director`, and `Sales Manager`.
- **Prompt Injection & Presentation Sanitization:** Untrusted LLM output is validated against Pydantic models, regex fieldname constraints (`^custom_[a-z][a-z0-9_]{1,50}$`), and HTML/script sanitization before rendering in the Desk DOM or persisting to Frappe metadata.

### 10.2 Workflow and cross-document policy governance

- **Workflow State Machine Verification (`workflow_engine.py`):** Validates DocType allowlist (blocking Tier 0 DocTypes), enforces BFS graph reachability from initial `doc_status = 0` states, rejects dead-end non-terminal states, enforces Frappe `docstatus` transition invariants (`0 -> 1`, `1 -> 2`; prohibiting `1 -> 0`, `2 -> *`, and `0 -> 2`), and generates Mermaid state diagrams prior to publication.
- **Cross-Document Integrity Policies (`cross_doc_policy.py`):** Enforces multi-document referential invariants via `CrossDocPolicyCatalog` during `validate` and `before_submit` hooks, including `XDOC_DN_SO_MUST_BE_SUBMITTED` (`Delivery Note` requires linked `Sales Order` to have `docstatus == 1`), `XDOC_SI_SO_CANNOT_BE_CANCELLED` (`Sales Invoice` blocks submission if linked `Sales Order` has `docstatus == 2`), and `AMOUNT_CANNOT_EXCEED_LINKED`.

### 10.3 Audit durability

- Persist and commit deployment intent (`PREPARED`) in `tabEXRP Deployment Audit` before physical mutation (**fail closed**).
- Record final verification outcome and disposition code; failures after DDL are reconciled and recorded even if an exception occurs during `Apply`.
- Application-level hooks do not replace database-level access controls; restrict direct MariaDB root credentials and retain independent backups.

## 11. Empirical PoC Verification Summary (POC-001)

All three mandatory verification suites were executed against the pinned Frappe `v15.126.0` / ERPNext `v15.124.5` and MariaDB `10.6.28 / 10.11 LTS` stack (commit `7b471053e3`). Full logs, SQL traces, and latency percentiles are published in [POC-001: Empirical Verification & Release-Gate Report](./POC-001-empirical-evidence.md).

### 11.1 Suite A — Frappe schema synchronization, DDL gating, and reconciliation

1. Verified `Custom Field.on_update -> frappe.db.updatedb(dt) -> MariaDBTable.sync()` call chain in Frappe v15.
2. Verified non-executing DDL plan inspection (`inspect_frappe_ddl_plan` in `ddl_plan_gate.py`) enforcing `APPROVED_DDL_REGEX`.
3. Verified single-field addition (`custom_cargo_id`) emitting exact `ALTER TABLE \`tabSales Order\` ADD COLUMN \`custom_cargo_id\` varchar(140)` in **615 ms** (`status: APPLIED`, `disposition: VERIFIED_CONSISTENT`).
4. Verified rejection of unapproved `MODIFY COLUMN` drift and secondary index creation (`unique=1`, `search_index=1`), routing both to `QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT`.
5. Verified all 6 rows of the §9 Exhaustive Snapshot Reconciliation matrix (`FAILED_CLEAN`, `APPLIED`, and all 4 `RECOVERY_REQUIRED` dispositions) plus idempotency replay and `IdempotencyConflictError` rejection.

### 11.2 Suite B — MariaDB locks, connection loss, and user-traffic impact

1. Verified `GET_LOCK` mutual exclusion and connection-drop recovery: dropping the lock-holding connection released the MariaDB advisory lock in **0.5 ms** (`0.0005s`).
2. Verified metadata lock contention under `SET SESSION lock_wait_timeout = 3`: `ALTER TABLE` queued behind an active `SELECT ... FOR UPDATE` transaction aborted cleanly in **3.023 seconds** with MariaDB Error `1205` (`Lock wait timeout exceeded`).
3. Measured concurrent user read latency across staggered worker threads during MDL queueing: **Min = 0.58 ms**, **p50 = 1,248.12 ms**, **p95 = 2,664.28 ms**, **Max = 2,664.28 ms**, with post-abort read latency returning immediately to **0.58 ms**.
4. Verified end-to-end snapshot reconciliation under live lock timeout: returned `status = FAILED_CLEAN` (`ABSENT_ABSENT_BASELINE_VERIFIED`) with zero orphan metadata or schema corruption.

### 11.3 Suite C — Policy enforcement, audit, and workflow boundaries

1. Verified 2-Axis Policy Gate blocking Tier 0 DocTypes (`GL Entry`, `Stock Ledger Entry`, `Sales Invoice`, `EXRP Settings`) and Tier 0 child-table fields (`Sales Order Item.rate`, `bypass_credit_limit_check`) across all roles.
2. Verified that normal ERPNext document data edits by authorized users remain unaffected by schema-mutation guardrails.
3. Verified Role-Based Authorization Matrix across `System Manager`, `Finance Director`, `Operations Director`, `Sales Manager`, and `Sales User`.
4. Verified fail-closed Stage 3 (`Prepare`) audit durability: simulated audit persistence failure aborted deployment prior to Stage 4 (`Apply`) with zero DDL executed.

### 11.4 Release-gate evidence

*The canonical empirical release-gate report is published at [POC-001: Empirical Verification & Release-Gate Report](./POC-001-empirical-evidence.md).*

## 12. Consequences, Trade-offs, and Alternatives Considered

### 12.1 Benefits

- Preserves stock ERPNext accounting and transactional controllers without core forks.
- Keeps AI proposals separate from deterministic validation, RBAC authorization, and execution.
- Supports isolated previews (DOM form preview, Mermaid workflow graphs, virtual report tables) and 1-click rollback/quarantine.
- Avoids a competing EXRP-owned physical schema authority.
- Bounds metadata lock contention to 3 seconds and treats uncertain outcomes safely via non-destructive reconciliation.

### 12.2 Costs and limitations

- Synchronous physical field creation requires maintaining the version-pinned `ddl_plan_gate.py` adapter against Frappe v15; multi-field or index-creating diffs are routed to `QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT`.
- Metadata locks and implicit commits prevent a universal zero-interference or atomic cross-DDL rollback guarantee.
- MariaDB advisory locks do not serialize privileged non-EXRP changes (`Customize Form` or `bench console`), requiring `base_revision_hash` conflict detection.
- Soft-quarantined fields (`hidden = 1, reqd = 0`) retain their physical column until decommissioned during scheduled administrative maintenance.
- Preview is not an execution-equivalent simulation of server-side ERPNext tax/accounting controllers.

### 12.3 Alternatives considered

1. **Direct Raw `ALTER TABLE` Execution Bypassing Frappe `Custom Field` (Rejected):** Issuing raw `ALTER TABLE` statements directly from EXRP would allow appending `ALGORITHM=INSTANT, LOCK=NONE`, but creates a split-brain schema authority that desynchronizes `tabCustom Field`, bypasses Frappe Redis metadata caches, breaks Desk form rendering, and risks destructive column drops during subsequent `bench migrate` runs.
2. **Forking Core ERPNext / Frappe Schema Synchronizer (Rejected):** Modifying `frappe/database/mariadb/schema.py` in a custom fork would allow native dry-run flags, but violates enterprise upgradeability across Frappe v15 security releases. Using a standalone Frappe app (`exrp`) with `ddl_plan_gate.py` achieves pre-execution inspection with zero core modifications.
3. **External Distributed Locks via Redis Redlock / etcd Instead of MariaDB `GET_LOCK()` (Rejected):** External lease-based locks do not fate-share with the MariaDB database connection; if a worker stalls or loses its Redis lease while DDL is in flight, another worker can overlap. MariaDB's session-scoped `GET_LOCK()` automatically releases within 0.5 ms if the DB connection drops.
4. **Physical Database Shadow Branching for Previews (Rejected):** Cloning or branching MariaDB schemas per conversational turn incurs multi-second I/O overhead and operational complexity. Cloning effective DocType metadata in memory and injecting isolated DOM previews / read-only virtual queries delivers sub-second previews with zero database mutation.

## 13. Companion Decisions

- **ADR-002:** Declarative configuration DSL, field-type allowlist (`PHASE_1_ALLOWED_FIELDTYPES`), and deterministic compiler (`safety_guardrails.py`, `planner.py`).
- **ADR-003:** Isolated Desk preview adapter (in-place DOM form preview, Mermaid workflow diagrammer, and virtual report table preview in `ai_sidecar.bundle.js`).
- **ADR-004:** Frappe schema-diff inspection (`ddl_plan_gate.py`), bounded `GET_LOCK` locking, unified audit journal (`tabEXRP Deployment Audit`), and snapshot reconciliation (`schema_reconciler.py`).
- **ADR-005:** Protected Tier 0 invariant registry (`safety_guardrails.py`), RBAC publication authority, and runtime lifecycle enforcement (`policy_enforcer.py`).
- **ADR-006:** Declarative workflow state-machine verifier (`workflow_engine.py`), declarative Report Builder engine (`report_engine.py`), and cross-document referential policy catalog (`cross_doc_policy.py`).
- **ADR-007:** Unified audit retention, configuration rollback (`ROLLED_BACK`), soft-quarantine (`QUARANTINED` via `rollback_engine.py`), and operational recovery.

## 14. Acceptance Decision

**Status: Accepted.** The empirical exit criteria defined in §11 have been verified and documented in [POC-001: Empirical Verification & Release-Gate Report](./POC-001-empirical-evidence.md) against pinned commit `7b471053e3`, Frappe Framework `v15.126.0`, and MariaDB `10.6.28 / 10.11 LTS`.

The formal release-gate decision is **GO for Synchronous Single-Field Deployment** under the mandatory safeguards:
1. Version-pinned DDL Plan Inspection Gate (`ddl_plan_gate.py`) matching `APPROVED_DDL_REGEX`.
2. MariaDB session-scoped `lock_wait_timeout = 3` to bound metadata lock queueing.
3. Fail-closed Stage 3 (`Prepare`) audit durability in `tabEXRP Deployment Audit` prior to schema mutation.
4. Non-destructive snapshot reconciliation (`schema_reconciler.py`, never auto-deleting unproven metadata) paired with role-gated 1-click rollback and soft quarantine (`rollback_engine.py`).
All multi-field additions, secondary index creations, or column modifications are strictly routed to the controlled administrative deployment queue (`QUEUE_FOR_CONTROLLED_ADMIN_DEPLOYMENT`).

## 15. External Technical References

- [Frappe v15 Source — `Custom Field` Lifecycle (`custom_field.py`)](https://github.com/frappe/frappe/blob/version-15/frappe/custom/doctype/custom_field/custom_field.py)
- [Frappe v15 Source — MariaDB Schema Synchronization (`schema.py`)](https://github.com/frappe/frappe/blob/version-15/frappe/database/mariadb/schema.py)
- [Frappe v15 Source — MariaDB Database Update Path (`database.py`)](https://github.com/frappe/frappe/blob/version-15/frappe/database/mariadb/database.py)
- [MariaDB Documentation — SQL Statements That Cause an Implicit Commit](https://mariadb.com/docs/server/reference/sql-statements/transactions/sql-statements-that-cause-an-implicit-commit)
- [MariaDB Documentation — Metadata Locking (MDL)](https://mariadb.com/docs/server/reference/sql-statements/transactions/metadata-locking)
- [MariaDB Documentation — WAIT and NOWAIT for Schema Operations](https://mariadb.com/docs/server/reference/sql-statements/transactions/wait-and-nowait)

**Evidence note:** Exact DDL emission, MariaDB metadata lock timeouts (3.023s fail-fast abort), advisory lock connection-drop recovery (0.5ms), and non-destructive snapshot reconciliation have been empirically measured and verified on the pinned stack in [POC-001: Empirical Verification & Release-Gate Report](./POC-001-empirical-evidence.md).
