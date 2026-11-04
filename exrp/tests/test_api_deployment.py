"""
Unit Tests for EXRP Whitelisted Backend Deployment Endpoint (ADR-001 Rev 2.3)
Verifies:
1. Successful deployment through apply_configuration_change using mock/in-memory adapter.
2. Rejection of unauthorized roles (enforcing System Manager, Finance Director, Operations Director).
3. MariaDB advisory lock contention, lock timeout (0), NULL error handling, and release-on-exit.
4. Idempotency binding replay and conflict detection (§7.1).
5. Fail-closed prepare audit durability before schema mutation (§8).
6. Live Frappe-like SQL execution mocking (GET_LOCK, SET SESSION lock_wait_timeout, reflection, Custom Field insert).
"""

import hashlib
import json
import os
import sys
import types
import unittest
from typing import Any, Dict, List, Optional

# Ensure repository root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Safe Frappe mocking for isolated standalone unit test runs
if "frappe" not in sys.modules:
    try:
        import frappe
    except ImportError:
        f = types.ModuleType("frappe")
        f.utils = types.ModuleType("frappe.utils")
        f.utils.cstr = lambda x: str(x)
        f.local = types.SimpleNamespace(site="test_site.local")
        sys.modules["frappe"] = f
        sys.modules["frappe.utils"] = f.utils

try:
    import frappe
    if hasattr(frappe, "local"):
        if not hasattr(frappe.local, "flags"):
            frappe.local.flags = frappe._dict() if hasattr(frappe, "_dict") else types.SimpleNamespace()
        frappe.local.flags.in_test = True
except Exception:
    pass

from exrp.ai_control_plane.ddl_plan_gate import ColumnDesc, DDLPlanInspection
from exrp.ai_control_plane.schema_reconciler import (
    ExhaustiveSnapshot,
    IdempotencyConflictError,
    make_bounded_lock_key,
)
from exrp.api.control_plane import (
    AUTHORIZED_DEPLOYMENT_ROLES,
    FrappeDeploymentAdapter,
    apply_configuration_change,
    get_current_user_roles,
)


class MockDeploymentAdapter:
    """Mock adapter double for testing apply_configuration_change."""

    def __init__(
        self,
        lock_return: int = 1,
        target_in_recovery: bool = False,
        before_snapshot: Optional[ExhaustiveSnapshot] = None,
        after_snapshot: Optional[ExhaustiveSnapshot] = None,
    ):
        self.lock_return = lock_return
        self.target_in_recovery = target_in_recovery
        self.before_snapshot = before_snapshot or ExhaustiveSnapshot(
            has_meta=False, has_col=False, revision_hash="rev_100"
        )
        self.after_snapshot = after_snapshot or ExhaustiveSnapshot(
            has_meta=True,
            has_col=True,
            definition_matches=True,
            indexes_unchanged=True,
            provenance_matches=True,
            unapproved_side_effects=False,
            revision_hash="rev_101",
        )
        self.lock_released = False
        self.apply_called = False
        self.cache_cleared = False
        self.idempotency_store: Dict[tuple, Dict[str, Any]] = {}
        self.prepared_records: List[Dict[str, Any]] = []

    def acquire_advisory_lock(self, lock_key: str, wait_seconds: int) -> Optional[int]:
        return self.lock_return

    def release_advisory_lock(self, lock_key: str) -> None:
        self.lock_released = True

    def is_target_in_recovery_required(self, site_id: str, doctype: str) -> bool:
        return self.target_in_recovery

    def get_existing_deployment_by_idempotency(
        self, site_id: str, idempotency_key: str
    ) -> Optional[Dict[str, Any]]:
        return self.idempotency_store.get((site_id, idempotency_key))

    def get_doctype_revision_hash(self, doctype: str) -> str:
        return self.before_snapshot.revision_hash

    def take_snapshot(
        self, doctype: str, fieldname: str, expected_deployment_id: str
    ) -> ExhaustiveSnapshot:
        return self.after_snapshot if self.apply_called else self.before_snapshot

    def inspect_ddl_plan(self, doctype: str, field_def: Dict[str, Any]) -> DDLPlanInspection:
        fieldname = field_def["fieldname"]
        return DDLPlanInspection(
            inspectable=True,
            statements=[f"ALTER TABLE `tab{doctype}` ADD COLUMN `{fieldname}` varchar(140)"],
            is_approved_additive_only=True,
        )

    def persist_prepare_and_audit_intent(self, record: Dict[str, Any]) -> None:
        self.prepared_records.append(record)

    def persist_final_outcome_and_audit(
        self, deployment_id: str, outcome_record: Dict[str, Any]
    ) -> None:
        if self.prepared_records:
            rec = self.prepared_records[-1]
            self.idempotency_store[(rec["site_id"], rec["idempotency_key"])] = outcome_record

    def set_lock_wait_timeout(self, seconds: int) -> None:
        pass

    def apply_native_custom_field(
        self, deployment_id: str, doctype: str, field_def: Dict[str, Any]
    ) -> None:
        self.apply_called = True

    def clear_doctype_cache(self, doctype: str) -> None:
        self.cache_cleared = True


