from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

from accounting_agent.contracts.model import (
    ModelRoutePolicy,
    ProcessingRegion,
    RedactionMode,
)
from accounting_agent.model_runtime import DataClassification, ModelPurpose, ProviderId


NOW = datetime(2026, 7, 11, 8, tzinfo=UTC)
HOSTED_PROVIDERS = (
    ProviderId.OPENAI,
    ProviderId.ANTHROPIC,
    ProviderId.GEMINI,
    ProviderId.CODEX_WORKSPACE,
)
LOCAL_PROVIDERS = (
    ProviderId.DETERMINISTIC,
    ProviderId.OLLAMA,
    ProviderId.LOCAL_OPENAI_COMPATIBLE,
)


def _hash(character: str) -> str:
    return character * 64


def _hosted_policy(**overrides: object) -> ModelRoutePolicy:
    values: dict[str, object] = {
        "policy_id": "model-route-policy-001",
        "policy_version": 1,
        "tenant_id": "tenant-001",
        "provider_id": ProviderId.OPENAI,
        "purposes": (ModelPurpose.EXTRACTION, ModelPurpose.EXPLANATION),
        "classifications": (
            DataClassification.PUBLIC_SYNTHETIC,
            DataClassification.CONFIDENTIAL_ACCOUNTING,
        ),
        "processing_region": ProcessingRegion.EUROPEAN_UNION,
        "max_retention_days": 0,
        "redaction_mode": RedactionMode.STRUCTURED_MINIMIZATION,
        "max_requests": 100,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 500_000,
        "max_cost_minor": 10_000,
        "cost_currency": "SEK",
        "consent_actor_id": "tenant-admin-001",
        "consented_at": NOW,
        "consent_evidence_sha256": _hash("9"),
        "dpa_sha256": _hash("a"),
        "subprocessor_review_sha256": _hash("b"),
        "evaluation_sha256": _hash("c"),
        "no_training_required": True,
        "expires_at": NOW + timedelta(days=90),
        "silent_fallback_allowed": False,
        "can_approve": False,
        "can_execute": False,
    }
    values.update(overrides)
    return ModelRoutePolicy(**values)  # type: ignore[arg-type]


def _local_policy(**overrides: object) -> ModelRoutePolicy:
    values: dict[str, object] = {
        "provider_id": ProviderId.OLLAMA,
        "classifications": (DataClassification.PRIVATE_COURSE,),
        "processing_region": ProcessingRegion.LOCAL_DEVICE,
        "redaction_mode": RedactionMode.NONE,
        "dpa_sha256": "",
        "subprocessor_review_sha256": "",
    }
    values.update(overrides)
    return _hosted_policy(**values)


