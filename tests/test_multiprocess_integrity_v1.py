from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from accounting_agent.approvals import (
    ApprovalBinding,
    ApprovalConflict,
    ApprovalRequest,
    ReviewerRole,
    SQLiteApprovalStore,
)
from accounting_agent.evidence import HashChainedEventLog


def _append_event_worker(arguments: tuple[str, int]) -> int:
    path, index = arguments
    event = HashChainedEventLog(path).append(
        client_id="synthetic-client",
        event_type="synthetic.multiprocess",
        actor_id=f"worker-{index % 4}",
        object_id=f"case-{index}",
        details={"index": index},
    )
    return event.sequence


def _create_approval_worker(arguments: tuple[str, ApprovalRequest]) -> str:
    database, request = arguments
    try:
        SQLiteApprovalStore(database).create_request(request)
    except ApprovalConflict:
        return "conflict"
    return "created"


class MultiprocessIntegrityTests(unittest.TestCase):
    def test_hash_chain_serializes_independent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            context = multiprocessing.get_context("spawn")
            with context.Pool(processes=4) as pool:
                sequences = pool.map(
                    _append_event_worker,
                    ((str(path), index) for index in range(16)),
                )

            verification = HashChainedEventLog(path).verify()

        self.assertTrue(verification.valid, verification.errors)
        self.assertEqual(16, verification.event_count)
        self.assertEqual(set(range(1, 17)), set(sequences))

    def test_exact_scope_approval_race_keeps_one_active_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "approvals.sqlite"
            SQLiteApprovalStore(database)
            now = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
            base = ApprovalRequest(
                request_id="approval-process-1",
                binding=ApprovalBinding(
                    client_id="synthetic-client",
                    entity_id="synthetic-entity",
                    case_id="synthetic-case",
                    proposal_hash="a" * 64,
                    evidence_hashes=("b" * 64,),
                    policy_hash="c" * 64,
                    provider_id="fixture",
                    environment="local",
                ),
                action="prepare_supplier_invoice",
                requestor_id="preparer-1",
                required_roles=(ReviewerRole.CONTROLLER,),
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
            requests = tuple(
                replace(base, request_id=f"approval-process-{index}")
                for index in range(1, 5)
            )
            context = multiprocessing.get_context("spawn")
            with context.Pool(processes=4) as pool:
                outcomes = pool.map(
                    _create_approval_worker,
                    ((str(database), request) for request in requests),
                )

        self.assertEqual(1, outcomes.count("created"), outcomes)
        self.assertEqual(3, outcomes.count("conflict"), outcomes)


if __name__ == "__main__":
    unittest.main()
