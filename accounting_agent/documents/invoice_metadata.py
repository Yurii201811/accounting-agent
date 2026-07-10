"""Best-effort invoice metadata extraction for local fixtures.

This is intentionally conservative. It recognizes simple text labels in local
fixtures and leaves OCR/PDF extraction to a later integration layer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


_LABELS = {
    "invoice_number": re.compile(
        r"(?im)^\s*(invoice\s*(number|no\.?)|fakturanummer|faktura\s*nr)\s*[:#-]\s*(?P<value>.+?)\s*$"
    ),
    "supplier": re.compile(
        r"(?im)^\s*(supplier|vendor|leverantor)\s*[:#-]\s*(?P<value>.+?)\s*$"
    ),
    "invoice_date": re.compile(
        r"(?im)^\s*(invoice\s*date|date|fakturadatum)\s*[:#-]\s*(?P<value>\d{4}-\d{2}-\d{2})\s*$"
    ),
    "amount": re.compile(
        r"(?im)^\s*(amount|total|summa)\s*[:#-]\s*(?P<value>.+?)\s*$"
    ),
}


@dataclass(frozen=True)
class InvoiceMetadata:
    invoice_number: str | None = None
    supplier: str | None = None
    invoice_date: str | None = None
    amount_minor: int | None = None
    currency: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def duplicate_key(self, *, client_id: str) -> str | None:
        """Return a deterministic metadata key when enough fields are present."""

        if not self.invoice_number or not self.supplier:
            return None
        parts = [
            _normalize(client_id),
            _normalize(self.supplier),
            _normalize(self.invoice_number),
            _normalize(self.invoice_date or ""),
            str(self.amount_minor or ""),
            _normalize(self.currency or ""),
        ]
        return "|".join(parts)


def extract_invoice_metadata(path: str | Path) -> InvoiceMetadata:
    """Extract simple invoice fields from text-like local files."""

    text = _read_small_text(Path(path))
    if not text:
        return InvoiceMetadata()

    raw_amount = _first_match(text, "amount")
    amount_minor, currency = _parse_amount(raw_amount)
    return InvoiceMetadata(
        invoice_number=_first_match(text, "invoice_number"),
        supplier=_first_match(text, "supplier"),
        invoice_date=_first_match(text, "invoice_date"),
        amount_minor=amount_minor,
        currency=currency,
    )


def _read_small_text(path: Path, *, limit: int = 256_000) -> str:
    try:
        data = path.read_bytes()[:limit]
    except OSError:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _first_match(text: str, field: str) -> str | None:
    match = _LABELS[field].search(text)
    if match is None:
        return None
    value = " ".join(match.group("value").strip().split())
    return value or None


def _parse_amount(value: str | None) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    match = re.search(r"(?P<amount>-?\d[\d\s.,]*)\s*(?P<currency>[A-Za-z]{3})?", value)
    if match is None:
        return None, None

    amount = match.group("amount").replace(" ", "")
    if "," in amount and "." in amount:
        amount = amount.replace(",", "")
    elif "," in amount:
        amount = amount.replace(",", ".")

    try:
        decimal_amount = Decimal(amount)
    except InvalidOperation:
        return None, _currency(match)

    minor = int((decimal_amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return minor, _currency(match)


def _currency(match: re.Match[str]) -> str | None:
    currency = match.group("currency")
    return currency.upper() if currency else None


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())
