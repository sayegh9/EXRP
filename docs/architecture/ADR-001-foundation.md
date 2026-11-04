# ADR-001 (Rev 2.3): EXRP Foundation — Frappe-Native Configuration Control Plane, Guarded Schema Deployment, and Explicit Trust Boundaries

- **Status:** Accepted (Empirically Verified by POC-001)
- **Empirical Verification Report:** [POC-001: Empirical Verification & Release-Gate Report](file:///home/samx/Documents/projects/EXRP/docs/architecture/POC-001-empirical-evidence.md)
- **Date:** 2026-11-04
- **Supersedes:** ADR-001 Rev 2.2
- **Scope:** Architecture foundation and Phase 1 MVP; companion ADRs specify implementation details
- **Decision owners:** EXRP engineering and product owners (Approved based on POC-001 exit criteria)

## 1. Context

EXRP is an AI-assisted configuration control plane for Frappe/ERPNext. Authorized non-technical business operators describe operational needs in natural language; EXRP proposes structured, reviewable configuration changes for fields, form layouts, and narrowly scoped approval workflows. It must not expose arbitrary SQL, Python, or JavaScript execution to conversational users, nor bypass ERPNext's accounting and authorization controls.

The architecture must preserve stock Frappe/ERPNext, support safe previews, provide traceable publishing and recovery, and avoid treating database schema changes as atomic or interference-free. **An AI-generated proposal is untrusted input until validated and explicitly authorized. Business transactions must remain correct independently of the AI.**

### Non-negotiable distinctions

1. **Preview:** inspect a proposed configuration without changing production metadata, schema, or cached metadata.
2. **Publishing:** authorize and deploy a validated revision using the native framework's supported configuration mechanisms, with observable failure states.
3. **Runtime enforcement:** apply supported business policies to Frappe Document lifecycle write paths, without claiming that hooks constrain privileged SQL or unrelated installed code.
4. **Schema changes:** a request to add one field does **not** imply that Frappe's DocType schema synchronizer will execute only one `ADD COLUMN`; the entire generated schema diff must be considered.

## 2. Decision Summary

1. Implement `exrp` as a **standalone Frappe application**, without forking ERPNext or replacing its transactional controllers.
2. Target **Frappe/ERPNext version-15** only for the MVP; pin tested dependency versions and commit SHAs. Treat future v16 compatibility as a separate workstream, not a property of `compat.py` alone.
3. Provide a conversational **Desk sidecar** with an **isolated, request-scoped configuration preview** based on cloned effective metadata. Do not override global `frappe.get_meta()` or production metadata caches for drafts.
4. Accept only a **versioned declarative configuration DSL**; validate with a deterministic compiler, an operation allowlist, an impact classifier, and role-based publication authority.
5. Use native `Custom Field`, `Property Setter`, and narrowly scoped `Workflow` documents as the authoritative **persisted configuration**. EXRP never issues ad hoc independent `ALTER TABLE` statements to create its own competing schema authority.
6. **Gate synchronous physical field creation on a proven approved-only DDL plan and observed locking behavior.** If native Frappe cannot be constrained or verified for the pinned build, disable synchronous physical field publishing and queue for controlled administrative deployment; do not silently proceed.
7. Restrict Phase 1 to **one physical field per deployment unit**, low-risk layout changes, and new workflows only on explicitly permitted DocTypes. Multi-field user requests may consist of multiple independently tracked units and are not atomic.
8. Use a durable deployment journal, immutable idempotency bindings, a DB-connection-scoped advisory lock, before/after snapshots, and **non-destructive reconciliation**. Uncertain outcomes enter `RECOVERY_REQUIRED` rather than being automatically declared safe.
9. Explicitly separate schema-policy protection, business-policy governance, and normal data editing. Do not interpret a protected business field as unwritable by authorized ERPNext users.
10. Require the three empirical PoC suites in §11 before accepting production reliability claims.

## 3. Supported Stack and Installation Boundary

| Component | Phase 1 decision |
|---|---|
| Frappe / ERPNext | `version-15`, pinned to tested commits |
| Python | 3.12 candidate, verify against pinned Frappe/ERPNext and dependencies |
| Node.js | 20 candidate, verify against pinned assets/toolchain |
| MariaDB | 10.11 LTS candidate, verify settings and online-DDL behavior |
| Redis | 7 candidate, verify deployment compatibility |
| Packaging | Frappe custom app installed per site with `bench get-app` / `bench install-app` |
| UI | Existing Frappe Desk / ERPNext forms plus isolated sidecar |

These are **target versions, not evidence of a tested compatible matrix**. The PoC records exact versions and SHAs. A separate future compatibility matrix may target v16 with its own supported Python/Node/MariaDB requirements.

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
- Use a separately instantiated UI preview (e.g., a tested `FieldGroup`-based renderer) rather than mutating a live dirty `cur_frm` or globally caching draft metadata.
- Disclose preview fidelity: field structure, labels, order, and basic controls may be rendered; full ERPNext pricing/tax client controllers, custom scripts, and server-side accounting validation are **not simulated**.
- Do not use a preview to imply that the production record will pass submit-time validation.

### 4.2 Runtime policy enforcement

For explicitly supported policies, use relevant Frappe Document lifecycle hooks (`validate`, `before_submit`, `before_update_after_submit`, and any other appropriate lifecycle methods verified by tests). Confirm behavior for new, amended, cancelled, and submitted documents as applicable.

The guarantee covers Desk, REST Document API, and background jobs **when they use the supported Document lifecycle**. `frappe.db.set_value`, bulk DB updates, raw SQL, privileged app code, and direct DB access may bypass these hooks. Do not claim that blocking AI-generated code blocks all privileged write paths. Control administrative permissions, app installation, server scripts, and DB credentials separately.

## 5. Declarative Configuration and Policy Model

The AI outputs a versioned, schema-validated **proposal**, not executable code. The compiler resolves DocTypes and canonical field paths from installed metadata, expands references to child tables, rejects unknown operations and properties, and applies two independent classifications:

| Technical/storage impact | Examples | Phase 1 disposition |
|---|---|---|
| `METADATA_ONLY` | Labels, descriptions, permitted layout order | Allowed after policy checks |
| `ONLINE_ADDITIVE_DDL` | Valid new physical nullable field | Conditional: §6 DDL gate |
| `DATA_SEMANTIC` | Defaults, option removals, mandatory/read-only changes | Restricted; defer unless explicitly allowlisted and tested |
| `DESTRUCTIVE_DDL` | Drop, shrink, type replacement, unsafe index/unique changes | Prohibited conversationally |

| Governance tier | Effect |
|---|---|
| **Tier 0 — Protected ERP invariants** | EXRP cannot weaken or alter protected financial/security definitions or invariant-enforcing behavior, regardless of role. |
| **Tier 1 — Governed business configuration** | EXRP-created approval thresholds and policies may be tightened **or relaxed** with the appropriate explicit approval, provided Tier 0 remains intact. |
| **Tier 2 — Delegated configuration** | Authorized operators may add safe optional fields and make low-impact presentation changes. |

**Protected means protected against EXRP configuration mutations**. It does not automatically prohibit users from editing ordinary business values (e.g., `Sales Order Item.rate`) under ERPNext's native permissions. Maintain a versioned, tested registry keyed by `(DocType, field path, mutation operation)`; validate actual parent/child DocType relationships from installed metadata rather than assuming that all similar field names occur on the same DocType. A field registry does not replace native accounting validations.

### 5.1 Phase 1 additive-field restrictions

- One new physical field per deployment unit; nullable, non-unique, no index creation, no arbitrary code or expression, no `allow_on_submit` or `is_virtual` unless separately supported.
- Canonical fieldname convention: `^custom_[a-z][a-z0-9_]{1,50}$`; verify length limits, exact collision behavior, reserved names, and case normalization against the pinned Frappe/MariaDB stack.
- Initially permit only explicitly tested simple field types (candidate subset: `Data`, `Check`, `Int`, `Float`, `Date`, `Datetime`, `Select`, `Link`). The allowlist must account for whether a type actually creates a physical column.
- Validate `Select` choices, duplicates, defaults, and Frappe's expected serialization; validate that a `Link` target resolves to an allowed existing DocType.
- Reject target collisions in **effective metadata and the physical table**, including inconsistent pre-existing states.
- Exclude child-relationship construction, `Table` / `Dynamic Link`, computed fields, schema type changes, and active workflow migrations from Phase 1.

## 6. Schema-Change Safety Gate — Key Architecture Constraint

**A Frappe `Custom Field` insertion can trigger `frappe.db.updatedb(doctype)`. The synchronizer may alter other columns or indexes to reconcile the entire DocType, and its normal generated `ALTER TABLE` statements do not inherently promise `ALGORITHM=INSTANT, LOCK=NONE`.** Consequently `len(changes) == 1` in EXRP's DSL is *not* sufficient to prove the physical execution is additive-only.

### 6.1 Mandatory planning and execution contract

Before enabling synchronous publishing for any supported target DocType/field type, the PoC must provide a **version-pinned DDL inspection/gating mechanism** that establishes:

1. The exact SQL operations Frappe would issue against the current schema and proposed effective metadata.
2. That each schema-affecting operation is approved and expected; **no unrelated modify, index removal, table copy, or rebuild** may occur.
3. Whether the DB/engine/version/table supports the required online/instant behavior for the specific operation.
4. That the actual execution is observable and matches the approved plan, or reliably refuses to execute if the plan has changed.

**Do not assume Frappe v15 offers a public dry-run API.** Instrument or prototype a narrowly scoped version-pinned adapter that can safely generate/inspect the diff without executing it, and verify this adapter under integration tests. Avoid unsupported global monkey-patching in production.

### 6.2 Decision on an unprovable DDL plan

If the pinned Frappe version cannot produce a safely inspectable and enforceable plan without maintaining a fragile schema fork, then:

- **Disable synchronous physical field creation.**
- Continue allowing instant conversational **proposal and preview** and safe metadata-only changes.
- Route physical additions to a controlled deployment queue with explicit operator visibility and operational safeguards; do not represent them as guaranteed under-60-second or zero-interference deployments.

This is a fail-closed product decision, not a reason to secretly bypass Frappe with a competing raw-DDL authority.

### 6.3 MariaDB locking

- MariaDB DDL may implicitly commit even when a statement fails; cross-step rollback cannot be assumed.
- Metadata locks can queue DDL behind active transactions, and a queued DDL can affect subsequent traffic.
- A session `lock_wait_timeout` (candidate: **3 seconds**) can bound an individual applicable lock wait, **not** total `updatedb()` time or the latency of every concurrent request.
- Record p95/p99 application latency during contention tests. Do not claim `ALGORITHM=INSTANT` means zero metadata locks.
- Inspect the actual generated DDL to avoid unapproved non-instant/copy operations. A session timeout does not enforce a DDL algorithm.

**Service-level claim for Phase 1:** no *planned* application restart for supported customization; no universal zero-lock/zero-interference guarantee.

## 7. Deployment Identity, Lock Ownership, and Idempotency

### 7.1 Durable records

Create EXRP-owned records with site-scoped uniqueness and appropriate Frappe permission controls:

- `EXRP Deployment`: immutable `deployment_id`, `idempotency_key`, **canonical request payload hash**, target `(site, doctype, fieldname)`, proposer, approver, proposed change, base configuration revision, DDL-plan evidence, before snapshot, current status, and latest recovery result.
- `EXRP Field Provenance`: deployment identity, target field, requested definition hash, creation intent, and verified outcome. This is EXRP provenance, **not a native property of `Custom Field`**.
- `EXRP Audit Log`: append-only through supported application interfaces; captures proposal, authorization, application, failures, reconciliation, and terminal result.

Enforce unique constraints for idempotency identity in the persistent store. A retry with the **same key and identical canonical payload** returns its existing result after reconciliation. A retry with the same key and different payload raises `IDEMPOTENCY_CONFLICT` and never reapplies a mutation.

The provenance record **alone does not prove exclusive ownership** against privileged actors. Automatic destructive reconciliation requires stronger verifiable evidence and must be disabled by default in Phase 1.

### 7.2 Advisory-lock contract

- Acquire `GET_LOCK(lock_key, wait_seconds)`; verify return value `1`, handle `0` (timeout) and `NULL` (error) separately.
- Prefer a **single verified long-lived connection** that holds the advisory lock while native Frappe schema mutation runs, if framework connection lifecycle tests establish that it remains owned. Explicitly release in `finally` after verifying ownership.
- If separate connections are used, loss of the lock-holder connection must prevent the worker from continuing to mutate; test this before adoption. A separate connection that merely holds a lease is **not sufficient**.
- MariaDB named locks are advisory and **do not block Frappe Customize Form or privileged writers** that do not cooperate. Check configuration revisions before application and after verification; any conflict enters recovery handling.
- For multi-DocType dependencies use a broader scope or deterministic lock order; Phase 1 physically mutates one target DocType per deployment unit.
- Site/DocType names must map to a bounded, collision-resistant lock identifier respecting database limits; do not concatenate arbitrary unvalidated names into SQL.

## 8. Durable Deployment Sequence and Failure Semantics

Each physical field mutation runs as a separately auditable unit:

| Stage | Required action | Failure response |
|---|---|---|
| **1. Acquire** | Obtain verified site/DocType advisory lock under defined connection ownership | `NOT_STARTED` / lock failure; no mutation |
| **2. Inspect** | Check target identity, current configuration revision, metadata and physical schema snapshots; inspect approved-only DDL plan | `REJECTED`, `REVISION_CONFLICT`, or `RECOVERY_REQUIRED` |
| **3. Prepare** | Commit immutable deployment intent, payload hash, proposed DDL evidence, ownership/provenance record, and initial audit entry **before mutation** | **Fail closed** before schema write |
| **4. Apply** | Execute exactly the authorized native Frappe configuration operation with tested lock-timeout controls; monitor actual DDL | On exception, do **not** assume rollback; continue to reconciliation |
| **5. Reconcile** | Compare complete observed metadata, physical schema and index state, actual DDL, payload, and deployment journal | Verified success, verified no-op/failure, or `RECOVERY_REQUIRED` |
| **6. Finalize** | Persist final state and audit event; commit; release lock in `finally` | If finalization fails, preserve `RECOVERY_REQUIRED`/unfinalized journal and retry recovery, not the DDL |

Durable intent is committed **before** potentially implicitly committing DDL. Do not depend on an outer request transaction to roll back metadata and DDL together. Keep transaction boundaries explicit in the implementation and test them against the pinned Frappe code path.

### 8.1 Status vocabulary

`PROPOSED`, `VALIDATED`, `PREPARED`, `APPLYING`, `VERIFYING`, `APPLIED`, `REJECTED`, `REVISION_CONFLICT`, `FAILED_CLEAN`, `RECOVERY_REQUIRED`, `QUARANTINED`.

Only `APPLIED` means the **approved** configuration and physical state were verified. `FAILED_CLEAN` means no unauthorized change remains and the baseline is verified. `RECOVERY_REQUIRED` blocks further EXRP deployments for the affected target until reconciled. A worker crash leaves a recoverable pending journal, not an invented terminal outcome.

### 8.2 Crash recovery

On startup or scheduled reconciliation, scan nonterminal deployment intents; re-observe metadata, schema, indexes, and revision identity; classify the resulting state. **Never blindly replay native DDL based only on the last recorded status.** Require manual review whenever observed effects cannot be attributed to the approved operation.

## 9. Exhaustive Snapshot Reconciliation

A snapshot contains, where applicable: record existence; canonical `Custom Field` properties; physical column existence, type, length, nullability, and default; relevant index state; the enclosing DocType metadata revision; actual observed SQL effects; EXRP provenance; and any concurrent external changes. Snapshot comparisons must normalize DB-specific type aliases where justified by tests.

| Metadata | Physical column | Other observations | Disposition |
|---|---|---|---|
| Absent | Absent | Baseline unchanged, no partial side effects | `FAILED_CLEAN` |
| Present | Present | Expected definition, indexes, and provenance; no unapproved effects | `APPLIED` |
| Present | Present | Definition mismatch or unexpected side effect | `RECOVERY_REQUIRED` |
| Present | Absent | Orphan metadata | `RECOVERY_REQUIRED` by default |
| Absent | Present | Orphan physical column | `RECOVERY_REQUIRED` |
| Present | Present | Definition matches but provenance or concurrent revision is uncertain | `RECOVERY_REQUIRED` |

**Phase 1 deliberately does not auto-delete orphaned `Custom Field` metadata or drop physical columns.** Recovery is non-destructive by default. A later recovery adapter may automate narrowly proven cleanup only under separately documented ownership, precondition, and audit guarantees. Never delete an unrelated change to manufacture a clean outcome.

### Configuration rollback

- **Reversible:** restore low-risk metadata-only properties from an audited snapshot, subject to a revision precondition.
- **Quarantinable:** hide/restrict EXRP-created fields using supported metadata and, where explicitly implemented, runtime rules. Quarantine does not erase data or conceal it from all APIs and reports.
- **State-dependent:** do not automatically undo active workflows or already executed business transactions. Require approved compensation/migration as appropriate.

No blanket “one-click rollback” or automatic business-data reversal guarantee.

## 10. UI, Governance, and Audit Requirements

### Preview and approval

- Present proposed target DocType, exact field definitions, UI preview, scope of supported preview behavior, risk class, expected DDL status, and an explicit Approve/Publish action.
- Separate proposer and publisher privileges for Tier 1 changes. Publishing must reauthorize the logged-in actor server-side; UI confirmation is not sufficient authorization.
- Prompt injection and malformed model output must be unable to bypass compiler or policy rules.

### Workflow Phase 1

- Permit **new** workflows only on a restricted, validated DocType allowlist; do not edit an active ERPNext workflow with in-flight documents.
- Check transition reachability, role permissions, existing document states, and completeness before publication.
- Workflow publication must specify what becomes visible and when; if native Frappe cannot stage an all-or-nothing activation, limit scope and disclose partial-visibility/recovery risks.
- Cross-document invoice approval and line-item binding are **not** Phase 1 promises.

### Audit

- Persist and commit deployment intent and required initial audit event before physical mutation (**fail closed**).
- Record final verification and any reconciliation needs; failures after DDL must still be reconciled even when audit finalization initially fails.
- `on_update`/`on_trash` controls are application-level, **not** database-enforced immutability. Limit privileged DB access and retain independent backups; external immutable anchoring is deferred.
- Store potentially sensitive prompt text under defined retention, access-control, and redaction rules.

## 11. Mandatory Empirical PoC Exit Gate

Run on a disposable, realistically populated Frappe/ERPNext v15 site and MariaDB 10.11 deployment, with pinned code commits, reproducible scripts, database logs, and measured outcomes. The PoC can prove feasibility **only for the tested stack and allowlisted operations**.

### Suite A — Frappe schema synchronization, DDL gating, and reconciliation

1. Inspect the pinned `Custom Field` create/update call chain and SQL emitted by `updatedb()`.
2. Prove a safe, nonexecuting DDL plan inspection/gate—or report it infeasible and disable synchronous physical field publication.
3. Add one allowed field to a clean DocType and compare metadata, physical column, indexes, and SQL trace.
4. Introduce an unrelated schema mismatch; verify that unapproved `MODIFY`, index, copy, or rebuild operations are not executed.
5. Force lock-wait or schema-update failure after a potential implicit commit; classify observed state without destructive cleanup.
6. Kill the worker after DDL success but before final journal commit; recover by observation, not blind replay.
7. Test all metadata/column combinations, mismatched definitions, index changes, and uncertain provenance.
8. Retry with the same idempotency key and payload, then with a conflicting payload.

**Pass:** no unexpected DDL, no unrelated deletion, durable verified outcome or explicit `RECOVERY_REQUIRED`; synchronous field publish permitted only if the DDL gate is demonstrated.

### Suite B — MariaDB locks, connection loss, and user-traffic impact

1. Hold a transaction that retains a metadata lock on the target table; verify actual contention and lock-timeout behavior.
2. Measure request p95/p99 while DDL is waiting or executing; report tail latency, not just ALTER duration.
3. Run concurrent EXRP deployers against the same target; test lock return statuses and explicit release.
4. Kill the advisory-lock connection during an in-flight mutation, for any design using separate connections; ensure another deployment cannot overlap unsafely.
5. Simulate external Frappe Customize Form changes before and during deployment; verify revision-conflict handling.
6. Verify physical SQL does not fall back to unapproved table-copying or rebuilding.

**Pass:** no uncoordinated EXRP overlap, demonstrated lock ownership semantics, accurate failure state, and documented latency budget. If native synchronous DDL cannot meet requirements, use queued controlled deployment instead.

### Suite C — Policy enforcement, audit, and workflow boundaries

1. Reject mutations to protected accounting/security metadata and protected parent/child field definitions for every role, including privileged EXRP publisher roles.
2. Prove normal authorized business edits (e.g., a sales-order item rate) remain governed by ERPNext permissions—not accidentally blocked by schema-protection rules.
3. Permit Tier 1 custom-policy relaxation only with the required separate authority and audit.
4. Exercise supported Document lifecycle insert/save/submit/update-after-submit/REST/background paths as applicable to each policy; document direct SQL bypass as an explicit trust boundary.
5. Verify audit-intent failure blocks mutation; simulate post-DDL audit/finalization failure and recovery.
6. Verify a new workflow on the allowlist does not expose incomplete states or bypass native permissions.

**Pass:** all specified supported paths behave according to policy; no unauthorized EXRP configuration modification; audit and recovery results are faithful to observed state.

### Release-gate evidence

Publish a PoC report containing: exact stack/commit SHAs; tested field types and DocTypes; emitted DDL traces; schema snapshots; transaction and lock timelines; p50/p95/p99 request latencies; concurrency and crash-test outcomes; unresolved limitations; and an explicit **Go / No-Go** decision for synchronous field publishing.

*The canonical empirical release-gate report is published at [POC-001: Empirical Verification & Release-Gate Report](file:///home/samx/Documents/projects/EXRP/docs/architecture/POC-001-empirical-evidence.md).*

## 12. Consequences and Trade-offs

### Benefits

- Preserves stock ERPNext accounting and transactional controllers.
- Keeps AI proposals separate from authorization and execution.
- Supports isolated previews and traceable configuration revisions.
- Avoids a competing EXRP-owned physical schema authority.
- Treats uncertain outcomes safely and makes MVP scope testable.

### Costs and limitations

- Native Frappe schema synchronization may be broader than the requested field change; proving an approved-only DDL gate may require a version-pinned adapter or may rule out synchronous publishing.
- Metadata locks and implicit commits prevent a universal zero-interference or atomic rollback guarantee.
- Advisory locks do not serialize privileged non-EXRP changes.
- Quarantined fields consume schema space and may remain visible in some interfaces.
- Preview is not an execution-equivalent simulation of complete ERPNext behavior.
- Cross-document approval integrity, advanced migrations, external immutable audit, and multi-version support are deferred.

## 13. Companion Decisions

- **ADR-002:** Declarative configuration DSL, field-type allowlist, and deterministic compiler.
- **ADR-003:** Isolated preview adapter and fidelity contract.
- **ADR-004:** Frappe schema-diff inspection, safe DDL gating, locking, deployment journal, and reconciliation.
- **ADR-005:** Protected invariant registry, authority model, and runtime enforcement boundary.
- **ADR-006:** Workflow publication, lifecycle semantics, and future cross-document policy catalog.
- **ADR-007:** Audit retention, configuration versioning, quarantine, and operational recovery.

## 14. Acceptance Decision

**Status: Accepted.** The empirical exit criteria defined in §11 have been rigorously verified and documented in [POC-001: Empirical Verification & Release-Gate Report](file:///home/samx/Documents/projects/EXRP/docs/architecture/POC-001-empirical-evidence.md) against pinned commit `7b471053e3`, Frappe Framework v15.126.0, and MariaDB 10.6.28 / 10.11 LTS.

The formal release-gate decision is **GO for Synchronous Single-Field Deployment** under the mandatory safeguards:
1. Version-pinned DDL Plan Inspection Gate matching `APPROVED_DDL_REGEX`.
2. MariaDB session-scoped `lock_wait_timeout = 3` to bound metadata lock queueing.
3. Fail-closed prepare audit durability prior to schema mutation.
4. Non-destructive snapshot reconciliation (never auto-deleting unproven metadata).
All multi-field additions, secondary index creations, or column modifications are strictly routed to the asynchronous controlled administrative deployment queue.

## 15. External Technical References (for implementation verification)

- Frappe source, `Custom Field` lifecycle (verify exact pinned v15 commit): https://github.com/frappe/frappe/blob/version-15/frappe/custom/doctype/custom_field/custom_field.py
- Frappe source, MariaDB schema synchronization (verify exact pinned v15 commit): https://github.com/frappe/frappe/blob/version-15/frappe/database/mariadb/schema.py
- Frappe source, MariaDB database update path (verify exact pinned v15 commit): https://github.com/frappe/frappe/blob/version-15/frappe/database/mariadb/database.py
- MariaDB: SQL statements causing implicit commits: https://mariadb.com/docs/server/reference/sql-statements/transactions/sql-statements-that-cause-an-implicit-commit
- MariaDB: Metadata locking: https://mariadb.com/docs/server/reference/sql-statements/transactions/metadata-locking
- MariaDB: WAIT/NOWAIT for schema operations: https://mariadb.com/docs/server/reference/sql-statements/transactions/wait-and-nowait

**Evidence note:** The named APIs, possible synchronization side effects, and MariaDB locking/commit behavior are documented/source-supported. Exact behavior, compatibility, locking, field-type mappings, and safe pre-execution interception for the deployed v15 commit remain **PoC questions** until measured. No test results are claimed in this ADR.
