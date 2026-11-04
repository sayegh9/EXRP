# EXRP Developer & Architecture Guide

Welcome to **EXRP**: an AI-native, conversationally tailored ERP/CRM engine built on top of a declarative metadata framework with zero downtime, sandboxed safety, and full accounting compliance.

---

## 🏛️ System Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │      Decoupled AI Frontend (React/Next.js)   │
                    │  - Conversational Agent Interface            │
                    │  - Dynamic Form/Grid Renderer                │
                    │  - Live Schema Diff / Preview Modal          │
                    └──────────────────────┬───────────────────────┘
                                           │ JSON Schema Delta
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ EXRP AI Control Plane (`erpnext/ai_control_plane`)                          │
│                                                                              │
│  1. Schema Extractor: Compact, token-lean DocType JSON for LLM context       │
│  2. Safety Guardrails: Enforces Two-Tier Boundary Fence                      │
│     - Zone 1 (Permitted): CRM, Leads, Custom Entities, Layouts               │
│     - Zone 2 (Locked): GL Entry, Journal Entry, Double-Entry Invariants      │
│  3. Declarative Applier: Safe metadata updates (Custom Field/Property Setter)│
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ Validated Metadata API
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Headless Frappe / ERPNext Seed Engine                                        │
│  - Battle-tested General Ledger, Tax, Multi-currency, and Invoicing Core     │
│  - MariaDB 10.6+ & Redis Cache/Queue Stack                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart: Local Development

### 1. Database & Cache Stack (Docker)
We provide a configured Docker Compose stack for MariaDB (with Frappe-compliant `utf8mb4` collation) and Redis:

```bash
cd docker
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d
```

Check running services:
```bash
docker compose -f docker-compose.dev.yml ps
```

### 2. Testing the AI Control Plane
The AI Control Plane modules (`erpnext/ai_control_plane`) are tested independently:

```bash
# Run unit tests directly
PYTHONPATH=. python3 erpnext/tests/test_ai_control_plane.py
```

---

## 📚 Key Documents

* **[ADR-001: Headless Frappe & Modular Accounting Seed](file:///home/samx/Documents/projects/EXRP/docs/architecture/ADR-001-foundation.md)**
* **[PRD-001: Conversational Customization Engine](file:///home/samx/Documents/projects/EXRP/docs/product/PRD-001-ai-control-plane.md)**
