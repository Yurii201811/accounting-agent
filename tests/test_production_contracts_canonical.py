from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone

from hypothesis import given, settings, strategies as st

from accounting_agent.connector_contract import (
    AuthReference,
    ConnectorCapability,
    ConnectorEnvironment,
)
from accounting_agent.contracts.canonical import (
    BankDetailsState,
    CanonicalBalance,
    CanonicalDimension,
    CanonicalInvoice,
    CanonicalJournal,
    CanonicalPeriod,
    CanonicalSupplier,
    DimensionAssignment,
    InvoiceKind,
    InvoiceLine,
    InvoiceStatus,
    JournalLine,
    JournalStatus,
    LifecycleStatus,
    PeriodState,
    RecordSource,
)
from accounting_agent.contracts.sync import (
    ConnectorConnection,
    ConnectorConnectionStatus,
    SyncCheckpoint,
)


PROPERTY_SETTINGS = settings(max_examples=75, derandomize=True, deadline=None)
NOW = datetime(2026, 7, 11, 8, tzinfo=UTC)


def _hash(character: str) -> str:
    return character * 64


def _source(**overrides: object) -> RecordSource:
    values: dict[str, object] = {
        "source_system": "fortnox",
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "connection_id": "connection-001",
        "connection_revision": 1,
        "connection_sha256": _hash("c"),
        "environment": ConnectorEnvironment.SANDBOX,
        "sync_run_id": "sync-run-001",
        "checkpoint_id": "checkpoint-001",
        "checkpoint_sha256": _hash("d"),
        "source_record_id": "source-record-001",
        "source_version": "17",
        "source_sha256": _hash("a"),
        "raw_snapshot_sha256": _hash("f"),
        "mapping_version": "canonical-v1.2.0",
        "observed_at": NOW,
    }
    values.update(overrides)
    return RecordSource(**values)  # type: ignore[arg-type]


def _scope() -> dict[str, str]:
    return {
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
    }


def _checkpoint_and_source() -> tuple[SyncCheckpoint, RecordSource]:
    connection = ConnectorConnection(
        connection_id="connection-001",
        revision=1,
        tenant_id="tenant-001",
        client_id="client-001",
        legal_entity_id="entity-se-001",
        provider_id="fortnox",
        source_company_id="fortnox-company-001",
        environment=ConnectorEnvironment.SANDBOX,
        auth_reference=AuthReference("oauth-ref:fortnox-001"),
        capabilities=(ConnectorCapability.READ_MASTER_DATA,),
        status=ConnectorConnectionStatus.ACTIVE,
        recorded_at=NOW - timedelta(minutes=1),
    )
    checkpoint = SyncCheckpoint(
        checkpoint_id="checkpoint-001",
        sync_run_id="sync-run-001",
        connection_id=connection.connection_id,
        connection_revision=connection.revision,
        connection_sha256=connection.canonical_sha256(),
        tenant_id=connection.tenant_id,
        client_id=connection.client_id,
        legal_entity_id=connection.legal_entity_id,
        provider_id=connection.provider_id,
        source_company_id=connection.source_company_id,
        environment=connection.environment,
        resource="suppliers",
        sequence=1,
        source_cursor=None,
        next_cursor=None,
        record_count=1,
        raw_snapshot_sha256=_hash("f"),
        canonical_record_set_sha256=_hash("9"),
        captured_at=NOW,
    )
    source = _source(
        connection_sha256=connection.canonical_sha256(),
        checkpoint_sha256=checkpoint.canonical_sha256(),
    )
    return checkpoint, source


def _supplier(**overrides: object) -> CanonicalSupplier:
    values: dict[str, object] = {
        "supplier_id": "supplier-001",
        "record_version": 1,
        **_scope(),
        "source": _source(),
        "display_name": "Synthetic Components AB",
        "organization_identifier": "SE-5590000000",
        "bank_details_state": BankDetailsState.FINGERPRINTED,
        "bank_account_fingerprint": _hash("b"),
        "status": LifecycleStatus.ACTIVE,
    }
    values.update(overrides)
    return CanonicalSupplier(**values)  # type: ignore[arg-type]


