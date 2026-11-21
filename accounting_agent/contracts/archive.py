"""Immutable document metadata and archive-manifest contracts.

The contracts deliberately contain hashes, provenance, typed policy metadata,
and opaque references only. They do not contain document bytes, filesystem
paths, provider storage keys, credentials, or transport behavior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from ._wire import (
    canonical_json_sha256,
    datetime_to_wire,
    parse_json_object,
    parse_enum,
    parse_wire_date,
    parse_wire_datetime,
    require_base64,
    require_date,
    require_identifier,
    require_nonempty_text,
    require_positive_integer,
    require_sha256,
    require_tuple,
    require_utc_datetime,
    require_wire_array,
    require_wire_object,
    require_wire_version,
)


class RecordClass(str, Enum):
    SUPPLIER_INVOICE = "supplier_invoice"
    BANK_STATEMENT = "bank_statement"
    ACCOUNTING_VOUCHER = "accounting_voucher"
    LEDGER_EXPORT = "ledger_export"
    CONNECTOR_SNAPSHOT = "connector_snapshot"
    AUDIT_EVIDENCE = "audit_evidence"


class DocumentClassification(str, Enum):
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class MalwareStatus(str, Enum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    SCAN_FAILED = "scan_failed"
    UNSCANNABLE = "unscannable"


class QuarantineState(str, Enum):
    HELD = "held"
    RELEASED = "released"


class StorageRegion(str, Enum):
    """Storage-neutral residency labels, not provider bucket or object identifiers."""

    LOCAL_DEVICE = "local_device"
    SWEDEN = "se"


class RetentionClass(str, Enum):
    SWEDISH_ACCOUNTING = "swedish_accounting"
    POLICY_DEFINED = "policy_defined"


class LegalHoldState(str, Enum):
    NONE = "none"
    ACTIVE = "active"
    RELEASED = "released"


class ProvenanceSource(str, Enum):
    DIRECT_UPLOAD = "direct_upload"
    MICROSOFT_GRAPH = "microsoft_graph"
    ERP_CONNECTOR = "erp_connector"
    LOCAL_IMPORT = "local_import"
    DERIVED_PRESENTATION = "derived_presentation"


class ProcessingAction(str, Enum):
    INGESTED = "ingested"
    MALWARE_SCANNED = "malware_scanned"
    TEXT_EXTRACTED = "text_extracted"
    OCR_COMPLETED = "ocr_completed"
    PRESENTATION_CREATED = "presentation_created"
    ARCHIVE_ACCEPTED = "archive_accepted"
    FORMAT_MIGRATED = "format_migrated"
    RETENTION_EXTENDED = "retention_extended"
    LEGAL_HOLD_PLACED = "legal_hold_placed"
    LEGAL_HOLD_RELEASED = "legal_hold_released"


class PolicyPurpose(str, Enum):
    RETENTION = "retention"
    ARCHIVE_ACCEPTANCE = "archive_acceptance"
    PROCESSING = "processing"
    LEGAL_HOLD = "legal_hold"


class SignatureAlgorithm(str, Enum):
    ECDSA_P256_SHA256 = "ecdsa_p256_sha256"
    RSA_PSS_SHA256 = "rsa_pss_sha256"
    ED25519 = "ed25519"


_PROVENANCE_FIELDS = frozenset(
    {
        "source",
        "source_reference",
        "source_sha256",
        "captured_at",
        "captured_by_actor_id",
    }
)
_DOCUMENT_FIELDS = frozenset(
    {
        "schema_version",
        "document_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "record_class",
        "classification",
        "malware_status",
        "quarantine_state",
        "content_sha256",
        "media_type",
        "size_bytes",
        "storage_region",
        "provenance",
        "retention_class",
        "retention_basis_date",
        "retain_until",
        "legal_hold_state",
        "recorded_at",
    }
)
_PROCESSING_FIELDS = frozenset(
    {
        "sequence",
        "action",
        "occurred_at",
        "actor_id",
        "processor",
        "processor_version",
        "input_sha256",
        "output_sha256",
    }
)
_POLICY_FIELDS = frozenset({"policy_id", "purpose", "version", "policy_sha256"})
_SIGNATURE_FIELDS = frozenset(
    {
        "key_reference",
        "algorithm",
        "signed_at",
        "signed_payload_sha256",
        "signature_base64",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "manifest_id",
        "revision",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "document_id",
        "document_record_sha256",
        "record_class",
        "classification",
        "malware_status",
        "quarantine_state",
        "storage_region",
        "original_sha256",
        "presentation_sha256",
        "provenance",
        "processing_history",
        "policy_versions",
        "signatures",
        "retention_class",
        "retention_basis_date",
        "retain_until",
        "legal_hold_state",
        "created_at",
    }
)
_MANIFEST_UNSIGNED_FIELDS = _MANIFEST_FIELDS - {"signatures"}


@dataclass(frozen=True)
class DocumentProvenance:
    source: ProvenanceSource
    source_reference: str
    source_sha256: str
    captured_at: datetime
    captured_by_actor_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", parse_enum(self.source, ProvenanceSource, "source"))
        object.__setattr__(
            self,
            "source_reference",
            require_identifier(self.source_reference, "source_reference"),
        )
        require_sha256(self.source_sha256, "source_sha256")
        require_utc_datetime(self.captured_at, "captured_at")
        object.__setattr__(
            self,
            "captured_by_actor_id",
            require_identifier(self.captured_by_actor_id, "captured_by_actor_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "source_reference": self.source_reference,
            "source_sha256": self.source_sha256,
            "captured_at": datetime_to_wire(self.captured_at),
            "captured_by_actor_id": self.captured_by_actor_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> DocumentProvenance:
        payload = require_wire_object(
            value,
            contract_name="DocumentProvenance",
            expected_fields=_PROVENANCE_FIELDS,
        )
        return cls(
            source=payload["source"],
            source_reference=payload["source_reference"],
            source_sha256=payload["source_sha256"],
            captured_at=parse_wire_datetime(payload["captured_at"], "captured_at"),
            captured_by_actor_id=payload["captured_by_actor_id"],
        )


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    record_class: RecordClass
    classification: DocumentClassification
    malware_status: MalwareStatus
    quarantine_state: QuarantineState
    content_sha256: str
    media_type: str
    size_bytes: int
    storage_region: StorageRegion
    provenance: DocumentProvenance
    retention_class: RetentionClass
    retention_basis_date: date
    retain_until: date
    legal_hold_state: LegalHoldState
    recorded_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("document_id", "tenant_id", "client_id", "legal_entity_id"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_positive_integer(self.record_version, "record_version")
        object.__setattr__(
            self, "record_class", parse_enum(self.record_class, RecordClass, "record_class")
        )
        object.__setattr__(
            self,
            "classification",
            parse_enum(self.classification, DocumentClassification, "classification"),
        )
        object.__setattr__(
            self,
            "malware_status",
            parse_enum(self.malware_status, MalwareStatus, "malware_status"),
        )
        object.__setattr__(
            self,
            "quarantine_state",
            parse_enum(self.quarantine_state, QuarantineState, "quarantine_state"),
        )
        object.__setattr__(
            self,
            "storage_region",
            parse_enum(self.storage_region, StorageRegion, "storage_region"),
        )
        object.__setattr__(
            self,
            "retention_class",
            parse_enum(self.retention_class, RetentionClass, "retention_class"),
        )
        object.__setattr__(
            self,
            "legal_hold_state",
            parse_enum(self.legal_hold_state, LegalHoldState, "legal_hold_state"),
        )
        require_sha256(self.content_sha256, "content_sha256")
        media_type = require_nonempty_text(self.media_type, "media_type", maximum=127)
        if not re.fullmatch(
            r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*",
            media_type,
        ):
            raise ValueError("media_type must be a canonical media type")
        require_positive_integer(self.size_bytes, "size_bytes", allow_zero=True)
        if not isinstance(self.provenance, DocumentProvenance):
            raise ValueError("provenance must be a DocumentProvenance")
        if self.content_sha256 != self.provenance.source_sha256:
            raise ValueError("content_sha256 must match provenance source_sha256")
        _validate_malware_quarantine(self.malware_status, self.quarantine_state)
        require_utc_datetime(self.recorded_at, "recorded_at")
        if self.recorded_at < self.provenance.captured_at:
            raise ValueError("recorded_at cannot precede provenance capture")
        _validate_retention(
            self.retention_class,
            self.retention_basis_date,
            self.retain_until,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "document_id": self.document_id,
            "record_version": self.record_version,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "record_class": self.record_class.value,
            "classification": self.classification.value,
            "malware_status": self.malware_status.value,
            "quarantine_state": self.quarantine_state.value,
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "storage_region": self.storage_region.value,
            "provenance": self.provenance.to_dict(),
            "retention_class": self.retention_class.value,
            "retention_basis_date": self.retention_basis_date.isoformat(),
            "retain_until": self.retain_until.isoformat(),
            "legal_hold_state": self.legal_hold_state.value,
            "recorded_at": datetime_to_wire(self.recorded_at),
        }

    @classmethod
    def from_dict(cls, value: object) -> DocumentRecord:
        payload = require_wire_object(
            value,
            contract_name="DocumentRecord",
            expected_fields=_DOCUMENT_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            document_id=payload["document_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            record_class=payload["record_class"],
            classification=payload["classification"],
            malware_status=payload["malware_status"],
            quarantine_state=payload["quarantine_state"],
            content_sha256=payload["content_sha256"],
            media_type=payload["media_type"],
            size_bytes=payload["size_bytes"],
            storage_region=payload["storage_region"],
            provenance=DocumentProvenance.from_dict(payload["provenance"]),
            retention_class=payload["retention_class"],
            retention_basis_date=parse_wire_date(
                payload["retention_basis_date"], "retention_basis_date"
            ),
            retain_until=parse_wire_date(payload["retain_until"], "retain_until"),
            legal_hold_state=payload["legal_hold_state"],
            recorded_at=parse_wire_datetime(payload["recorded_at"], "recorded_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> DocumentRecord:
        return cls.from_dict(parse_json_object(value, "DocumentRecord"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "DocumentRecord")

    def assert_successor_of(self, previous: DocumentRecord) -> None:
        if not isinstance(previous, DocumentRecord):
            raise ValueError("previous must be a DocumentRecord")
        if self.record_version != previous.record_version + 1:
            raise ValueError("record_version must advance by exactly one")
        immutable_fields = (
            "document_id",
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "record_class",
            "content_sha256",
            "media_type",
            "size_bytes",
            "provenance",
            "retention_class",
            "retention_basis_date",
        )
        for field_name in immutable_fields:
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"document successor cannot change {field_name}")
        if self.recorded_at < previous.recorded_at:
            raise ValueError("recorded_at cannot move backwards")
        _validate_document_lifecycle(previous, self)
        _validate_retention_successor(
            previous.retain_until,
            self.retain_until,
            previous.legal_hold_state,
            self.legal_hold_state,
        )


@dataclass(frozen=True)
class ArchiveProcessingEntry:
    sequence: int
    action: ProcessingAction
    occurred_at: datetime
    actor_id: str
    processor: str
    processor_version: str
    input_sha256: str
    output_sha256: str

    def __post_init__(self) -> None:
        require_positive_integer(self.sequence, "sequence")
        object.__setattr__(self, "action", parse_enum(self.action, ProcessingAction, "action"))
        require_utc_datetime(self.occurred_at, "occurred_at")
        object.__setattr__(self, "actor_id", require_identifier(self.actor_id, "actor_id"))
        require_nonempty_text(self.processor, "processor")
        require_nonempty_text(self.processor_version, "processor_version")
        require_sha256(self.input_sha256, "input_sha256")
        require_sha256(self.output_sha256, "output_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "action": self.action.value,
            "occurred_at": datetime_to_wire(self.occurred_at),
            "actor_id": self.actor_id,
            "processor": self.processor,
            "processor_version": self.processor_version,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> ArchiveProcessingEntry:
        payload = require_wire_object(
            value,
            contract_name="ArchiveProcessingEntry",
            expected_fields=_PROCESSING_FIELDS,
        )
        return cls(
            sequence=payload["sequence"],
            action=payload["action"],
            occurred_at=parse_wire_datetime(payload["occurred_at"], "occurred_at"),
            actor_id=payload["actor_id"],
            processor=payload["processor"],
            processor_version=payload["processor_version"],
            input_sha256=payload["input_sha256"],
            output_sha256=payload["output_sha256"],
        )


@dataclass(frozen=True)
class PolicyVersion:
    policy_id: str
    purpose: PolicyPurpose
    version: str
    policy_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", require_identifier(self.policy_id, "policy_id"))
        object.__setattr__(
            self,
            "purpose",
            parse_enum(self.purpose, PolicyPurpose, "policy purpose"),
        )
        require_nonempty_text(self.version, "version")
        require_sha256(self.policy_sha256, "policy_sha256")

    def to_dict(self) -> dict[str, str]:
        return {
            "policy_id": self.policy_id,
            "purpose": self.purpose.value,
            "version": self.version,
            "policy_sha256": self.policy_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> PolicyVersion:
        payload = require_wire_object(
            value,
            contract_name="PolicyVersion",
            expected_fields=_POLICY_FIELDS,
        )
        return cls(
            policy_id=payload["policy_id"],
            purpose=payload["purpose"],
            version=payload["version"],
            policy_sha256=payload["policy_sha256"],
        )


@dataclass(frozen=True)
class ArchiveSignature:
    key_reference: str
    algorithm: SignatureAlgorithm
    signed_at: datetime
    signed_payload_sha256: str
    signature_base64: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key_reference",
            require_identifier(self.key_reference, "key_reference"),
        )
        object.__setattr__(
            self,
            "algorithm",
            parse_enum(self.algorithm, SignatureAlgorithm, "signature algorithm"),
        )
        require_utc_datetime(self.signed_at, "signed_at")
        require_sha256(self.signed_payload_sha256, "signed_payload_sha256")
        require_base64(self.signature_base64, "signature_base64", minimum_bytes=32)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_reference": self.key_reference,
            "algorithm": self.algorithm.value,
            "signed_at": datetime_to_wire(self.signed_at),
            "signed_payload_sha256": self.signed_payload_sha256,
            "signature_base64": self.signature_base64,
        }

    @classmethod
    def from_dict(cls, value: object) -> ArchiveSignature:
        payload = require_wire_object(
            value,
            contract_name="ArchiveSignature",
            expected_fields=_SIGNATURE_FIELDS,
        )
        return cls(
            key_reference=payload["key_reference"],
            algorithm=payload["algorithm"],
            signed_at=parse_wire_datetime(payload["signed_at"], "signed_at"),
            signed_payload_sha256=payload["signed_payload_sha256"],
            signature_base64=payload["signature_base64"],
        )


@dataclass(frozen=True)
class ArchiveManifestV1:
    manifest_id: str
    revision: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    document_id: str
    document_record_sha256: str
    record_class: RecordClass
    classification: DocumentClassification
    malware_status: MalwareStatus
    quarantine_state: QuarantineState
    storage_region: StorageRegion
    original_sha256: str
    presentation_sha256: str
    provenance: DocumentProvenance
    processing_history: tuple[ArchiveProcessingEntry, ...]
    policy_versions: tuple[PolicyVersion, ...]
    signatures: tuple[ArchiveSignature, ...]
    retention_class: RetentionClass
    retention_basis_date: date
    retain_until: date
    legal_hold_state: LegalHoldState
    created_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "manifest_id",
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "document_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_positive_integer(self.revision, "revision")
        require_sha256(self.document_record_sha256, "document_record_sha256")
        object.__setattr__(
            self, "record_class", parse_enum(self.record_class, RecordClass, "record_class")
        )
        object.__setattr__(
            self,
            "classification",
            parse_enum(self.classification, DocumentClassification, "classification"),
        )
        object.__setattr__(
            self,
            "malware_status",
            parse_enum(self.malware_status, MalwareStatus, "malware_status"),
        )
        object.__setattr__(
            self,
            "quarantine_state",
            parse_enum(self.quarantine_state, QuarantineState, "quarantine_state"),
        )
        object.__setattr__(
            self,
            "storage_region",
            parse_enum(self.storage_region, StorageRegion, "storage_region"),
        )
        object.__setattr__(
            self,
            "retention_class",
            parse_enum(self.retention_class, RetentionClass, "retention_class"),
        )
        object.__setattr__(
            self,
            "legal_hold_state",
            parse_enum(self.legal_hold_state, LegalHoldState, "legal_hold_state"),
        )
        if self.malware_status is not MalwareStatus.CLEAN:
            raise ValueError("archive manifests require clean malware status")
        if self.quarantine_state is not QuarantineState.RELEASED:
            raise ValueError("archive manifests require released quarantine state")
        require_sha256(self.original_sha256, "original_sha256")
        require_sha256(self.presentation_sha256, "presentation_sha256")
        if not isinstance(self.provenance, DocumentProvenance):
            raise ValueError("provenance must be a DocumentProvenance")
        if self.provenance.source_sha256 != self.original_sha256:
            raise ValueError("original_sha256 must match provenance source_sha256")
        self._validate_typed_tuples()
        require_utc_datetime(self.created_at, "created_at")
        if self.processing_history[-1].occurred_at > self.created_at:
            raise ValueError("created_at cannot precede processing history")
        _validate_retention(
            self.retention_class,
            self.retention_basis_date,
            self.retain_until,
        )
        self._validate_processing_history()
        self._validate_legal_hold_evidence()
        expected_signing_hash = self.signing_payload_sha256(self.unsigned_payload_dict())
        if any(
            signature.signed_payload_sha256 != expected_signing_hash
            for signature in self.signatures
        ):
            raise ValueError("signature signed payload hash must match exact manifest content")
        if any(signature.signed_at < self.created_at for signature in self.signatures):
            raise ValueError("signatures cannot precede manifest creation")

    def _validate_typed_tuples(self) -> None:
        for field_name, expected_type in (
            ("processing_history", ArchiveProcessingEntry),
            ("policy_versions", PolicyVersion),
            ("signatures", ArchiveSignature),
        ):
            values = require_tuple(getattr(self, field_name), field_name)
            if not values:
                raise ValueError(f"{field_name} must not be empty")
            if not all(isinstance(value, expected_type) for value in values):
                raise ValueError(f"{field_name} contains an invalid typed record")
        policy_revisions = tuple((item.policy_id, item.version) for item in self.policy_versions)
        if len(policy_revisions) != len(set(policy_revisions)):
            raise ValueError("policy_versions must contain unique policy revisions")
        if not any(policy.purpose is PolicyPurpose.RETENTION for policy in self.policy_versions):
            raise ValueError("archive manifests require retention-purpose policy evidence")
        signature_keys = tuple(item.key_reference for item in self.signatures)
        if len(signature_keys) != len(set(signature_keys)):
            raise ValueError("signatures must contain unique key references")
        signed_hashes = {item.signed_payload_sha256 for item in self.signatures}
        if len(signed_hashes) != 1:
            raise ValueError("signatures must bind one signed payload hash")

    def _validate_processing_history(self) -> None:
        expected_sequence = 1
        previous_output = self.original_sha256
        previous_time: datetime | None = None
        actions: list[ProcessingAction] = []
        for entry in self.processing_history:
            if entry.sequence != expected_sequence:
                raise ValueError("processing_history sequence must be contiguous and one-based")
            if entry.input_sha256 != previous_output:
                raise ValueError("processing hash chain is not contiguous")
            if previous_time is not None and entry.occurred_at < previous_time:
                raise ValueError("processing_history timestamps cannot move backwards")
            if (
                entry.action
                in {
                    ProcessingAction.INGESTED,
                    ProcessingAction.MALWARE_SCANNED,
                    ProcessingAction.ARCHIVE_ACCEPTED,
                    ProcessingAction.RETENTION_EXTENDED,
                    ProcessingAction.LEGAL_HOLD_PLACED,
                    ProcessingAction.LEGAL_HOLD_RELEASED,
                }
                and entry.input_sha256 != entry.output_sha256
            ):
                raise ValueError(
                    f"metadata-only action {entry.action.value} cannot change content hashes"
                )
            expected_sequence += 1
            previous_output = entry.output_sha256
            previous_time = entry.occurred_at
            actions.append(entry.action)
        if previous_output != self.presentation_sha256:
            raise ValueError("processing history must end at presentation_sha256")
        if ProcessingAction.MALWARE_SCANNED not in actions:
            raise ValueError("processing_history must include MALWARE_SCANNED")
        if ProcessingAction.ARCHIVE_ACCEPTED not in actions:
            raise ValueError("processing_history must include ARCHIVE_ACCEPTED")
        if actions.index(ProcessingAction.MALWARE_SCANNED) > actions.index(
            ProcessingAction.ARCHIVE_ACCEPTED
        ):
            raise ValueError("malware scan must precede archive acceptance")

    def _validate_legal_hold_evidence(self) -> None:
        hold_actions = tuple(
            entry.action
            for entry in self.processing_history
            if entry.action
            in {ProcessingAction.LEGAL_HOLD_PLACED, ProcessingAction.LEGAL_HOLD_RELEASED}
        )
        if self.legal_hold_state is LegalHoldState.NONE:
            if hold_actions:
                raise ValueError("legal_hold_state none cannot contain legal-hold actions")
            return
        required_action = (
            ProcessingAction.LEGAL_HOLD_PLACED
            if self.legal_hold_state is LegalHoldState.ACTIVE
            else ProcessingAction.LEGAL_HOLD_RELEASED
        )
        if not hold_actions or hold_actions[-1] is not required_action:
            raise ValueError(
                f"legal_hold_state requires {required_action.name} as its last hold action"
            )
        if self.legal_hold_state is LegalHoldState.RELEASED and (
            ProcessingAction.LEGAL_HOLD_PLACED not in hold_actions
        ):
            raise ValueError("LEGAL_HOLD_RELEASED requires prior LEGAL_HOLD_PLACED evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "manifest_id": self.manifest_id,
            "revision": self.revision,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "document_id": self.document_id,
            "document_record_sha256": self.document_record_sha256,
            "record_class": self.record_class.value,
            "classification": self.classification.value,
            "malware_status": self.malware_status.value,
            "quarantine_state": self.quarantine_state.value,
            "storage_region": self.storage_region.value,
            "original_sha256": self.original_sha256,
            "presentation_sha256": self.presentation_sha256,
            "provenance": self.provenance.to_dict(),
            "processing_history": [entry.to_dict() for entry in self.processing_history],
            "policy_versions": [policy.to_dict() for policy in self.policy_versions],
            "signatures": [signature.to_dict() for signature in self.signatures],
            "retention_class": self.retention_class.value,
            "retention_basis_date": self.retention_basis_date.isoformat(),
            "retain_until": self.retain_until.isoformat(),
            "legal_hold_state": self.legal_hold_state.value,
            "created_at": datetime_to_wire(self.created_at),
        }

    def unsigned_payload_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        del payload["signatures"]
        return payload

    @staticmethod
    def signing_payload_sha256(value: object) -> str:
        payload = require_wire_object(
            value,
            contract_name="ArchiveManifestV1 signing payload",
            expected_fields=frozenset(_MANIFEST_UNSIGNED_FIELDS),
        )
        return canonical_json_sha256(dict(payload), "ArchiveManifestV1 signing payload")

    @classmethod
    def from_dict(cls, value: object) -> ArchiveManifestV1:
        payload = require_wire_object(
            value,
            contract_name="ArchiveManifestV1",
            expected_fields=_MANIFEST_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        history = require_wire_array(payload["processing_history"], "processing_history")
        policies = require_wire_array(payload["policy_versions"], "policy_versions")
        signatures = require_wire_array(payload["signatures"], "signatures")
        return cls(
            manifest_id=payload["manifest_id"],
            revision=payload["revision"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            document_id=payload["document_id"],
            document_record_sha256=payload["document_record_sha256"],
            record_class=payload["record_class"],
            classification=payload["classification"],
            malware_status=payload["malware_status"],
            quarantine_state=payload["quarantine_state"],
            storage_region=payload["storage_region"],
            original_sha256=payload["original_sha256"],
            presentation_sha256=payload["presentation_sha256"],
            provenance=DocumentProvenance.from_dict(payload["provenance"]),
            processing_history=tuple(ArchiveProcessingEntry.from_dict(item) for item in history),
            policy_versions=tuple(PolicyVersion.from_dict(item) for item in policies),
            signatures=tuple(ArchiveSignature.from_dict(item) for item in signatures),
            retention_class=payload["retention_class"],
            retention_basis_date=parse_wire_date(
                payload["retention_basis_date"], "retention_basis_date"
            ),
            retain_until=parse_wire_date(payload["retain_until"], "retain_until"),
            legal_hold_state=payload["legal_hold_state"],
            created_at=parse_wire_datetime(payload["created_at"], "created_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> ArchiveManifestV1:
        return cls.from_dict(parse_json_object(value, "ArchiveManifestV1"))

    def assert_matches_document(self, document: DocumentRecord) -> None:
        if not isinstance(document, DocumentRecord):
            raise ValueError("document must be a DocumentRecord")
        expected = {
            "tenant_id": document.tenant_id,
            "client_id": document.client_id,
            "legal_entity_id": document.legal_entity_id,
            "document_id": document.document_id,
            "document_record_sha256": document.canonical_sha256(),
            "record_class": document.record_class,
            "classification": document.classification,
            "malware_status": document.malware_status,
            "quarantine_state": document.quarantine_state,
            "storage_region": document.storage_region,
            "original_sha256": document.content_sha256,
            "provenance": document.provenance,
            "retention_class": document.retention_class,
            "retention_basis_date": document.retention_basis_date,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"archive manifest does not match document {field_name}")
        if self.retain_until < document.retain_until:
            raise ValueError("archive retention cannot be shorter than document retention")
        _validate_legal_hold_transition(document.legal_hold_state, self.legal_hold_state)

    def assert_successor_of(
        self,
        previous: ArchiveManifestV1,
        *,
        previous_document: DocumentRecord,
        document: DocumentRecord,
    ) -> None:
        if not isinstance(previous, ArchiveManifestV1):
            raise ValueError("previous must be an ArchiveManifestV1")
        if self.revision != previous.revision + 1:
            raise ValueError("manifest revision must advance by exactly one")
        immutable_fields = (
            "manifest_id",
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "document_id",
            "record_class",
            "original_sha256",
            "provenance",
            "retention_class",
            "retention_basis_date",
        )
        for field_name in immutable_fields:
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"manifest successor cannot change {field_name}")
        if self.created_at < previous.created_at:
            raise ValueError("created_at cannot move backwards")
        previous.assert_matches_document(previous_document)
        self.assert_matches_document(document)
        if self.document_record_sha256 == previous.document_record_sha256:
            if document != previous_document:
                raise ValueError("unchanged document digest must reference the same record")
        else:
            document.assert_successor_of(previous_document)
        if (
            self.processing_history[: len(previous.processing_history)]
            != previous.processing_history
        ):
            raise ValueError("processing_history must be append-only")
        if self.policy_versions[: len(previous.policy_versions)] != previous.policy_versions:
            raise ValueError("policy_versions must preserve prior entries")
        if self.retain_until > previous.retain_until:
            appended_history = self.processing_history[len(previous.processing_history) :]
            if not any(
                entry.action is ProcessingAction.RETENTION_EXTENDED for entry in appended_history
            ):
                raise ValueError(
                    "retention extension requires appended RETENTION_EXTENDED evidence"
                )
            appended_policies = self.policy_versions[len(previous.policy_versions) :]
            if not any(policy.purpose is PolicyPurpose.RETENTION for policy in appended_policies):
                raise ValueError("retention extension requires appended policy evidence")
        _validate_retention_successor(
            previous.retain_until,
            self.retain_until,
            previous.legal_hold_state,
            self.legal_hold_state,
        )


def _validate_retention(
    retention_class: RetentionClass,
    retention_basis_date: object,
    retain_until: object,
) -> None:
    basis = require_date(retention_basis_date, "retention_basis_date")
    endpoint = require_date(retain_until, "retain_until")
    if retention_class is RetentionClass.SWEDISH_ACCOUNTING:
        minimum = date(basis.year + 7, 12, 31)
        if endpoint < minimum:
            raise ValueError(
                "Swedish accounting retention must reach the seventh-year calendar endpoint"
            )
    elif endpoint <= basis:
        raise ValueError("policy-defined retain_until must follow its basis date")


def _validate_malware_quarantine(
    malware_status: MalwareStatus,
    quarantine_state: QuarantineState,
) -> None:
    if quarantine_state is QuarantineState.RELEASED and malware_status is not MalwareStatus.CLEAN:
        raise ValueError("only clean documents may be released from quarantine")
    if (
        malware_status
        in {
            MalwareStatus.PENDING,
            MalwareStatus.INFECTED,
            MalwareStatus.SCAN_FAILED,
            MalwareStatus.UNSCANNABLE,
        }
        and quarantine_state is not QuarantineState.HELD
    ):
        raise ValueError("non-clean documents must remain held in quarantine")


def _validate_document_lifecycle(previous: DocumentRecord, current: DocumentRecord) -> None:
    classification_rank = {
        DocumentClassification.INTERNAL: 0,
        DocumentClassification.CONFIDENTIAL: 1,
        DocumentClassification.RESTRICTED: 2,
    }
    if classification_rank[current.classification] < classification_rank[previous.classification]:
        raise ValueError("document classification cannot be lowered")

    if previous.malware_status in {MalwareStatus.CLEAN, MalwareStatus.INFECTED} and (
        current.malware_status is not previous.malware_status
    ):
        raise ValueError("terminal malware status cannot change")

    storage_transitions = {
        StorageRegion.LOCAL_DEVICE: {StorageRegion.LOCAL_DEVICE, StorageRegion.SWEDEN},
        StorageRegion.SWEDEN: {StorageRegion.SWEDEN},
    }
    if current.storage_region not in storage_transitions[previous.storage_region]:
        raise ValueError("document storage region cannot move outside Sweden")


def _validate_legal_hold_transition(
    previous: LegalHoldState,
    current: LegalHoldState,
) -> None:
    if previous is LegalHoldState.ACTIVE and current is LegalHoldState.NONE:
        raise ValueError("legal hold cannot be cleared without a released state")
    if previous is LegalHoldState.RELEASED and current is LegalHoldState.NONE:
        raise ValueError("legal hold history cannot regress to none")
    if previous is LegalHoldState.NONE and current is LegalHoldState.RELEASED:
        raise ValueError("legal hold cannot be released before it is active")


def _validate_retention_successor(
    previous_retain_until: date,
    retain_until: date,
    previous_hold_state: LegalHoldState,
    hold_state: LegalHoldState,
) -> None:
    if retain_until < previous_retain_until:
        raise ValueError("retention cannot be shortened")
    _validate_legal_hold_transition(previous_hold_state, hold_state)
