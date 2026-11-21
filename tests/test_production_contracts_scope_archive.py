from __future__ import annotations

import importlib.util
import json
import unittest
from base64 import b64encode
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone

from accounting_agent.contracts import (
    AuthenticationStrength,
    ArchiveManifestV1,
    ArchiveProcessingEntry,
    ArchiveSignature,
    DocumentClassification,
    DocumentProvenance,
    DocumentRecord,
    LegalHoldState,
    MalwareStatus,
    MembershipRole,
    PolicyPurpose,
    PolicyVersion,
    ProcessingAction,
    ProvenanceSource,
    QuarantineState,
    RecordClass,
    RetentionClass,
    SignatureAlgorithm,
    StorageRegion,
    TenantContext,
)
from accounting_agent.contracts import _wire
import accounting_agent


EXPECTED_ROOT_EXPORTS = (
    "AuthenticationStrength",
    "ArchiveManifestV1",
    "ArchiveProcessingEntry",
    "ArchiveSignature",
    "DocumentClassification",
    "DocumentProvenance",
    "DocumentRecord",
    "LegalHoldState",
    "MalwareStatus",
    "MembershipRole",
    "PolicyPurpose",
    "PolicyVersion",
    "ProcessingAction",
    "ProvenanceSource",
    "QuarantineState",
    "RecordClass",
    "RetentionClass",
    "SignatureAlgorithm",
    "StorageRegion",
    "TenantContext",
)


def _hash(character: str) -> str:
    return character * 64


def _provenance() -> DocumentProvenance:
    return DocumentProvenance(
        source=ProvenanceSource.DIRECT_UPLOAD,
        source_reference="upload-001",
        source_sha256=_hash("a"),
        captured_at=datetime(2026, 1, 2, 8, tzinfo=UTC),
        captured_by_actor_id="actor-001",
    )


def _document(**overrides: object) -> DocumentRecord:
    values: dict[str, object] = {
        "document_id": "document-001",
        "record_version": 1,
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "record_class": RecordClass.SUPPLIER_INVOICE,
        "classification": DocumentClassification.CONFIDENTIAL,
        "malware_status": MalwareStatus.CLEAN,
        "quarantine_state": QuarantineState.RELEASED,
        "content_sha256": _hash("a"),
        "media_type": "application/pdf",
        "size_bytes": 4096,
        "storage_region": StorageRegion.SWEDEN,
        "provenance": _provenance(),
        "retention_class": RetentionClass.SWEDISH_ACCOUNTING,
        "retention_basis_date": date(2026, 12, 31),
        "retain_until": date(2033, 12, 31),
        "legal_hold_state": LegalHoldState.NONE,
        "recorded_at": datetime(2026, 1, 2, 9, tzinfo=UTC),
    }
    values.update(overrides)
    return DocumentRecord(**values)  # type: ignore[arg-type]


def _history(
    *, legal_hold_state: LegalHoldState = LegalHoldState.NONE
) -> tuple[ArchiveProcessingEntry, ...]:
    entries = [
        ArchiveProcessingEntry(
            sequence=1,
            action=ProcessingAction.INGESTED,
            occurred_at=datetime(2026, 1, 2, 9, tzinfo=UTC),
            actor_id="worker-001",
            processor="accounting-agent-intake",
            processor_version="1.0.0",
            input_sha256=_hash("a"),
            output_sha256=_hash("a"),
        ),
        ArchiveProcessingEntry(
            sequence=2,
            action=ProcessingAction.MALWARE_SCANNED,
            occurred_at=datetime(2026, 1, 2, 9, 1, tzinfo=UTC),
            actor_id="worker-001",
            processor="malware-scanner",
            processor_version="2026.01",
            input_sha256=_hash("a"),
            output_sha256=_hash("a"),
        ),
        ArchiveProcessingEntry(
            sequence=3,
            action=ProcessingAction.PRESENTATION_CREATED,
            occurred_at=datetime(2026, 1, 2, 9, 2, tzinfo=UTC),
            actor_id="worker-001",
            processor="pdfa-presenter",
            processor_version="1.0.0",
            input_sha256=_hash("a"),
            output_sha256=_hash("b"),
        ),
        ArchiveProcessingEntry(
            sequence=4,
            action=ProcessingAction.ARCHIVE_ACCEPTED,
            occurred_at=datetime(2026, 1, 2, 9, 3, tzinfo=UTC),
            actor_id="archive-001",
            processor="archive-policy",
            processor_version="se-2026.1",
            input_sha256=_hash("b"),
            output_sha256=_hash("b"),
        ),
    ]
    if legal_hold_state is not LegalHoldState.NONE:
        entries.append(
            ArchiveProcessingEntry(
                sequence=5,
                action=ProcessingAction.LEGAL_HOLD_PLACED,
                occurred_at=datetime(2026, 1, 3, 9, tzinfo=UTC),
                actor_id="archive-admin-001",
                processor="legal-hold-policy",
                processor_version="1.0.0",
                input_sha256=_hash("b"),
                output_sha256=_hash("b"),
            )
        )
    if legal_hold_state is LegalHoldState.RELEASED:
        entries.append(
            ArchiveProcessingEntry(
                sequence=6,
                action=ProcessingAction.LEGAL_HOLD_RELEASED,
                occurred_at=datetime(2026, 1, 4, 9, tzinfo=UTC),
                actor_id="archive-admin-002",
                processor="legal-hold-policy",
                processor_version="1.0.0",
                input_sha256=_hash("b"),
                output_sha256=_hash("b"),
            )
        )
    return tuple(entries)