def _invoice_line(**overrides: object) -> InvoiceLine:
    values: dict[str, object] = {
        "line_id": "line-001",
        "description": "Synthetic consulting",
        "account_id": "account-6540",
        "tax_code": "vat-se-25",
        "net_minor": 10_000,
        "tax_minor": 2_500,
        "gross_minor": 12_500,
    }
    values.update(overrides)
    return InvoiceLine(**values)  # type: ignore[arg-type]


def _invoice(**overrides: object) -> CanonicalInvoice:
    values: dict[str, object] = {
        "invoice_id": "invoice-001",
        "record_version": 1,
        **_scope(),
        "source": _source(source_record_id="source-invoice-001"),
        "kind": InvoiceKind.SUPPLIER_INVOICE,
        "status": InvoiceStatus.OPEN,
        "supplier_id": "supplier-001",
        "invoice_number": "SYN-2026-001",
        "invoice_date": date(2026, 7, 1),
        "due_date": date(2026, 7, 31),
        "currency": "SEK",
        "period_id": "period-2026-07",
        "period_state": PeriodState.OPEN,
        "lines": (_invoice_line(),),
        "net_minor": 10_000,
        "tax_minor": 2_500,
        "gross_minor": 12_500,
    }
    values.update(overrides)
    return CanonicalInvoice(**values)  # type: ignore[arg-type]


def _assignments() -> tuple[DimensionAssignment, ...]:
    return (
        DimensionAssignment(
            dimension_id="dimension-cost-center",
            value_id="cost-center-stockholm",
        ),
    )


def _journal_lines(amount: int = 12_500) -> tuple[JournalLine, ...]:
    return (
        JournalLine(
            line_id="journal-line-001",
            account_id="account-6540",
            description="Synthetic debit",
            debit_minor=amount,
            credit_minor=0,
            dimensions=_assignments(),
        ),
        JournalLine(
            line_id="journal-line-002",
            account_id="account-2440",
            description="Synthetic credit",
            debit_minor=0,
            credit_minor=amount,
            dimensions=(),
        ),
    )


def _journal(**overrides: object) -> CanonicalJournal:
    values: dict[str, object] = {
        "journal_id": "journal-001",
        "record_version": 1,
        **_scope(),
        "source": _source(source_record_id="source-journal-001"),
        "status": JournalStatus.POSTED,
        "journal_number": "A-2026-001",
        "journal_date": date(2026, 7, 1),
        "currency": "SEK",
        "period_id": "period-2026-07",
        "period_state": PeriodState.OPEN,
        "lines": _journal_lines(),
    }
    values.update(overrides)
    return CanonicalJournal(**values)  # type: ignore[arg-type]


def _balance(**overrides: object) -> CanonicalBalance:
    values: dict[str, object] = {
        "balance_id": "balance-001",
        "record_version": 1,
        **_scope(),
        "source": _source(source_record_id="source-balance-001"),
        "account_id": "account-1930",
        "period_id": "period-2026-07",
        "period_state": PeriodState.UNKNOWN,
        "as_of_date": date(2026, 7, 31),
        "currency": "SEK",
        "amount_minor": -12_500,
        "dimensions": _assignments(),
    }
    values.update(overrides)
    return CanonicalBalance(**values)  # type: ignore[arg-type]


def _period(**overrides: object) -> CanonicalPeriod:
    values: dict[str, object] = {
        "period_id": "period-2026-07",
        "record_version": 1,
        **_scope(),
        "source": _source(source_record_id="source-period-001"),
        "fiscal_year_id": "fiscal-year-2026",
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 31),
        "state": PeriodState.UNKNOWN,
    }
    values.update(overrides)
    return CanonicalPeriod(**values)  # type: ignore[arg-type]


def _dimension(**overrides: object) -> CanonicalDimension:
    values: dict[str, object] = {
        "dimension_id": "dimension-cost-center",
        "record_version": 1,
        **_scope(),
        "source": _source(source_record_id="source-dimension-001"),
        "dimension_type": "cost_center",
        "code": "STHLM",
        "label": "Stockholm",
        "status": LifecycleStatus.ACTIVE,
    }
    values.update(overrides)
    return CanonicalDimension(**values)  # type: ignore[arg-type]


def _successor_source(previous: RecordSource, *, character: str = "c") -> RecordSource:
    return replace(
        previous,
        source_version=str(int(previous.source_version) + 1),
        source_sha256=_hash(character),
        observed_at=previous.observed_at + timedelta(minutes=1),
    )


