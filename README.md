# EXRP: AI-Native Configuration Control Plane for Frappe / ERPNext

EXRP is a Frappe-native configuration control plane that enables non-technical business operators to customize data models, form layouts, and operational workflows through natural language prompts—with zero downtime, sandboxed safety, and full accounting compliance.

---

## 🏛️ Architecture & Verified Guarantees (ADR-001 Rev 2.3)

* **Standalone Frappe App**: Installs cleanly via `bench get-app https://github.com/sayegh9/EXRP.git` and `bench install-app exrp`. Does **not** fork or modify ERPNext core.
* **Three-Pillar Separation**:
  1. **Configuration Preview**: Request-scoped clones of effective metadata rendered in an isolated preview container (zero DB DDL executed).
  2. **Controlled Deployment**: Native Frappe `Custom Field` / `Property Setter` authority wrapped in a 6-stage durable sequence (`Acquire -> Inspect/DDL Plan Gate -> Prepare/Audit -> Apply -> Snapshot Reconcile -> Finalize`).
  3. **Runtime Policy Enforcement**: Server-side Document lifecycle hooks (`validate`, `before_submit`, `before_update_after_submit`) enforcing invariants across Desk, REST, and background jobs.
* **Approved-Only DDL Plan Gate (§6.1 / §6.2)**: Simulates Frappe's `MariaDBTable.sync()` diff before execution; strictly halts and queues any plan producing unexpected `MODIFY COLUMN`, index alterations, or table rebuilds.
* **Non-Destructive Snapshot Reconciliation (§9)**: Bounded MariaDB connection-scoped advisory locking (`GET_LOCK <= 64 chars`), fail-fast `lock_wait_timeout = 3s`, and 6-row non-destructive disposition. Never auto-deletes metadata or drops physical columns in Phase 1.
* **2-Axis Policy Compiler (§5)**: Protects Tier 0 Parent & Child ERP Invariants (`GL Entry`, `Sales Order Item.rate`, `bypass_credit_limit_check`) against AI weakening, while enabling authorized Tier 1 bidirectional policy relaxation by Directors.

---

## 📁 Repository Layout

```text
EXRP/
├── pyproject.toml              # Standalone Frappe app manifest
├── docker/
│   ├── docker-compose.dev.yml  # Local MariaDB 10.6+ & Redis 7 stack
│   ├── my.cnf                  # Frappe utf8mb4 collation configuration
│   └── .env.example
├── docs/
│   ├── DEVELOPMENT.md
│   ├── architecture/ADR-001-foundation.md  # Canonical ADR-001 Rev 2.3
│   └── product/PRD-001-ai-control-plane.md
└── exrp/
    ├── __init__.py             # Version definition (0.1.0)
    ├── hooks.py                # Frappe app registration, Desk assets, and lifecycle hooks
    ├── modules.txt
    ├── patches.txt
    ├── ai_control_plane/
    │   ├── __init__.py
    │   ├── ddl_plan_gate.py      # §6.1/§6.2 Approved-only DDL plan gate
    │   ├── planner.py            # §4 Conversational Planner with Gemini Interactions & Self-Correction
    │   ├── policy_enforcer.py    # §4.2/§5 Runtime Policy Enforcement Engine & Invariant Guards
    │   ├── safety_guardrails.py  # §5 2-Axis Policy Compiler & Protected Invariants
    │   ├── schema_extractor.py   # §4.1 Token-lean compact schema extractor
    │   └── schema_reconciler.py  # §7/§8/§9 6-Stage Durable Reconciler & GET_LOCK
    ├── api/
    │   ├── __init__.py
    │   └── control_plane.py      # Whitelisted Frappe REST / RPC endpoints & Document lifecycle hooks
    ├── public/
    │   ├── css/
    │   │   └── ai_sidecar.css    # Frappe Desk Light & Dark theme sidecar styles
    │   └── js/
    │       └── ai_sidecar.bundle.js # Desk embedded drawer, floating launcher, & DDL visualizer
    └── tests/
        ├── test_ai_control_plane.py       # Suites A, B, C unit tests (12/12 passing)
        ├── test_planner.py                # Conversational Planner & self-correction tests (8/8 passing)
        ├── test_api_deployment.py         # Whitelisted deployment & role authorization tests (10/10 passing)
        ├── test_policy_enforcer.py        # Runtime Document lifecycle hooks & policy tests (10/10 passing)
        └── test_live_mariadb_suite_b.py   # Live MariaDB Suite B PoC (5/5 passing)
```

---

## 🚀 Running Tests & Empirical PoC Verification

### 1. Complete Unit, Planner & Policy Test Suites (40 tests)
```bash
PYTHONPATH=. .venv/bin/python exrp/tests/test_ai_control_plane.py
PYTHONPATH=. .venv/bin/python exrp/tests/test_planner.py
PYTHONPATH=. .venv/bin/python exrp/tests/test_api_deployment.py
PYTHONPATH=. .venv/bin/python exrp/tests/test_policy_enforcer.py
```

### 2. Live MariaDB 10.11 Suite B Integration PoC
Spin up the local container stack:
```bash
docker compose -f docker/docker-compose.dev.yml up -d
```

Run the live test against `127.0.0.1:3306`:
```bash
.venv/bin/python exrp/tests/test_live_mariadb_suite_b.py
```
Empirically verifies:
- Connection-scoped `GET_LOCK()` acquisition and instant release on connection drop.
- Fail-fast Metadata Lock contention (`lock_wait_timeout = 3s` aborting in 3.03s).
- User read query tail latency measurement (p50=1258ms, p95=2669ms, dropping to 0.70ms post-timeout).
- Non-destructive `FAILED_CLEAN` snapshot reconciliation preserving zero orphan corruption.