def _policies() -> tuple[PolicyVersion, ...]:
    return (
        PolicyVersion(
            policy_id="archive-retention-se",
            purpose=PolicyPurpose.RETENTION,
            version="2026.1",
            policy_sha256=_hash("c"),
        ),
    )


def _signatures(
    signed_payload_sha256: str,
    signed_at: datetime,
) -> tuple[ArchiveSignature, ...]:
    return (
        ArchiveSignature(
            key_reference="kms-key-001",
            algorithm=SignatureAlgorithm.ECDSA_P256_SHA256,
            signed_at=signed_at,
            signed_payload_sha256=signed_payload_sha256,
            signature_base64=b64encode(b"s" * 64).decode("ascii"),
        ),
    )


def _manifest_unsigned_payload(values: dict[str, object]) -> dict[str, object]:
    provenance = values["provenance"]
    history = values["processing_history"]
    policies = values["policy_versions"]
    assert isinstance(provenance, DocumentProvenance)
    assert isinstance(history, tuple)
    assert isinstance(policies, tuple)
    return {
        "schema_version": "v1",
        "manifest_id": values["manifest_id"],
        "revision": values["revision"],
        "tenant_id": values["tenant_id"],
        "client_id": values["client_id"],
        "legal_entity_id": values["legal_entity_id"],
        "document_id": values["document_id"],
        "document_record_sha256": values["document_record_sha256"],
        "record_class": RecordClass(values["record_class"]).value,
        "classification": DocumentClassification(values["classification"]).value,
        "malware_status": MalwareStatus(values["malware_status"]).value,
        "quarantine_state": QuarantineState(values["quarantine_state"]).value,
        "storage_region": StorageRegion(values["storage_region"]).value,
        "original_sha256": values["original_sha256"],
        "presentation_sha256": values["presentation_sha256"],
        "provenance": provenance.to_dict(),
        "processing_history": [entry.to_dict() for entry in history],
        "policy_versions": [policy.to_dict() for policy in policies],
        "retention_class": RetentionClass(values["retention_class"]).value,
        "retention_basis_date": values["retention_basis_date"].isoformat(),  # type: ignore[union-attr]
        "retain_until": values["retain_until"].isoformat(),  # type: ignore[union-attr]
        "legal_hold_state": LegalHoldState(values["legal_hold_state"]).value,
        "created_at": values["created_at"].isoformat().replace("+00:00", "Z"),  # type: ignore[union-attr]
    }


def _manifest(**overrides: object) -> ArchiveManifestV1:
    document = _document()
    values: dict[str, object] = {
        "manifest_id": "manifest-001",
        "revision": 1,
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "document_id": "document-001",
        "document_record_sha256": document.canonical_sha256(),
        "record_class": RecordClass.SUPPLIER_INVOICE,
        "classification": DocumentClassification.CONFIDENTIAL,
        "malware_status": MalwareStatus.CLEAN,
        "quarantine_state": QuarantineState.RELEASED,
        "storage_region": StorageRegion.SWEDEN,
        "original_sha256": _hash("a"),
        "presentation_sha256": _hash("b"),
        "provenance": _provenance(),
        "processing_history": _history(),
        "policy_versions": _policies(),
        "retention_class": RetentionClass.SWEDISH_ACCOUNTING,
        "retention_basis_date": date(2026, 12, 31),
        "retain_until": date(2033, 12, 31),
        "legal_hold_state": LegalHoldState.NONE,
        "created_at": datetime(2026, 1, 2, 9, 4, tzinfo=UTC),
    }
    values.update(overrides)
    if "signatures" not in overrides:
        try:
            digest = ArchiveManifestV1.signing_payload_sha256(_manifest_unsigned_payload(values))
        except (AssertionError, AttributeError, TypeError, ValueError):
            digest = _hash("0")
        created_at = values["created_at"]
        assert isinstance(created_at, datetime)
        values["signatures"] = _signatures(digest, created_at + timedelta(minutes=1))
    return ArchiveManifestV1(**values)  # type: ignore[arg-type]