class RecordSourceContractTests(unittest.TestCase):
    def test_source_round_trip_is_deterministic(self) -> None:
        source = _source()
        self.assertEqual(source, RecordSource.from_dict(source.to_dict()))
        self.assertEqual(
            source,
            RecordSource.from_json(json.dumps(source.to_dict(), separators=(",", ":"))),
        )

    def test_source_requires_lowercase_system_hash_and_strict_utc(self) -> None:
        for field, value in (
            ("source_system", "Fortnox"),
            ("source_sha256", "A" * 64),
            ("observed_at", NOW.replace(tzinfo=None)),
            ("observed_at", NOW.astimezone(timezone(timedelta(hours=2)))),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    _source(**{field: value})

    def test_source_successor_is_monotonic_and_identity_bound(self) -> None:
        original = _source()
        current = _successor_source(original)
        current.assert_successor_of(original)
        for changed in (
            replace(current, connection_id="connection-002"),
            replace(current, source_record_id="source-record-002"),
            replace(current, observed_at=original.observed_at - timedelta(microseconds=1)),
            replace(current, source_version=original.source_version, source_sha256=original.source_sha256),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    changed.assert_successor_of(original)
        with self.assertRaises(ValueError):
            current.assert_successor_of(object())  # type: ignore[arg-type]

    def test_source_binds_sync_checkpoint_snapshot_and_mapping(self) -> None:
        source = _source()
        payload = source.to_dict()
        self.assertEqual("sync-run-001", payload["sync_run_id"])
        self.assertEqual("checkpoint-001", payload["checkpoint_id"])
        self.assertEqual(_hash("f"), payload["raw_snapshot_sha256"])
        self.assertEqual("canonical-v1.2.0", payload["mapping_version"])
        for field, value in (
            ("sync_run_id", "unknown"),
            ("checkpoint_id", ""),
            ("raw_snapshot_sha256", "F" * 64),
            ("mapping_version", ""),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    _source(**{field: value})

    def test_source_and_every_canonical_record_bind_exact_scope_and_checkpoint(self) -> None:
        checkpoint, source = _checkpoint_and_source()
        source.assert_matches_checkpoint(checkpoint)

        for field_name, bad_value in (
            ("tenant_id", "tenant-evil"),
            ("client_id", "client-evil"),
            ("legal_entity_id", "entity-evil"),
            ("connection_sha256", _hash("8")),
            ("checkpoint_sha256", _hash("7")),
            ("source_system", "netsuite"),
            ("observed_at", NOW + timedelta(microseconds=1)),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, "checkpoint"):
                    replace(source, **{field_name: bad_value}).assert_matches_checkpoint(
                        checkpoint
                    )

        with self.assertRaisesRegex(ValueError, "source scope"):
            _supplier(source=replace(source, tenant_id="tenant-evil"))


class CanonicalSupplierContractTests(unittest.TestCase):
    def test_supplier_round_trip_digest_and_immutability(self) -> None:
        supplier = _supplier()
        self.assertEqual(supplier, CanonicalSupplier.from_dict(supplier.to_dict()))
        self.assertEqual(supplier, CanonicalSupplier.from_json(json.dumps(supplier.to_dict())))
        self.assertEqual(supplier.canonical_sha256(), CanonicalSupplier.from_dict(supplier.to_dict()).canonical_sha256())
        with self.assertRaises(FrozenInstanceError):
            supplier.display_name = "Changed"  # type: ignore[misc]

    def test_bank_state_never_accepts_raw_or_ambiguous_bank_data(self) -> None:
        for state, fingerprint in (
            (BankDetailsState.UNKNOWN, _hash("b")),
            (BankDetailsState.NOT_PROVIDED, _hash("b")),
            (BankDetailsState.FINGERPRINTED, ""),
            (BankDetailsState.FINGERPRINTED, "SE3550000000054910000003"),
        ):
            with self.subTest(state=state, fingerprint=fingerprint):
                with self.assertRaises(ValueError):
                    _supplier(bank_details_state=state, bank_account_fingerprint=fingerprint)
        payload = _supplier().to_dict()
        payload["iban"] = "SE3550000000054910000003"
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            CanonicalSupplier.from_dict(payload)

    def test_supplier_lifecycle_status_is_explicit(self) -> None:
        self.assertEqual(LifecycleStatus.ACTIVE, _supplier().status)
        with self.assertRaises(ValueError):
            _supplier(status="")

    def test_supplier_lifecycle_status_cannot_regress_or_reactivate(self) -> None:
        unknown = _supplier(status=LifecycleStatus.UNKNOWN)
        active = replace(
            unknown,
            record_version=2,
            source=_successor_source(unknown.source),
            status=LifecycleStatus.ACTIVE,
        )
        active.assert_successor_of(unknown)
        inactive = replace(
            active,
            record_version=3,
            source=_successor_source(active.source, character="d"),
            status=LifecycleStatus.INACTIVE,
        )
        inactive.assert_successor_of(active)

        for previous, status in (
            (active, LifecycleStatus.UNKNOWN),
            (inactive, LifecycleStatus.UNKNOWN),
            (inactive, LifecycleStatus.ACTIVE),
        ):
            candidate = replace(
                previous,
                record_version=previous.record_version + 1,
                source=_successor_source(previous.source, character="e"),
                status=status,
            )
            with self.subTest(previous=previous.status, current=status):
                with self.assertRaisesRegex(ValueError, "lifecycle status"):
                    candidate.assert_successor_of(previous)

    def test_bank_fingerprint_change_is_detected_but_not_misreported(self) -> None:
        previous = _supplier()
        unchanged = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
            display_name="Synthetic Components Sverige AB",
        )
        changed = replace(unchanged, bank_account_fingerprint=_hash("d"))
        removed = replace(
            unchanged,
            bank_details_state=BankDetailsState.NOT_PROVIDED,
            bank_account_fingerprint="",
        )
        self.assertFalse(unchanged.bank_fingerprint_changed_from(previous))
        self.assertTrue(changed.bank_fingerprint_changed_from(previous))
        self.assertTrue(removed.bank_fingerprint_changed_from(previous))
        changed.assert_successor_of(previous)

    def test_supplier_successor_preserves_scope_and_record_identity(self) -> None:
        previous = _supplier()
        current = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
        )
        current.assert_successor_of(previous)
        for field_name, bad_value in (
            ("record_version", 3),
            ("tenant_id", "tenant-002"),
            ("client_id", "client-002"),
            ("legal_entity_id", "entity-se-002"),
            ("supplier_id", "supplier-002"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    replace(
                        current,
                        **{field_name: bad_value},
                    ).assert_successor_of(previous)
        with self.assertRaises(ValueError):
            current.bank_fingerprint_changed_from(object())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            replace(current, tenant_id="tenant-002").bank_fingerprint_changed_from(previous)


class CanonicalInvoiceContractTests(unittest.TestCase):
    def test_invoice_round_trip_and_exact_arithmetic(self) -> None:
        invoice = _invoice()
        self.assertEqual(invoice, CanonicalInvoice.from_dict(invoice.to_dict()))
        self.assertEqual(invoice, CanonicalInvoice.from_json(json.dumps(invoice.to_dict())))
        for changed in (
            {"gross_minor": 12_499},
            {"net_minor": 9_999},
            {"tax_minor": 2_499},
            {
                "lines": (
                    _invoice_line(net_minor=9_999, tax_minor=2_500, gross_minor=12_499),
                )
            },
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    _invoice(**changed)
        with self.assertRaises(ValueError):
            _invoice_line(gross_minor=12_499)
        with self.assertRaisesRegex(ValueError, "unique line_id"):
            _invoice(
                lines=(_invoice_line(), _invoice_line()),
                net_minor=20_000,
                tax_minor=5_000,
                gross_minor=25_000,
            )
        with self.assertRaisesRegex(ValueError, "line net"):
            _invoice(
                lines=(
                    _invoice_line(net_minor=9_999, tax_minor=2_501, gross_minor=12_500),
                ),
            )
        with self.assertRaisesRegex(ValueError, "line tax"):
            _invoice(
                lines=(
                    _invoice_line(net_minor=10_000, tax_minor=2_499, gross_minor=12_499),
                ),
            )

    def test_invoice_minor_units_reject_bool_and_float_everywhere(self) -> None:
        for field, value in (
            ("net_minor", True),
            ("tax_minor", 2500.0),
            ("gross_minor", False),
            ("gross_minor", 9_007_199_254_740_992),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    _invoice(**{field: value})
                with self.assertRaises(ValueError):
                    _invoice_line(**{field: value})

    def test_credit_invoice_uses_signed_integer_minor_units(self) -> None:
        line = _invoice_line(net_minor=-10_000, tax_minor=-2_500, gross_minor=-12_500)
        invoice = _invoice(
            lines=(line,),
            net_minor=-10_000,
            tax_minor=-2_500,
            gross_minor=-12_500,
        )
        self.assertEqual(-12_500, invoice.gross_minor)

    def test_invoice_kind_and_status_are_explicit_and_round_trip(self) -> None:
        invoice = _invoice(
            kind=InvoiceKind.SUPPLIER_CREDIT_NOTE,
            status=InvoiceStatus.PARTIALLY_PAID,
        )
        restored = CanonicalInvoice.from_dict(invoice.to_dict())
        self.assertEqual(InvoiceKind.SUPPLIER_CREDIT_NOTE, restored.kind)
        self.assertEqual(InvoiceStatus.PARTIALLY_PAID, restored.status)
        for field in ("kind", "status"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    _invoice(**{field: ""})

    def test_invoice_requires_explicit_period_state_and_valid_dates_currency(self) -> None:
        for changed in (
            {"period_state": ""},
            {"due_date": date(2026, 6, 30)},
            {"currency": "sek"},
            {"lines": []},
            {"lines": ()},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    _invoice(**changed)

    def test_invoice_successor_never_reopens_locked_period(self) -> None:
        previous = _invoice(period_state=PeriodState.LOCKED)
        base = {
            "record_version": 2,
            "source": _successor_source(previous.source),
        }
        replace(previous, **base).assert_successor_of(previous)
        for state in (PeriodState.OPEN, PeriodState.UNKNOWN):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    replace(previous, period_state=state, **base).assert_successor_of(previous)
        opened = _invoice(period_state=PeriodState.OPEN)
        with self.assertRaises(ValueError):
            replace(
                opened,
                record_version=2,
                source=_successor_source(opened.source),
                period_state=PeriodState.UNKNOWN,
            ).assert_successor_of(opened)

    def test_invoice_lifecycle_never_regresses_or_reopens_terminal_states(self) -> None:
        previous = _invoice(status=InvoiceStatus.PARTIALLY_PAID)
        for status in (InvoiceStatus.UNKNOWN, InvoiceStatus.DRAFT, InvoiceStatus.OPEN):
            with self.subTest(status=status):
                candidate = replace(
                    previous,
                    record_version=2,
                    source=_successor_source(previous.source),
                    status=status,
                )
                with self.assertRaisesRegex(ValueError, "invoice status"):
                    candidate.assert_successor_of(previous)

        paid = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
            status=InvoiceStatus.PAID,
        )
        for status in InvoiceStatus:
            candidate = replace(
                paid,
                record_version=3,
                source=_successor_source(paid.source, character="d"),
                status=status,
            )
            with self.subTest(status=status):
                if status is InvoiceStatus.PAID:
                    candidate.assert_successor_of(paid)
                else:
                    with self.assertRaisesRegex(ValueError, "invoice status"):
                        candidate.assert_successor_of(paid)

        with self.assertRaisesRegex(ValueError, "terminal invoice content"):
            replace(
                paid,
                record_version=3,
                source=_successor_source(paid.source, character="e"),
                lines=(replace(paid.lines[0], description="Forged paid amount"),),
            ).assert_successor_of(paid)


class CanonicalJournalContractTests(unittest.TestCase):
    def test_journal_round_trip_and_balances(self) -> None:
        journal = _journal()
        self.assertEqual(journal, CanonicalJournal.from_dict(journal.to_dict()))
        self.assertEqual(12_500, journal.debit_total_minor)
        self.assertEqual(12_500, journal.credit_total_minor)
        with self.assertRaisesRegex(ValueError, "balance"):
            _journal(lines=(_journal_lines()[0], replace(_journal_lines()[1], credit_minor=12_499)))

    def test_journal_status_is_explicit_and_cannot_regress_after_posting(self) -> None:
        previous = _journal(status=JournalStatus.POSTED)
        current = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
            status=JournalStatus.DRAFT,
        )
        with self.assertRaises(ValueError):
            current.assert_successor_of(previous)
        reversed_journal = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
            status=JournalStatus.REVERSED,
        )
        with self.assertRaises(ValueError):
            replace(
                reversed_journal,
                record_version=3,
                source=_successor_source(reversed_journal.source, character="d"),
                status=JournalStatus.POSTED,
            ).assert_successor_of(reversed_journal)
        with self.assertRaisesRegex(ValueError, "posted journal content"):
            replace(
                previous,
                record_version=2,
                source=_successor_source(previous.source, character="e"),
                lines=_journal_lines(13_000),
            ).assert_successor_of(previous)
        with self.assertRaises(ValueError):
            _journal(lines=[])
        with self.assertRaises(ValueError):
            _journal(lines=(object(),))
        with self.assertRaisesRegex(ValueError, "unique line_id"):
            _journal(lines=(_journal_lines()[0], _journal_lines()[0]))

        draft = _journal(status=JournalStatus.DRAFT)
        for status in (JournalStatus.UNKNOWN, JournalStatus.REVERSED):
            candidate = replace(
                draft,
                record_version=2,
                source=_successor_source(draft.source),
                status=status,
            )
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "journal status"):
                    candidate.assert_successor_of(draft)

    def test_each_journal_line_has_exactly_one_positive_side(self) -> None:
        for debit, credit in ((0, 0), (1, 1), (-1, 0), (0, -1), (True, 0), (0, 1.0)):
            with self.subTest(debit=debit, credit=credit):
                with self.assertRaises(ValueError):
                    JournalLine(
                        line_id="line-invalid",
                        account_id="account-1000",
                        description="Invalid synthetic line",
                        debit_minor=debit,  # type: ignore[arg-type]
                        credit_minor=credit,  # type: ignore[arg-type]
                        dimensions=(),
                    )

    def test_dimension_assignments_are_unique_and_immutable_tuples(self) -> None:
        assignment = _assignments()[0]
        with self.assertRaises(ValueError):
            replace(_journal_lines()[0], dimensions=[assignment])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            replace(_journal_lines()[0], dimensions=(assignment, assignment))
        with self.assertRaises(ValueError):
            replace(_journal_lines()[0], dimensions=(object(),))  # type: ignore[arg-type]

    @PROPERTY_SETTINGS
    @given(amount=st.integers(min_value=1, max_value=10**15))
    def test_any_positive_two_line_journal_is_exactly_balanced(self, amount: int) -> None:
        journal = _journal(lines=_journal_lines(amount))
        self.assertEqual(amount, journal.debit_total_minor)
        self.assertEqual(amount, journal.credit_total_minor)


class PeriodAndBalanceContractTests(unittest.TestCase):
    def test_period_round_trip_and_requires_explicit_state(self) -> None:
        period = _period()
        self.assertEqual(period, CanonicalPeriod.from_dict(period.to_dict()))
        for changed in (
            {"state": ""},
            {"start_date": date(2026, 8, 1)},
            {"record_version": True},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    _period(**changed)

    def test_unknown_period_can_resolve_but_locked_period_cannot_reopen(self) -> None:
        unknown = _period()
        opened = replace(
            unknown,
            record_version=2,
            source=_successor_source(unknown.source),
            state=PeriodState.OPEN,
        )
        opened.assert_successor_of(unknown)
        locked = replace(
            opened,
            record_version=3,
            source=_successor_source(opened.source, character="d"),
            state=PeriodState.LOCKED,
        )
        locked.assert_successor_of(opened)
        with self.assertRaises(ValueError):
            replace(
                locked,
                record_version=4,
                source=_successor_source(locked.source, character="e"),
                state=PeriodState.OPEN,
            ).assert_successor_of(locked)

        closed = replace(
            unknown,
            record_version=2,
            source=_successor_source(unknown.source),
            state=PeriodState.CLOSED,
        )
        closed.assert_successor_of(unknown)
        reopened = replace(
            closed,
            record_version=3,
            source=_successor_source(closed.source, character="d"),
            state=PeriodState.OPEN,
        )
        reopened.assert_successor_of(closed)
        regressed = replace(
            closed,
            record_version=3,
            source=_successor_source(closed.source, character="e"),
            state=PeriodState.UNKNOWN,
        )
        with self.assertRaisesRegex(ValueError, "regress to unknown"):
            regressed.assert_successor_of(closed)

    def test_balance_round_trip_signed_minor_units_and_period_state(self) -> None:
        balance = _balance()
        self.assertEqual(balance, CanonicalBalance.from_dict(balance.to_dict()))
        self.assertEqual(balance, CanonicalBalance.from_json(json.dumps(balance.to_dict())))
        for changed in (
            {"amount_minor": True},
            {"amount_minor": 1.0},
            {"period_state": ""},
            {"dimensions": list(_assignments())},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    _balance(**changed)


class CanonicalDimensionContractTests(unittest.TestCase):
    def test_dimension_round_trip_and_successor(self) -> None:
        previous = _dimension()
        self.assertEqual(previous, CanonicalDimension.from_dict(previous.to_dict()))
        current = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
            label="Stockholm office",
        )
        current.assert_successor_of(previous)

    def test_dimension_strict_types_and_identity(self) -> None:
        with self.assertRaises(ValueError):
            _dimension(status="")
        previous = _dimension()
        current = replace(
            previous,
            record_version=2,
            source=_successor_source(previous.source),
            dimension_id="dimension-project",
        )
        with self.assertRaises(ValueError):
            current.assert_successor_of(previous)

    def test_dimension_lifecycle_status_cannot_regress_or_reactivate(self) -> None:
        inactive = _dimension(status=LifecycleStatus.INACTIVE)
        for status in (LifecycleStatus.UNKNOWN, LifecycleStatus.ACTIVE):
            candidate = replace(
                inactive,
                record_version=2,
                source=_successor_source(inactive.source),
                status=status,
            )
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "lifecycle status"):
                    candidate.assert_successor_of(inactive)


class StrictWireContractTests(unittest.TestCase):
    def test_all_top_level_contracts_reject_unknown_fields_and_versions(self) -> None:
        records = (
            _supplier(),
            _invoice(),
            _journal(),
            _balance(),
            _period(),
            _dimension(),
        )
        for record in records:
            record_type = type(record)
            restored = record_type.from_json(json.dumps(record.to_dict()))
            self.assertEqual(record, restored)
            self.assertEqual(record.canonical_sha256(), restored.canonical_sha256())
            for field, value in (("unexpected", "value"), ("schema_version", "v2")):
                payload = record.to_dict()
                payload[field] = value
                with self.subTest(record=record_type.__name__, field=field):
                    with self.assertRaises(ValueError):
                        record_type.from_dict(payload)
        with self.assertRaises(ValueError):
            _supplier(source=object())

    def test_raw_json_duplicate_keys_are_rejected_at_every_depth(self) -> None:
        duplicate_top_level = json.dumps(_supplier().to_dict()).replace(
            '"supplier_id": "supplier-001",',
            '"supplier_id": "supplier-001", "supplier_id": "forged",',
        )
        duplicate_nested = json.dumps(_invoice().to_dict()).replace(
            '"line_id": "line-001",',
            '"line_id": "line-001", "line_id": "forged",',
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            CanonicalSupplier.from_json(duplicate_top_level)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            CanonicalInvoice.from_json(duplicate_nested)

    def test_all_successors_require_exact_scope_source_and_version(self) -> None:
        pairs = (
            (_invoice(), CanonicalInvoice),
            (_journal(), CanonicalJournal),
            (_balance(), CanonicalBalance),
            (_dimension(), CanonicalDimension),
        )
        for previous, record_type in pairs:
            current = replace(
                previous,
                record_version=2,
                source=_successor_source(previous.source),
            )
            current.assert_successor_of(previous)
            with self.subTest(record=record_type.__name__):
                with self.assertRaises(ValueError):
                    replace(current, legal_entity_id="entity-se-002").assert_successor_of(previous)
                with self.assertRaises(ValueError):
                    replace(current, record_version=3).assert_successor_of(previous)
        with self.assertRaises(ValueError):
            _invoice().assert_successor_of(object())  # type: ignore[arg-type]

    @PROPERTY_SETTINGS
    @given(
        net=st.integers(min_value=-(10**14), max_value=10**14),
        tax=st.integers(min_value=-(10**14), max_value=10**14),
    )
    def test_invoice_integer_arithmetic_round_trips_exactly(self, net: int, tax: int) -> None:
        gross = net + tax
        line = _invoice_line(net_minor=net, tax_minor=tax, gross_minor=gross)
        invoice = _invoice(
            lines=(line,),
            net_minor=net,
            tax_minor=tax,
            gross_minor=gross,
        )
        self.assertEqual(invoice, CanonicalInvoice.from_dict(invoice.to_dict()))


if __name__ == "__main__":
    unittest.main()