class TestApiDeployment(unittest.TestCase):
    """Test suite for apply_configuration_change and FrappeDeploymentAdapter under ADR-001 Rev 2.3."""

    def setUp(self):
        FrappeDeploymentAdapter.reset_in_memory_state()

    def tearDown(self):
        FrappeDeploymentAdapter.reset_in_memory_state()

    def test_1_successful_deployment_with_mock_adapter(self):
        """
        Requirement 1: Test successful deployment through the API with mock adapter.
        Verifies 6-stage durable sequence outcome: APPLIED, VERIFIED_CONSISTENT, execution_time_ms.
        """
        mock_adapter = MockDeploymentAdapter()
        field_def = {
            "fieldname": "custom_loyalty_tier",
            "label": "Loyalty Tier",
            "fieldtype": "Data",
        }

        outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_mock_001",
            field_def=field_def,
            idempotency_key="idemp_mock_001",
            adapter=mock_adapter,
            user_roles=["System Manager"],
        )

        self.assertTrue(outcome.get("success"), f"Deployment failed: {outcome}")
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "VERIFIED_CONSISTENT")
        self.assertEqual(outcome["doctype"], "Sales Order")
        self.assertEqual(outcome["fieldname"], "custom_loyalty_tier")
        self.assertIn("execution_time_ms", outcome)
        self.assertGreaterEqual(outcome["execution_time_ms"], 0.0)

        # Verify adapter lifecycle methods called
        self.assertTrue(mock_adapter.apply_called)
        self.assertTrue(mock_adapter.cache_cleared)
        self.assertTrue(mock_adapter.lock_released)
        self.assertEqual(len(mock_adapter.prepared_records), 1)
        self.assertEqual(mock_adapter.prepared_records[0]["deployment_id"], "dep_mock_001")

    def test_2_successful_deployment_with_frappe_deployment_adapter_in_memory(self):
        """
        Verifies FrappeDeploymentAdapter in standalone in-memory mode works out of the box
        without passing an explicit mock adapter.
        """
        field_def = {
            "fieldname": "custom_risk_score",
            "label": "Risk Score",
            "fieldtype": "Int",
        }

        outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_inmem_001",
            field_def=field_def,
            idempotency_key="idemp_inmem_001",
            user_roles=["Finance Director"],
        )

        self.assertTrue(outcome["success"])
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "VERIFIED_CONSISTENT")
        self.assertEqual(outcome["doctype"], "Sales Order")
        self.assertEqual(outcome["fieldname"], "custom_risk_score")
        self.assertGreaterEqual(outcome["execution_time_ms"], 0.0)

    def test_3_rejection_of_unauthorized_roles(self):
        """
        Requirement 2: Test rejection of unauthorized roles.
        Only System Manager, Finance Director, and Operations Director can apply changes.
        """
        field_def = {
            "fieldname": "custom_unauthorized_field",
            "label": "Unauthorized Field",
            "fieldtype": "Data",
        }

        # Subtest 3.1: Accounts User -> Rejected
        outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_unauth_001",
            field_def=field_def,
            user_roles=["Accounts User"],
        )
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["status"], "REJECTED")
        self.assertEqual(outcome["stage"], "AUTHORIZATION")
        self.assertEqual(outcome["disposition"], "UNAUTHORIZED_ROLE")
        self.assertIn("authorized", outcome["reason"].lower())

        # Subtest 3.2: Guest -> Rejected
        outcome_guest = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_unauth_002",
            field_def=field_def,
            user_roles=["Guest"],
        )
        self.assertFalse(outcome_guest["success"])
        self.assertEqual(outcome_guest["status"], "REJECTED")
        self.assertEqual(outcome_guest["disposition"], "UNAUTHORIZED_ROLE")

        # Subtest 3.3: Empty roles -> Rejected
        outcome_empty = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_unauth_003",
            field_def=field_def,
            user_roles=[],
        )
        self.assertFalse(outcome_empty["success"])
        self.assertEqual(outcome_empty["status"], "REJECTED")

        # Subtest 3.4: raise_on_unauthorized=True raises PermissionError
        with self.assertRaises(PermissionError):
            apply_configuration_change(
                doctype="Sales Order",
                deployment_id="dep_unauth_004",
                field_def=field_def,
                user_roles=["Employee"],
                raise_on_unauthorized=True,
            )

        # Subtest 3.5: All 3 authorized roles pass authorization
        for role in ["System Manager", "Finance Director", "Operations Director"]:
            f_def = {
                "fieldname": f"custom_field_for_{role.lower().replace(' ', '_')}",
                "label": f"Field For {role}",
                "fieldtype": "Data",
            }
            res = apply_configuration_change(
                doctype="Sales Order",
                deployment_id=f"dep_auth_{role.lower().replace(' ', '_')}",
                field_def=f_def,
                user_roles=[role],
            )
            self.assertTrue(res["success"], f"Role '{role}' was unexpectedly rejected: {res}")
            self.assertEqual(res["status"], "APPLIED")

    def test_4_lock_contention_and_timeout_failure_handling(self):
        """
        Requirement 3: Test lock contention / timeout failure handling.
        MariaDB GET_LOCK returns 0 on timeout, and NULL on DB error (§7.2).
        """
        field_def = {
            "fieldname": "custom_lock_field",
            "label": "Lock Field",
            "fieldtype": "Data",
        }

        # Subtest 4.1: Lock acquisition timeout (lock_return=0)
        timeout_adapter = FrappeDeploymentAdapter(lock_return=0)
        outcome_timeout = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_timeout_001",
            field_def=field_def,
            adapter=timeout_adapter,
            user_roles=["System Manager"],
        )
        self.assertFalse(outcome_timeout["success"])
        self.assertEqual(outcome_timeout["status"], "REJECTED")
        self.assertEqual(outcome_timeout["stage"], "ACQUIRE")
        self.assertEqual(outcome_timeout["disposition"], "LOCK_CONTENTION_OR_TIMEOUT")
        self.assertIn("Lock wait timeout (0)", outcome_timeout["reason"])
        self.assertGreaterEqual(outcome_timeout["execution_time_ms"], 0.0)

        # Subtest 4.2: Database lock error (lock_return=None)
        null_adapter = FrappeDeploymentAdapter(lock_return=None)
        outcome_null = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_null_001",
            field_def=field_def,
            adapter=null_adapter,
            user_roles=["System Manager"],
        )
        self.assertFalse(outcome_null["success"])
        self.assertEqual(outcome_null["status"], "REJECTED")
        self.assertEqual(outcome_null["stage"], "ACQUIRE")
        self.assertEqual(outcome_null["disposition"], "LOCK_CONTENTION_OR_TIMEOUT")
        self.assertIn("Database lock error (NULL)", outcome_null["reason"])

    def test_5_active_concurrent_lock_contention_between_adapter_instances(self):
        """
        Tests active concurrent locking:
        When Adapter 1 holds the advisory lock on 'Sales Order', Adapter 2's attempt
        is rejected with lock contention. When Adapter 1 releases, Adapter 2 succeeds.
        """
        adapter1 = FrappeDeploymentAdapter()
        adapter2 = FrappeDeploymentAdapter()

        lock_key = make_bounded_lock_key("default", "Sales Order")
        # Adapter 1 acquires lock
        acquired = adapter1.acquire_advisory_lock(lock_key, wait_seconds=5)
        self.assertEqual(acquired, 1)

        # Adapter 2 attempts deployment on Sales Order -> fails due to contention
        field_def = {
            "fieldname": "custom_concurrent_field",
            "label": "Concurrent Field",
            "fieldtype": "Data",
        }
        outcome_contention = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_concurrent_001",
            field_def=field_def,
            adapter=adapter2,
            user_roles=["System Manager"],
        )
        self.assertFalse(outcome_contention["success"])
        self.assertEqual(outcome_contention["status"], "REJECTED")
        self.assertEqual(outcome_contention["stage"], "ACQUIRE")
        self.assertEqual(outcome_contention["disposition"], "LOCK_CONTENTION_OR_TIMEOUT")

        # Adapter 1 releases lock
        adapter1.release_advisory_lock(lock_key)

        # Adapter 2 attempts deployment again -> succeeds!
        outcome_success = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_concurrent_002",
            field_def=field_def,
            adapter=adapter2,
            user_roles=["System Manager"],
        )
        self.assertTrue(outcome_success["success"])
        self.assertEqual(outcome_success["status"], "APPLIED")

    def test_6_idempotency_caching_and_conflict_handling(self):
        """
        ADR-001 Rev 2.3 §7.1:
        Same idempotency_key with identical payload returns cached outcome.
        Same idempotency_key with modified payload returns IDEMPOTENCY_CONFLICT rejection.
        """
        field_a = {
            "fieldname": "custom_idemp_field",
            "label": "Idempotent Field",
            "fieldtype": "Data",
        }
        shared_key = "idemp_test_replay_001"

        # First run: applies successfully
        res1 = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_idemp_1",
            field_def=field_a,
            idempotency_key=shared_key,
            user_roles=["System Manager"],
        )
        self.assertTrue(res1["success"])
        self.assertEqual(res1["status"], "APPLIED")

        # Replay: identical payload -> returns cached outcome
        res2 = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_idemp_2",
            field_def=field_a,
            idempotency_key=shared_key,
            user_roles=["System Manager"],
        )
        self.assertTrue(res2["success"])
        self.assertEqual(res2["status"], "APPLIED")

        # Conflict: same idempotency key with different payload -> rejected
        field_b = {
            "fieldname": "custom_idemp_field",
            "label": "Changed Label",
            "fieldtype": "Int",
        }
        res3 = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_idemp_3",
            field_def=field_b,
            idempotency_key=shared_key,
            user_roles=["System Manager"],
        )
        self.assertFalse(res3["success"])
        self.assertEqual(res3["status"], "REJECTED")
        self.assertEqual(res3["disposition"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(res3["stage"], "IDEMPOTENCY_CHECK")

    def test_7_fail_closed_prepare_audit_error(self):
        """
        ADR-001 Rev 2.3 §8:
        Stage 3 Prepare commit must fail closed before schema write if audit DB persistence fails.
        """
        adapter = FrappeDeploymentAdapter(simulate_prepare_error=True)
        field_def = {
            "fieldname": "custom_prep_fail_field",
            "label": "Prep Fail Field",
            "fieldtype": "Data",
        }

        outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_prep_fail_001",
            field_def=field_def,
            adapter=adapter,
            user_roles=["System Manager"],
        )
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["status"], "FAILED_CLEAN")
        self.assertEqual(outcome["stage"], "PREPARE")
        self.assertIn("Fail-closed", outcome["reason"])
        self.assertFalse(adapter.apply_called)

    def test_8_json_string_serialization_and_malformed_input(self):
        """
        Tests serialized JSON payload handling from Frappe Desk RPC or REST API.
        """
        # Valid JSON string
        valid_json_str = json.dumps({
            "fieldname": "custom_json_field",
            "label": "JSON Field",
            "fieldtype": "Data",
        })
        res_valid = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_json_001",
            field_def=valid_json_str,
            user_roles=["System Manager"],
        )
        self.assertTrue(res_valid["success"])
        self.assertEqual(res_valid["status"], "APPLIED")

        # Malformed JSON string
        res_malformed = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_json_002",
            field_def="{not valid json:",
            user_roles=["System Manager"],
        )
        self.assertFalse(res_malformed["success"])
        self.assertEqual(res_malformed["status"], "REJECTED")
        self.assertEqual(res_malformed["disposition"], "INVALID_JSON_PAYLOAD")

        # Missing fieldname
        res_missing_name = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_json_003",
            field_def={"label": "Missing Name", "fieldtype": "Data"},
            user_roles=["System Manager"],
        )
        self.assertFalse(res_missing_name["success"])
        self.assertEqual(res_missing_name["status"], "REJECTED")
        self.assertEqual(res_missing_name["disposition"], "INVALID_FIELD_DEFINITION")

    def test_9_target_in_recovery_required_blocks_deployment(self):
        """
        ADR-001 Rev 2.3 §8.1:
        Target DocType with unresolved RECOVERY_REQUIRED blocks subsequent deployments.
        """
        adapter = FrappeDeploymentAdapter(target_in_recovery=True)
        field_def = {
            "fieldname": "custom_blocked_field",
            "label": "Blocked Field",
            "fieldtype": "Data",
        }

        outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_recovery_block_001",
            field_def=field_def,
            adapter=adapter,
            user_roles=["System Manager"],
        )
        self.assertFalse(outcome["success"])
        self.assertEqual(outcome["status"], "RECOVERY_REQUIRED")
        self.assertEqual(outcome["stage"], "INSPECT")
        self.assertIn("RECOVERY_REQUIRED", outcome["reason"])
        self.assertFalse(adapter.apply_called)

    def test_10_live_frappe_sql_execution_mocking(self):
        """
        Verifies FrappeDeploymentAdapter with active Frappe mock:
        - GET_LOCK with <=64 char key
        - SET SESSION lock_wait_timeout = 3
        - Reflection on information_schema.COLUMNS & tabCustom Field
        - Persistence to tabEXRP Deployment Audit
        - Native Custom Field insertion via frappe.get_doc({...}).insert()
        - RELEASE_LOCK on exit
        """
        sql_calls = []
        doc_inserts = []

        class MockFrappeDoc:
            def __init__(self, data):
                self.data = data
            def insert(self, ignore_permissions=True):
                doc_inserts.append(self.data)

        class MockFrappeDB:
            def sql(self, query, values=None):
                sql_calls.append((query.strip(), values))
                q_upper = query.upper()
                if "SELECT GET_LOCK" in q_upper:
                    return ((1,),)
                if "SELECT RELEASE_LOCK" in q_upper:
                    return ((1,),)
                if "COUNT(*)" in q_upper:
                    return ((0,),)
                if "SELECT PAYLOAD_HASH" in q_upper:
                    return ()
                if "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE" in q_upper:
                    return (
                        ("name", "varchar(140)", "NO", None),
                        ("creation", "datetime(6)", "YES", None),
                    )
                if "SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT" in q_upper:
                    return (
                        ("name", "varchar(140)", None),
                        ("creation", "datetime(6)", None),
                    )
                if "SELECT NAME, FIELDTYPE FROM `TABCUSTOM FIELD`" in q_upper:
                    # Before apply: empty; after apply: exists
                    return (("Sales Order-custom_live_field", "Data"),) if doc_inserts else ()
                if "FROM INFORMATION_SCHEMA.COLUMNS" in q_upper and "COLUMN_NAME = %S" in q_upper:
                    # Physical column reflection
                    return (("custom_live_field", "varchar(140)"),) if doc_inserts else ()
                return ()

            def commit(self):
                sql_calls.append(("COMMIT", None))

        mock_frappe = types.ModuleType("mock_frappe")
        mock_frappe.db = MockFrappeDB()
        mock_frappe.get_doc = lambda d: MockFrappeDoc(d)
        mock_frappe.clear_cache = lambda doctype: sql_calls.append((f"CLEAR_CACHE:{doctype}", None))

        adapter = FrappeDeploymentAdapter(frappe_module=mock_frappe, in_memory=False)
        self.assertFalse(adapter.in_memory)

        field_def = {
            "fieldname": "custom_live_field",
            "label": "Live Field",
            "fieldtype": "Data",
        }

        outcome = apply_configuration_change(
            doctype="Sales Order",
            deployment_id="dep_live_001",
            field_def=field_def,
            adapter=adapter,
            user_roles=["System Manager"],
        )

        self.assertTrue(outcome["success"], f"Live SQL deployment failed: {outcome}")
        self.assertEqual(outcome["status"], "APPLIED")
        self.assertEqual(outcome["disposition"], "VERIFIED_CONSISTENT")

        # Verify SQL calls made
        query_texts = [c[0] for c in sql_calls]
        self.assertTrue(any("SELECT GET_LOCK" in q for q in query_texts))
        self.assertTrue(any("SET SESSION lock_wait_timeout" in q for q in query_texts))
        self.assertTrue(any("tabEXRP Deployment Audit" in q for q in query_texts))
        self.assertTrue(any("SELECT RELEASE_LOCK" in q for q in query_texts))
        self.assertTrue(any("CLEAR_CACHE:Sales Order" in q for q in query_texts))

        # Verify GET_LOCK key length <= 64 chars
        get_lock_call = next(c for c in sql_calls if "SELECT GET_LOCK" in c[0])
        lock_key_used = get_lock_call[1][0]
        self.assertLessEqual(len(lock_key_used), 64)
        self.assertTrue(lock_key_used.startswith("exrp:v1:"))

        # Verify Custom Field doc insert
        self.assertEqual(len(doc_inserts), 1)
        self.assertEqual(doc_inserts[0]["doctype"], "Custom Field")
        self.assertEqual(doc_inserts[0]["fieldname"], "custom_live_field")
        self.assertEqual(doc_inserts[0]["dt"], "Sales Order")


if __name__ == "__main__":
    unittest.main()