def _assert_manifest_successor(
    current: ArchiveManifestV1,
    previous: ArchiveManifestV1,
    *,
    previous_document: DocumentRecord | None = None,
    document: DocumentRecord | None = None,
) -> None:
    current.assert_successor_of(
        previous,
        previous_document=previous_document or _document(),
        document=document or _document(),
    )


class ProductionContractPackageTests(unittest.TestCase):
    def test_contract_package_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("accounting_agent.contracts"))

    def test_contracts_are_additive_root_exports(self) -> None:
        for export_name in EXPECTED_ROOT_EXPORTS:
            with self.subTest(export=export_name):
                self.assertIn(export_name, accounting_agent.__all__)
                self.assertIs(
                    getattr(accounting_agent, export_name),
                    getattr(importlib.import_module("accounting_agent.contracts"), export_name),
                )


class TenantContextContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = TenantContext(
            tenant_id="tenant-001",
            client_id="client-001",
            legal_entity_id="entity-se-001",
            actor_id="actor-001",
            roles=(MembershipRole.PREPARER, MembershipRole.REVIEWER),
            authentication_strength=AuthenticationStrength.MULTI_FACTOR,
            request_id="request-001",
        )

    def test_context_is_frozen_and_uses_an_immutable_role_tuple(self) -> None:
        self.assertIsInstance(self.context.roles, tuple)
        with self.assertRaises(FrozenInstanceError):
            self.context.actor_id = "actor-002"  # type: ignore[misc]

        with self.assertRaisesRegex(ValueError, "roles must be a tuple"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="actor-001",
                roles=[MembershipRole.PREPARER],  # type: ignore[arg-type]
                authentication_strength=AuthenticationStrength.MULTI_FACTOR,
                request_id="request-001",
            )

    def test_context_rejects_unknown_or_ambiguous_authority(self) -> None:
        with self.assertRaisesRegex(ValueError, "authentication_strength"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="actor-001",
                roles=(MembershipRole.PREPARER,),
                authentication_strength="trusted-ish",  # type: ignore[arg-type]
                request_id="request-001",
            )

        with self.assertRaisesRegex(ValueError, "unknown membership role"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="actor-001",
                roles=("super_admin",),  # type: ignore[arg-type]
                authentication_strength=AuthenticationStrength.MULTI_FACTOR,
                request_id="request-001",
            )

        with self.assertRaisesRegex(ValueError, "service_worker role must be exclusive"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="worker-001",
                roles=(MembershipRole.SERVICE_WORKER, MembershipRole.TENANT_ADMIN),
                authentication_strength=AuthenticationStrength.SERVICE_CREDENTIAL,
                request_id="request-001",
            )

        with self.assertRaisesRegex(ValueError, "service_worker requires service_credential"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="worker-001",
                roles=(MembershipRole.SERVICE_WORKER,),
                authentication_strength=AuthenticationStrength.MULTI_FACTOR,
                request_id="request-001",
            )
        with self.assertRaisesRegex(ValueError, "service_credential requires service_worker"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="actor-001",
                roles=(MembershipRole.PREPARER,),
                authentication_strength=AuthenticationStrength.SERVICE_CREDENTIAL,
                request_id="request-001",
            )

    def test_context_rejects_weak_or_duplicate_scope_data(self) -> None:
        values = self.context.to_dict()
        for field_name, bad_value in (
            ("tenant_id", ".."),
            ("client_id", "client\u200bother"),
            ("legal_entity_id", " entity-001"),
            ("actor_id", "unknown"),
            ("request_id", "request\nother"),
        ):
            with self.subTest(field=field_name):
                invalid = dict(values)
                invalid[field_name] = bad_value
                with self.assertRaises(ValueError):
                    TenantContext.from_dict(invalid)

        with self.assertRaisesRegex(ValueError, "roles must not contain duplicates"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="actor-001",
                roles=(MembershipRole.AUDITOR, MembershipRole.AUDITOR),
                authentication_strength=AuthenticationStrength.MULTI_FACTOR,
                request_id="request-001",
            )
        with self.assertRaisesRegex(ValueError, "roles must not be empty"):
            TenantContext(
                tenant_id="tenant-001",
                client_id="client-001",
                legal_entity_id="entity-se-001",
                actor_id="actor-001",
                roles=(),
                authentication_strength=AuthenticationStrength.MULTI_FACTOR,
                request_id="request-001",
            )

    def test_context_wire_round_trip_is_versioned_and_strict(self) -> None:
        payload = self.context.to_dict()
        self.assertEqual("v1", payload["schema_version"])
        self.assertEqual(self.context, TenantContext.from_dict(payload))

        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            TenantContext.from_dict({**payload, "schema_version": "v2"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            TenantContext.from_dict({**payload, "body_scope_override": "entity-evil"})
        with self.assertRaisesRegex(ValueError, "roles must be a wire array"):
            TenantContext.from_dict({**payload, "roles": "preparer"})

        duplicate_json = json.dumps(payload).replace(
            '"tenant_id": "tenant-001",',
            '"tenant_id": "tenant-001", "tenant_id": "tenant-evil",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            TenantContext.from_json(duplicate_json)

    def test_context_reuses_unicode_canonical_identity_rules(self) -> None:
        context = TenantContext(
            tenant_id="t",
            client_id="klient-a\u030ar",
            legal_entity_id="é",
            actor_id="a",
            roles=(MembershipRole.REVIEWER, MembershipRole.PREPARER),
            authentication_strength=AuthenticationStrength.MULTI_FACTOR,
            request_id="r",
        )
        self.assertEqual("klient-år", context.client_id)
        self.assertEqual("t", context.tenant_id)
        self.assertEqual("é", context.legal_entity_id)
        self.assertEqual(
            (MembershipRole.PREPARER, MembershipRole.REVIEWER),
            context.roles,
        )


class DocumentRecordContractTests(unittest.TestCase):
    def test_document_is_frozen_metadata_only_and_round_trips_strict_wire_data(self) -> None:
        document = _document()
        self.assertEqual(_hash("a"), document.provenance.source_sha256)
        self.assertFalse(
            {"bytes", "content", "document_text", "file_path", "ocr_text", "raw_text"}
            & set(document.__dataclass_fields__)
        )
        with self.assertRaises(FrozenInstanceError):
            document.content_sha256 = _hash("f")  # type: ignore[misc]

        payload = document.to_dict()
        self.assertEqual("v1", payload["schema_version"])
        self.assertEqual(document, DocumentRecord.from_dict(payload))
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            DocumentRecord.from_dict({**payload, "raw_text": "invoice body"})

    def test_document_fails_closed_on_unknown_values_hashes_and_provenance(self) -> None:
        for field_name, bad_value in (
            ("record_class", "payroll_record"),
            ("classification", "mostly_secret"),
            ("malware_status", "probably_clean"),
            ("quarantine_state", "maybe_released"),
            ("storage_region", "anywhere"),
            ("retention_class", "keep_for_a_while"),
            ("legal_hold_state", "maybe"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    _document(**{field_name: bad_value})

        with self.assertRaisesRegex(ValueError, "content_sha256"):
            _document(content_sha256="A" * 64)
        with self.assertRaisesRegex(ValueError, "must match provenance"):
            _document(content_sha256=_hash("e"))
        with self.assertRaisesRegex(ValueError, "provenance"):
            _document(provenance=None)

    def test_document_requires_utc_and_a_valid_retention_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "recorded_at must be UTC"):
            _document(recorded_at=datetime(2026, 1, 2, 9))
        with self.assertRaisesRegex(ValueError, "captured_at must be an ISO 8601 UTC"):
            _provenance().from_dict(
                {
                    **_provenance().to_dict(),
                    "captured_at": "2026-01-02T09:00:00+01:00",
                }
            )
        with self.assertRaisesRegex(ValueError, "Swedish accounting retention"):
            _document(retain_until=date(2033, 12, 30))

        with self.assertRaisesRegex(ValueError, "must follow its basis date"):
            _document(
                retention_class=RetentionClass.POLICY_DEFINED,
                retention_basis_date=date(2026, 1, 2),
                retain_until=date(2026, 1, 2),
            )
        policy_defined = _document(
            retention_class=RetentionClass.POLICY_DEFINED,
            retention_basis_date=date(2026, 1, 2),
            retain_until=date(2026, 1, 3),
        )
        self.assertEqual(date(2026, 1, 3), policy_defined.retain_until)

    def test_document_lifecycle_is_monotonic_and_separates_scan_from_quarantine(self) -> None:
        pending = _document(
            classification=DocumentClassification.INTERNAL,
            malware_status=MalwareStatus.PENDING,
            quarantine_state=QuarantineState.HELD,
            storage_region=StorageRegion.LOCAL_DEVICE,
        )
        accepted = _document(
            record_version=2,
            classification=DocumentClassification.CONFIDENTIAL,
            malware_status=MalwareStatus.CLEAN,
            quarantine_state=QuarantineState.RELEASED,
            storage_region=StorageRegion.SWEDEN,
        )
        accepted.assert_successor_of(pending)

        rescan = _document(
            malware_status=MalwareStatus.SCAN_FAILED,
            quarantine_state=QuarantineState.HELD,
        )
        recovered = _document(record_version=2)
        recovered.assert_successor_of(rescan)

        with self.assertRaisesRegex(ValueError, "only clean documents"):
            _document(
                malware_status=MalwareStatus.INFECTED,
                quarantine_state=QuarantineState.RELEASED,
            )
        with self.assertRaisesRegex(ValueError, "terminal malware status"):
            _document(
                record_version=3,
                malware_status=MalwareStatus.SCAN_FAILED,
                quarantine_state=QuarantineState.HELD,
            ).assert_successor_of(accepted)
        with self.assertRaisesRegex(ValueError, "classification cannot be lowered"):
            _document(
                record_version=3,
                classification=DocumentClassification.INTERNAL,
            ).assert_successor_of(accepted)
        with self.assertRaisesRegex(ValueError, "storage region"):
            _document(
                record_version=3,
                storage_region=StorageRegion.LOCAL_DEVICE,
            ).assert_successor_of(accepted)

    def test_document_successors_cannot_shorten_retention_or_clear_a_hold(self) -> None:
        original = _document(retain_until=date(2035, 12, 31))
        held = _document(
            record_version=2,
            retain_until=date(2035, 12, 31),
            legal_hold_state=LegalHoldState.ACTIVE,
            recorded_at=datetime(2026, 1, 3, 9, tzinfo=UTC),
        )
        held.assert_successor_of(original)

        shortened = _document(
            record_version=3,
            retain_until=date(2034, 12, 31),
            legal_hold_state=LegalHoldState.ACTIVE,
            recorded_at=datetime(2026, 1, 4, 9, tzinfo=UTC),
        )
        with self.assertRaisesRegex(ValueError, "retention cannot be shortened"):
            shortened.assert_successor_of(held)

        cleared = _document(
            record_version=3,
            retain_until=date(2035, 12, 31),
            legal_hold_state=LegalHoldState.NONE,
            recorded_at=datetime(2026, 1, 4, 9, tzinfo=UTC),
        )
        with self.assertRaisesRegex(ValueError, "legal hold cannot be cleared"):
            cleared.assert_successor_of(held)


class ArchiveManifestContractTests(unittest.TestCase):
    def test_manifest_signatures_bind_every_unsigned_field_and_exact_document_record(self) -> None:
        document = _document()
        manifest = _manifest()
        self.assertEqual(document.canonical_sha256(), manifest.document_record_sha256)
        unsigned_payload = manifest.unsigned_payload_dict()
        signing_hash = ArchiveManifestV1.signing_payload_sha256(unsigned_payload)
        self.assertEqual(
            {signing_hash},
            {signature.signed_payload_sha256 for signature in manifest.signatures},
        )

        for field_name, field_value in unsigned_payload.items():
            mutated = deepcopy(unsigned_payload)
            if isinstance(field_value, str):
                mutated[field_name] = field_value + "-mutated"
            elif isinstance(field_value, int):
                mutated[field_name] = field_value + 1
            elif isinstance(field_value, list):
                mutated[field_name] = [*field_value, "mutation"]
            elif isinstance(field_value, dict):
                mutated[field_name] = {**field_value, "mutation": "present"}
            else:  # pragma: no cover - the strict payload has no other value shapes.
                self.fail(f"unsupported unsigned payload field shape: {field_name}")
            with self.subTest(field=field_name):
                self.assertNotEqual(
                    signing_hash,
                    ArchiveManifestV1.signing_payload_sha256(mutated),
                )

        with self.assertRaisesRegex(ValueError, "signed payload hash"):
            replace(manifest, client_id="client-evil")

    def test_manifest_is_frozen_tuple_based_and_round_trips_strict_wire_data(self) -> None:
        manifest = _manifest()
        self.assertIsInstance(manifest.processing_history, tuple)
        self.assertIsInstance(manifest.policy_versions, tuple)
        self.assertIsInstance(manifest.signatures, tuple)
        self.assertEqual(manifest, ArchiveManifestV1.from_dict(manifest.to_dict()))
        manifest.assert_matches_document(_document())

        for field_name in ("processing_history", "policy_versions", "signatures"):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, f"{field_name} must be a tuple"):
                    _manifest(**{field_name: list(getattr(manifest, field_name))})

    def test_manifest_requires_clean_malware_and_complete_typed_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "clean malware status"):
            _manifest(malware_status=MalwareStatus.PENDING)
        for field_name in ("processing_history", "policy_versions", "signatures"):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, f"{field_name} must not be empty"):
                    _manifest(**{field_name: ()})

        broken_chain = list(_history())
        broken_chain[2] = replace(broken_chain[2], input_sha256=_hash("e"))
        with self.assertRaisesRegex(ValueError, "processing hash chain"):
            _manifest(processing_history=tuple(broken_chain))

    def test_manifest_hold_state_requires_append_only_processing_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "LEGAL_HOLD_PLACED"):
            _manifest(legal_hold_state=LegalHoldState.ACTIVE)
        with self.assertRaisesRegex(ValueError, "LEGAL_HOLD_RELEASED"):
            _manifest(
                legal_hold_state=LegalHoldState.RELEASED,
                processing_history=_history(legal_hold_state=LegalHoldState.ACTIVE),
                created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
            )

        released = _manifest(
            legal_hold_state=LegalHoldState.RELEASED,
            processing_history=_history(legal_hold_state=LegalHoldState.RELEASED),
            created_at=datetime(2026, 1, 4, 9, 1, tzinfo=UTC),
        )
        self.assertEqual(LegalHoldState.RELEASED, released.legal_hold_state)

    def test_manifest_successor_extends_history_and_never_shortens_retention(self) -> None:
        original = _manifest(retain_until=date(2035, 12, 31))
        held = _manifest(
            revision=2,
            retain_until=date(2035, 12, 31),
            processing_history=_history(legal_hold_state=LegalHoldState.ACTIVE),
            legal_hold_state=LegalHoldState.ACTIVE,
            created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
        )
        _assert_manifest_successor(held, original)

        invalid = _manifest(
            revision=3,
            processing_history=held.processing_history,
            legal_hold_state=LegalHoldState.ACTIVE,
            retain_until=date(2034, 12, 31),
            created_at=datetime(2026, 1, 4, 9, 1, tzinfo=UTC),
        )
        with self.assertRaisesRegex(ValueError, "retention cannot be shortened"):
            _assert_manifest_successor(invalid, held)

    def test_retention_extension_requires_new_lineage_and_policy_evidence(self) -> None:
        original = _manifest()
        with self.assertRaisesRegex(ValueError, "RETENTION_EXTENDED"):
            _assert_manifest_successor(
                _manifest(revision=2, retain_until=date(2034, 12, 31)),
                original,
            )

        extension_event = ArchiveProcessingEntry(
            sequence=5,
            action=ProcessingAction.RETENTION_EXTENDED,
            occurred_at=datetime(2026, 1, 3, 9, tzinfo=UTC),
            actor_id="archive-001",
            processor="archive-policy",
            processor_version="se-2027.1",
            input_sha256=_hash("b"),
            output_sha256=_hash("b"),
        )
        missing_policy = _manifest(
            revision=2,
            retain_until=date(2034, 12, 31),
            processing_history=(*_history(), extension_event),
            created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
        )
        with self.assertRaisesRegex(ValueError, "policy evidence"):
            _assert_manifest_successor(missing_policy, original)

        unrelated_policy = PolicyVersion(
            policy_id="ui-color-policy",
            purpose=PolicyPurpose.PROCESSING,
            version="2027.1",
            policy_sha256=_hash("f"),
        )
        unrelated = _manifest(
            revision=2,
            retain_until=date(2034, 12, 31),
            processing_history=(*_history(), extension_event),
            policy_versions=(*_policies(), unrelated_policy),
            created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
        )
        with self.assertRaisesRegex(ValueError, "policy evidence"):
            _assert_manifest_successor(unrelated, original)

        extension_policy = PolicyVersion(
            policy_id="archive-retention-se",
            purpose=PolicyPurpose.RETENTION,
            version="2027.1",
            policy_sha256=_hash("e"),
        )
        extended = _manifest(
            revision=2,
            retain_until=date(2034, 12, 31),
            processing_history=(*_history(), extension_event),
            policy_versions=(*_policies(), extension_policy),
            created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
        )
        _assert_manifest_successor(extended, original)

    def test_manifest_successor_binds_the_exact_document_lifecycle_chain(self) -> None:
        previous_document = _document(
            classification=DocumentClassification.INTERNAL,
            storage_region=StorageRegion.LOCAL_DEVICE,
        )
        previous = _manifest(
            classification=DocumentClassification.INTERNAL,
            storage_region=StorageRegion.LOCAL_DEVICE,
            document_record_sha256=previous_document.canonical_sha256(),
        )
        document = _document(
            record_version=2,
            classification=DocumentClassification.CONFIDENTIAL,
            storage_region=StorageRegion.SWEDEN,
            legal_hold_state=LegalHoldState.ACTIVE,
            recorded_at=datetime(2026, 1, 3, 8, tzinfo=UTC),
        )
        current = _manifest(
            revision=2,
            classification=DocumentClassification.CONFIDENTIAL,
            storage_region=StorageRegion.SWEDEN,
            document_record_sha256=document.canonical_sha256(),
            processing_history=_history(legal_hold_state=LegalHoldState.ACTIVE),
            legal_hold_state=LegalHoldState.ACTIVE,
            created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
        )
        current.assert_matches_document(document)
        _assert_manifest_successor(
            current,
            previous,
            previous_document=previous_document,
            document=document,
        )

    def test_archive_contracts_reject_non_utc_signatures_and_invalid_versions(self) -> None:
        with self.assertRaisesRegex(ValueError, "signed_at must be UTC"):
            ArchiveSignature(
                key_reference="kms-key-001",
                algorithm=SignatureAlgorithm.ECDSA_P256_SHA256,
                signed_at=datetime(2026, 1, 2, 9, tzinfo=timezone(timedelta(hours=1))),
                signed_payload_sha256=_hash("d"),
                signature_base64=b64encode(b"s" * 64).decode("ascii"),
            )
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            ArchiveManifestV1.from_dict({**_manifest().to_dict(), "schema_version": "v2"})