class ModelRoutePolicyWireTests(unittest.TestCase):
    def test_round_trip_is_deterministic_sorted_and_immutable(self) -> None:
        policy = _hosted_policy(
            purposes=(ModelPurpose.EXPLANATION, ModelPurpose.EXTRACTION),
            classifications=(
                DataClassification.CONFIDENTIAL_ACCOUNTING,
                DataClassification.PUBLIC_SYNTHETIC,
            ),
        )
        restored = ModelRoutePolicy.from_dict(policy.to_dict())
        self.assertEqual(policy, restored)
        self.assertEqual(policy, ModelRoutePolicy.from_json(json.dumps(policy.to_dict())))
        self.assertRegex(policy.canonical_sha256(), r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            policy.canonical_sha256(),
            replace(policy, max_requests=policy.max_requests - 1).canonical_sha256(),
        )
        self.assertEqual(
            tuple(sorted(policy.purposes, key=lambda item: item.value)),
            policy.purposes,
        )
        self.assertEqual(
            tuple(sorted(policy.classifications, key=lambda item: item.value)),
            policy.classifications,
        )
        with self.assertRaises(FrozenInstanceError):
            policy.provider_id = ProviderId.GEMINI  # type: ignore[misc]

    def test_wire_rejects_unknown_missing_duplicate_and_unsupported_version(self) -> None:
        payload = _hosted_policy().to_dict()
        for mutation in (
            {**payload, "unexpected": "forged"},
            {key: value for key, value in payload.items() if key != "tenant_id"},
            {**payload, "schema_version": "v2"},
        ):
            with self.subTest(fields=tuple(mutation)):
                with self.assertRaises(ValueError):
                    ModelRoutePolicy.from_dict(mutation)
        duplicate = json.dumps(payload).replace(
            '"provider_id": "openai",',
            '"provider_id": "openai", "provider_id": "anthropic",',
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ModelRoutePolicy.from_json(duplicate)

    def test_policy_requires_exactly_one_known_provider(self) -> None:
        for provider in ("", "unknown", (ProviderId.OPENAI,), [ProviderId.OPENAI]):
            with self.subTest(provider=provider):
                with self.assertRaises(ValueError):
                    _hosted_policy(provider_id=provider)


class ModelRoutePolicyBoundaryTests(unittest.TestCase):
    def test_purpose_and_classification_sets_are_nonempty_unique_tuples(self) -> None:
        for field, value in (
            ("purposes", ()),
            ("purposes", [ModelPurpose.EXTRACTION]),
            ("purposes", (ModelPurpose.EXTRACTION, ModelPurpose.EXTRACTION)),
            ("purposes", ("unknown",)),
            ("classifications", ()),
            ("classifications", [DataClassification.PUBLIC_SYNTHETIC]),
            (
                "classifications",
                (
                    DataClassification.PUBLIC_SYNTHETIC,
                    DataClassification.PUBLIC_SYNTHETIC,
                ),
            ),
            ("classifications", ("unknown",)),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    _hosted_policy(**{field: value})

    def test_credentials_and_secrets_are_forbidden_for_every_provider(self) -> None:
        for provider in ProviderId:
            with self.subTest(provider=provider):
                values: dict[str, object] = {
                    "provider_id": provider,
                    "classifications": (DataClassification.CREDENTIAL_OR_SECRET,),
                }
                if provider in LOCAL_PROVIDERS:
                    values.update(
                        processing_region=ProcessingRegion.LOCAL_DEVICE,
                        dpa_sha256="",
                        subprocessor_review_sha256="",
                    )
                with self.assertRaisesRegex(ValueError, "credentials"):
                    _hosted_policy(**values)

    def test_private_course_material_is_local_only(self) -> None:
        for provider in LOCAL_PROVIDERS:
            with self.subTest(provider=provider):
                self.assertEqual(provider, _local_policy(provider_id=provider).provider_id)
        for provider in HOSTED_PROVIDERS:
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(ValueError, "private course"):
                    _hosted_policy(
                        provider_id=provider,
                        classifications=(DataClassification.PRIVATE_COURSE,),
                    )

    def test_hosted_routes_require_qualification_hashes_and_nonlocal_region(self) -> None:
        for provider in HOSTED_PROVIDERS:
            with self.subTest(provider=provider):
                classifications = (
                    (DataClassification.PUBLIC_SYNTHETIC,)
                    if provider is ProviderId.CODEX_WORKSPACE
                    else (
                        DataClassification.PUBLIC_SYNTHETIC,
                        DataClassification.CONFIDENTIAL_ACCOUNTING,
                    )
                )
                self.assertEqual(
                    provider,
                    _hosted_policy(
                        provider_id=provider,
                        classifications=classifications,
                    ).provider_id,
                )
                with self.assertRaises(ValueError):
                    _hosted_policy(
                        provider_id=provider,
                        classifications=classifications,
                        processing_region=ProcessingRegion.LOCAL_DEVICE,
                    )
                for field in (
                    "consent_evidence_sha256",
                    "dpa_sha256",
                    "subprocessor_review_sha256",
                    "evaluation_sha256",
                ):
                    with self.subTest(provider=provider, field=field):
                        with self.assertRaises(ValueError):
                            _hosted_policy(
                                provider_id=provider,
                                classifications=classifications,
                                **{field: ""},
                            )

    def test_policy_cannot_claim_a_provider_unsupported_classification(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not support"):
            _hosted_policy(
                provider_id=ProviderId.CODEX_WORKSPACE,
                classifications=(DataClassification.CONFIDENTIAL_ACCOUNTING,),
            )

    def test_local_routes_require_local_region_and_forbid_false_dpa_evidence(self) -> None:
        for provider in LOCAL_PROVIDERS:
            with self.subTest(provider=provider):
                with self.assertRaises(ValueError):
                    _local_policy(provider_id=provider, processing_region=ProcessingRegion.SWEDEN)
                with self.assertRaisesRegex(ValueError, "DPA"):
                    _local_policy(provider_id=provider, dpa_sha256=_hash("d"))
                with self.assertRaisesRegex(ValueError, "subprocessor"):
                    _local_policy(provider_id=provider, subprocessor_review_sha256=_hash("e"))

    def test_sensitive_hosted_routes_require_redaction(self) -> None:
        for classification in (
            DataClassification.CONFIDENTIAL_ACCOUNTING,
            DataClassification.PERSONAL_DATA,
        ):
            with self.subTest(classification=classification):
                with self.assertRaisesRegex(ValueError, "redaction"):
                    _hosted_policy(
                        classifications=(classification,),
                        redaction_mode=RedactionMode.NONE,
                    )
        public = _hosted_policy(
            classifications=(DataClassification.PUBLIC_SYNTHETIC,),
            redaction_mode=RedactionMode.NONE,
        )
        self.assertEqual(RedactionMode.NONE, public.redaction_mode)


class ModelRoutePolicyBudgetAndAuthorityTests(unittest.TestCase):
    def test_budgets_are_nonnegative_integer_minor_units(self) -> None:
        for field in (
            "max_retention_days",
            "max_requests",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_minor",
        ):
            for value in (-1, True, False, 1.0, 9_007_199_254_740_992):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        _hosted_policy(**{field: value})
            self.assertEqual(0, getattr(_hosted_policy(**{field: 0}), field))

    def test_cost_currency_and_timestamps_are_strict(self) -> None:
        for currency in ("sek", "SE", "EURO", 123):
            with self.subTest(currency=currency):
                with self.assertRaises(ValueError):
                    _hosted_policy(cost_currency=currency)
        for field, value in (
            ("consented_at", NOW.replace(tzinfo=None)),
            ("expires_at", NOW.astimezone(timezone(timedelta(hours=2)))),
            ("expires_at", NOW),
            ("expires_at", NOW - timedelta(microseconds=1)),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    _hosted_policy(**{field: value})

    def test_no_training_and_zero_authority_are_structural(self) -> None:
        for field in (
            "silent_fallback_allowed",
            "can_approve",
            "can_execute",
        ):
            for value in (True, 0, 1, "false"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        _hosted_policy(**{field: value})
        for value in (False, 0, 1, "true"):
            with self.subTest(no_training_required=value):
                with self.assertRaises(ValueError):
                    _hosted_policy(no_training_required=value)
        policy = _hosted_policy()
        self.assertFalse(policy.silent_fallback_allowed)
        self.assertFalse(policy.can_approve)
        self.assertFalse(policy.can_execute)
        self.assertTrue(policy.no_training_required)


class ModelRoutePolicySuccessorTests(unittest.TestCase):
    def test_successor_can_narrow_scope_and_strengthen_controls(self) -> None:
        previous = _hosted_policy()
        current = replace(
            previous,
            policy_version=2,
            purposes=(ModelPurpose.EXTRACTION,),
            classifications=(DataClassification.CONFIDENTIAL_ACCOUNTING,),
            max_retention_days=0,
            redaction_mode=RedactionMode.METADATA_ONLY,
            max_requests=50,
            max_input_tokens=500_000,
            max_output_tokens=250_000,
            max_cost_minor=5_000,
            consented_at=NOW + timedelta(days=1),
            consent_evidence_sha256=_hash("8"),
            expires_at=NOW + timedelta(days=60),
            dpa_sha256=_hash("d"),
            subprocessor_review_sha256=_hash("e"),
            evaluation_sha256=_hash("f"),
        )
        current.assert_successor_of(previous)

    def test_successor_requires_fresh_evidence_when_consent_changes(self) -> None:
        previous = _hosted_policy()
        for changed in (
            replace(
                previous,
                policy_version=2,
                consent_actor_id="tenant-admin-002",
            ),
            replace(
                previous,
                policy_version=2,
                consented_at=previous.consented_at + timedelta(microseconds=1),
            ),
            replace(
                previous,
                policy_version=2,
                consent_evidence_sha256=_hash("8"),
            ),
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError, "fresh consent"):
                    changed.assert_successor_of(previous)

        renewed = replace(
            previous,
            policy_version=2,
            consent_actor_id="tenant-admin-002",
            consented_at=previous.consented_at + timedelta(microseconds=1),
            consent_evidence_sha256=_hash("8"),
        )
        renewed.assert_successor_of(previous)

    def test_successor_rejects_identity_provider_version_and_scope_expansion(self) -> None:
        previous = _hosted_policy(
            purposes=(ModelPurpose.EXTRACTION,),
            classifications=(DataClassification.PUBLIC_SYNTHETIC,),
            redaction_mode=RedactionMode.PSEUDONYMIZATION,
        )
        current = replace(previous, policy_version=2)
        current.assert_successor_of(previous)
        for changed in (
            replace(current, policy_id="model-route-policy-002"),
            replace(current, tenant_id="tenant-002"),
            replace(current, provider_id=ProviderId.ANTHROPIC),
            replace(current, policy_version=3),
            replace(
                current,
                purposes=(ModelPurpose.EXTRACTION, ModelPurpose.EXPLANATION),
            ),
            replace(
                current,
                classifications=(
                    DataClassification.PUBLIC_SYNTHETIC,
                    DataClassification.INTERNAL_WORKSPACE,
                ),
            ),
            replace(current, processing_region=ProcessingRegion.SWEDEN),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    changed.assert_successor_of(previous)

    def test_successor_rejects_weaker_or_larger_limits(self) -> None:
        previous = _hosted_policy(
            max_retention_days=10,
            redaction_mode=RedactionMode.METADATA_ONLY,
        )
        current = replace(previous, policy_version=2)
        for field, value in (
            ("max_retention_days", 11),
            ("redaction_mode", RedactionMode.STRUCTURED_MINIMIZATION),
            ("max_requests", previous.max_requests + 1),
            ("max_input_tokens", previous.max_input_tokens + 1),
            ("max_output_tokens", previous.max_output_tokens + 1),
            ("max_cost_minor", previous.max_cost_minor + 1),
            ("cost_currency", "EUR"),
            ("consented_at", previous.consented_at - timedelta(microseconds=1)),
            ("expires_at", previous.expires_at + timedelta(microseconds=1)),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(current, **{field: value}).assert_successor_of(previous)
        with self.assertRaises(ValueError):
            current.assert_successor_of(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
