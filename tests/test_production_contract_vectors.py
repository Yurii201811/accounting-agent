from __future__ import annotations

import json
import math
import unittest
from importlib.resources import files
from pathlib import Path

from accounting_agent.contracts._wire import canonical_json_sha256
from accounting_agent.contracts.commands import (
    ApprovalDecisionCommand,
    ExternalDraftCommand,
    ExternalDraftReceipt,
)
from accounting_agent.contracts.model import ModelRoutePolicy
from accounting_agent.contracts.sync import (
    ConnectorConnection,
    SourceReconciliation,
    SyncCheckpoint,
)


ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "accounting_agent" / "contracts" / "production-contract-vectors.json"
EXPECTED_VECTOR_IDS = {
    "approval-decision-command-v1",
    "connector-connection-v1",
    "external-draft-command-v1",
    "external-draft-receipt-v1",
    "model-route-policy-v1",
    "provider-route-subset",
    "restricted-json-primitives",
    "safe-integer-boundary",
    "source-reconciliation-v1",
    "sync-checkpoint-001-v1",
    "sync-checkpoint-002-v1",
    "sync-checkpoint-chain-v1",
}


class ProductionContractVectorTests(unittest.TestCase):
    def test_vectors_are_packaged_with_the_contract_module(self) -> None:
        resource = files("accounting_agent.contracts").joinpath("production-contract-vectors.json")
        packaged = json.loads(resource.read_text(encoding="utf-8"))
        source = json.loads(VECTORS.read_text(encoding="utf-8"))

        self.assertEqual(source, packaged)

    def test_restricted_json_vectors_are_cross_language_stable(self) -> None:
        catalog = json.loads(VECTORS.read_text(encoding="utf-8"))
        self.assertEqual(1, catalog["schema_version"])
        self.assertEqual(
            "accounting-agent-restricted-json-sha256-v1",
            catalog["algorithm"],
        )
        self.assertEqual(
            EXPECTED_VECTOR_IDS,
            {vector["id"] for vector in catalog["vectors"]},
        )

        for vector in catalog["vectors"]:
            with self.subTest(vector=vector["id"]):
                encoded = json.dumps(
                    vector["value"],
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.assertEqual(vector["canonical_json"], encoded)
                self.assertEqual(
                    vector["sha256"],
                    canonical_json_sha256(vector["value"], vector["id"]),
                )

    def test_model_policy_vector_round_trips_to_the_same_digest(self) -> None:
        catalog = json.loads(VECTORS.read_text(encoding="utf-8"))
        vector = next(item for item in catalog["vectors"] if item["id"] == "model-route-policy-v1")
        policy = ModelRoutePolicy.from_dict(vector["value"])

        self.assertEqual(vector["value"], policy.to_dict())
        self.assertEqual(vector["sha256"], policy.canonical_sha256())

    def test_typed_contract_vectors_round_trip_to_the_same_digest(self) -> None:
        catalog = json.loads(VECTORS.read_text(encoding="utf-8"))
        contract_types = {
            "approval-decision-command-v1": ApprovalDecisionCommand,
            "connector-connection-v1": ConnectorConnection,
            "external-draft-command-v1": ExternalDraftCommand,
            "external-draft-receipt-v1": ExternalDraftReceipt,
            "source-reconciliation-v1": SourceReconciliation,
            "sync-checkpoint-001-v1": SyncCheckpoint,
            "sync-checkpoint-002-v1": SyncCheckpoint,
        }
        for vector in catalog["vectors"]:
            contract_type = contract_types.get(vector["id"])
            if contract_type is None:
                continue
            with self.subTest(vector=vector["id"]):
                contract = contract_type.from_dict(vector["value"])
                self.assertEqual(vector["value"], contract.to_dict())
                self.assertEqual(vector["sha256"], contract.canonical_sha256())

    def test_checkpoint_successor_chain_and_reconciliation_vectors_bind_exactly(self) -> None:
        catalog = json.loads(VECTORS.read_text(encoding="utf-8"))
        vectors = {vector["id"]: vector for vector in catalog["vectors"]}
        first = SyncCheckpoint.from_dict(vectors["sync-checkpoint-001-v1"]["value"])
        second = SyncCheckpoint.from_dict(vectors["sync-checkpoint-002-v1"]["value"])
        chain = vectors["sync-checkpoint-chain-v1"]

        self.assertEqual(
            [first.canonical_sha256(), second.canonical_sha256()],
            chain["value"]["checkpoint_sha256"],
        )
        self.assertEqual(chain["sha256"], SyncCheckpoint.chain_sha256((first, second)))

        reconciliation = SourceReconciliation.from_dict(
            vectors["source-reconciliation-v1"]["value"]
        )
        reconciliation.assert_matches_checkpoint(second)
        self.assertEqual(chain["sha256"], reconciliation.checkpoint_chain_sha256)

    def test_safe_receipt_vector_is_bound_to_the_exact_draft_command(self) -> None:
        catalog = json.loads(VECTORS.read_text(encoding="utf-8"))
        vectors = {vector["id"]: vector for vector in catalog["vectors"]}
        command = ExternalDraftCommand.from_dict(vectors["external-draft-command-v1"]["value"])
        receipt = ExternalDraftReceipt.from_dict(vectors["external-draft-receipt-v1"]["value"])

        receipt.assert_matches_command(command)
        self.assertEqual(receipt.payload_sha256, receipt.readback_sha256)
        self.assertFalse(receipt.is_frozen_for(command))

    def test_floats_and_nonfinite_numbers_remain_forbidden(self) -> None:
        for value in (1.0, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "permits only"):
                    canonical_json_sha256({"amount": value}, "test vector")

    def test_integers_are_limited_to_the_cross_language_safe_range(self) -> None:
        catalog = json.loads(VECTORS.read_text(encoding="utf-8"))
        vector = next(item for item in catalog["vectors"] if item["id"] == "safe-integer-boundary")
        maximum = 9_007_199_254_740_991
        self.assertEqual({"maximum": maximum, "minimum": -maximum}, vector["value"])
        self.assertEqual(
            vector["sha256"],
            canonical_json_sha256(vector["value"], "safe integer boundary"),
        )
        for value in (maximum + 1, -(maximum + 1)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "interoperable"):
                    canonical_json_sha256({"amount": value}, "test vector")


if __name__ == "__main__":
    unittest.main()