class ContractValidatorCoverageTests(unittest.TestCase):
    def test_private_wire_validators_reject_noncanonical_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "wire object"):
            _wire.require_wire_object([], contract_name="Example", expected_fields=frozenset())
        with self.assertRaisesRegex(ValueError, "missing fields"):
            _wire.require_wire_object(
                {}, contract_name="Example", expected_fields=frozenset({"required"})
            )
        for value in (None, "", " padded", "line\nbreak"):
            with self.subTest(text=value):
                with self.assertRaises(ValueError):
                    _wire.require_nonempty_text(value, "value")
        for value in (True, "1", -1):
            with self.subTest(integer=value):
                with self.assertRaises(ValueError):
                    _wire.require_positive_integer(value, "value", allow_zero=True)
        for value in (None, "not-a-time"):
            with self.subTest(timestamp=value):
                with self.assertRaises(ValueError):
                    _wire.parse_wire_datetime(value, "timestamp")
        for value in ("2026-01-02 09:00:00+00:00", "2026-01-02T09:00:00+00:00"):
            with self.subTest(timestamp=value):
                with self.assertRaises(ValueError):
                    _wire.parse_wire_datetime(value, "timestamp")
        with self.assertRaisesRegex(ValueError, "must be a date"):
            _wire.require_date(datetime(2026, 1, 1, tzinfo=UTC), "day")
        for value in (None, "2026-99-99"):
            with self.subTest(day=value):
                with self.assertRaises(ValueError):
                    _wire.parse_wire_date(value, "day")
        with self.assertRaises(ValueError):
            _wire.parse_wire_date("20260102", "day")
        with self.assertRaises(ValueError):
            _wire.require_nonempty_text("visible\u202einvisible", "value")
        for value in (None, "%%%", b64encode(b"short").decode("ascii")):
            with self.subTest(signature=value):
                with self.assertRaises(ValueError):
                    _wire.require_base64(value, "signature", minimum_bytes=32)

    def test_document_successor_and_metadata_failure_paths(self) -> None:
        for media_type in ("pdf", "application /pdf", "Application/PDF", "application/pdf;v=1"):
            with self.subTest(media_type=media_type):
                with self.assertRaisesRegex(ValueError, "canonical media type"):
                    _document(media_type=media_type)
        with self.assertRaisesRegex(ValueError, "cannot precede provenance"):
            _document(recorded_at=datetime(2026, 1, 2, 7, tzinfo=UTC))

        previous = _document()
        with self.assertRaisesRegex(ValueError, "previous must"):
            previous.assert_successor_of(object())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "advance by exactly one"):
            _document(record_version=3).assert_successor_of(previous)
        with self.assertRaisesRegex(ValueError, "cannot change document_id"):
            _document(document_id="document-002", record_version=2).assert_successor_of(previous)
        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            _document(
                record_version=2,
                recorded_at=datetime(2026, 1, 2, 8, 30, tzinfo=UTC),
            ).assert_successor_of(previous)
        released = _document(legal_hold_state=LegalHoldState.RELEASED)
        with self.assertRaisesRegex(ValueError, "cannot regress to none"):
            _document(record_version=2).assert_successor_of(released)

    def test_manifest_rejects_inconsistent_typed_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "provenance"):
            _manifest(provenance=None)
        with self.assertRaisesRegex(ValueError, "must match provenance"):
            _manifest(original_sha256=_hash("e"))
        with self.assertRaisesRegex(ValueError, "cannot precede processing"):
            _manifest(created_at=datetime(2026, 1, 2, 9, 2, tzinfo=UTC))
        with self.assertRaisesRegex(ValueError, "invalid typed record"):
            _manifest(processing_history=(object(),))
        with self.assertRaisesRegex(ValueError, "unique policy"):
            _manifest(policy_versions=(_policies()[0], _policies()[0]))
        processing_policy = PolicyVersion(
            policy_id="document-processing",
            purpose=PolicyPurpose.PROCESSING,
            version="2026.1",
            policy_sha256=_hash("f"),
        )
        with self.assertRaisesRegex(ValueError, "retention-purpose"):
            _manifest(policy_versions=(processing_policy,))
        base_signature = _manifest().signatures[0]
        with self.assertRaisesRegex(ValueError, "unique key"):
            _manifest(signatures=(base_signature, base_signature))

        other_signature = replace(
            base_signature,
            key_reference="kms-key-002",
            signed_payload_sha256=_hash("e"),
        )
        with self.assertRaisesRegex(ValueError, "one signed payload hash"):
            _manifest(signatures=(base_signature, other_signature))

    def test_manifest_rejects_invalid_processing_sequences_and_actions(self) -> None:
        history = list(_history())
        with self.assertRaisesRegex(ValueError, "sequence"):
            _manifest(
                processing_history=tuple(
                    [history[0], replace(history[1], sequence=4), *history[2:]]
                )
            )

        backwards = history.copy()
        backwards[1] = replace(backwards[1], occurred_at=datetime(2026, 1, 2, 8, 59, tzinfo=UTC))
        with self.assertRaisesRegex(ValueError, "timestamps"):
            _manifest(processing_history=tuple(backwards))

        with self.assertRaisesRegex(ValueError, "end at presentation"):
            _manifest(presentation_sha256=_hash("e"))

        missing_scan = (
            history[0],
            replace(history[2], sequence=2),
            replace(history[3], sequence=3),
        )
        with self.assertRaisesRegex(ValueError, "MALWARE_SCANNED"):
            _manifest(processing_history=missing_scan)

        with self.assertRaisesRegex(ValueError, "ARCHIVE_ACCEPTED"):
            _manifest(processing_history=tuple(history[:-1]))

        wrong_order = history.copy()
        wrong_order[1] = replace(wrong_order[1], action=ProcessingAction.ARCHIVE_ACCEPTED)
        wrong_order[3] = replace(wrong_order[3], action=ProcessingAction.MALWARE_SCANNED)
        with self.assertRaisesRegex(ValueError, "must precede"):
            _manifest(processing_history=tuple(wrong_order))

        metadata_mutation = history.copy()
        metadata_mutation[-1] = replace(
            metadata_mutation[-1],
            output_sha256=_hash("e"),
        )
        with self.assertRaisesRegex(ValueError, "metadata-only action"):
            _manifest(
                processing_history=tuple(metadata_mutation),
                presentation_sha256=_hash("e"),
            )

        with self.assertRaisesRegex(ValueError, "state none"):
            _manifest(
                processing_history=_history(legal_hold_state=LegalHoldState.ACTIVE),
                created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
            )

        released_only = [*history]
        released_only.append(
            replace(
                _history(legal_hold_state=LegalHoldState.RELEASED)[-1],
                sequence=5,
            )
        )
        with self.assertRaisesRegex(ValueError, "prior LEGAL_HOLD_PLACED"):
            _manifest(
                processing_history=tuple(released_only),
                legal_hold_state=LegalHoldState.RELEASED,
                created_at=datetime(2026, 1, 4, 9, 1, tzinfo=UTC),
            )

    def test_manifest_match_and_successor_failure_paths(self) -> None:
        manifest = _manifest()
        with self.assertRaisesRegex(ValueError, "document must"):
            manifest.assert_matches_document(object())  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "does not match document tenant_id"):
            _manifest(tenant_id="tenant-002").assert_matches_document(_document())
        longer_document = _document(retain_until=date(2035, 12, 31))
        with self.assertRaisesRegex(ValueError, "shorter than document"):
            _manifest(
                document_record_sha256=longer_document.canonical_sha256()
            ).assert_matches_document(longer_document)
        with self.assertRaisesRegex(ValueError, "released before it is active"):
            _manifest(
                processing_history=_history(legal_hold_state=LegalHoldState.RELEASED),
                legal_hold_state=LegalHoldState.RELEASED,
                created_at=datetime(2026, 1, 4, 9, 1, tzinfo=UTC),
            ).assert_matches_document(_document())

        with self.assertRaisesRegex(ValueError, "previous must"):
            manifest.assert_successor_of(  # type: ignore[arg-type]
                object(),
                previous_document=_document(),
                document=_document(),
            )
        with self.assertRaisesRegex(ValueError, "advance by exactly one"):
            _assert_manifest_successor(_manifest(revision=3), manifest)
        with self.assertRaisesRegex(ValueError, "cannot change tenant_id"):
            _assert_manifest_successor(
                _manifest(revision=2, tenant_id="tenant-002"),
                manifest,
            )
        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            _assert_manifest_successor(
                _manifest(
                    revision=2,
                    created_at=datetime(2026, 1, 2, 9, 3, tzinfo=UTC),
                ),
                manifest,
            )

        altered_history = list(_history(legal_hold_state=LegalHoldState.ACTIVE))
        altered_history[0] = replace(altered_history[0], processor_version="1.0.1")
        with self.assertRaisesRegex(ValueError, "append-only"):
            _assert_manifest_successor(
                _manifest(
                    revision=2,
                    processing_history=tuple(altered_history),
                    legal_hold_state=LegalHoldState.ACTIVE,
                    created_at=datetime(2026, 1, 3, 9, 1, tzinfo=UTC),
                ),
                manifest,
            )

        replacement_policy = PolicyVersion(
            policy_id="archive-retention-se-v2",
            purpose=PolicyPurpose.RETENTION,
            version="2027.1",
            policy_sha256=_hash("e"),
        )
        with self.assertRaisesRegex(ValueError, "preserve prior entries"):
            _assert_manifest_successor(
                _manifest(revision=2, policy_versions=(replacement_policy,)),
                manifest,
            )


if __name__ == "__main__":
    unittest.main()
