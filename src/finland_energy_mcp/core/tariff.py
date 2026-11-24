"""Dated tax rates and household electricity contracts (Finland).

Rates change over time, so each is a table of (valid_from, value). A date before the first
entry is refused rather than guessed.

Sources (checked 2026-11-24):
- VAT 24 % until 31.8.2024, 25.5 % from 1.9.2024 (Finnish Tax Administration, vero.fi).
- Electricity tax, class I (households), excluding VAT: 2.253 c/kWh (2.24 tax + 0.013
  strategic stockpile fee) until 31.3.2026; 2.325 c/kWh (2.24 + 0.085) from 1.4.2026
  (vero.fi "Tax rates on electricity and certain fuels"; network companies publish
  2.917875 c/kWh including VAT).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# (valid_from, value) pairs, oldest first.
_VAT_RATES: tuple[tuple[date, Decimal], ...] = (
    (date(2013, 1, 1), Decimal("0.24")),
    (date(2024, 9, 1), Decimal("0.255")),
)

# Earliest entry is the oldest rate verified for this project, not the start of the tax.
_ELECTRICITY_TAX_CLASS_I_EXCL_VAT: tuple[tuple[date, Decimal], ...] = (
    (date(2025, 1, 1), Decimal("2.253")),
    (date(2026, 4, 1), Decimal("2.325")),
)


def _rate_on(table: tuple[tuple[date, Decimal], ...], day: date, name: str) -> Decimal:
    """Return the value valid on `day`: the last entry whose valid_from is not after it."""
    valid = [value for valid_from, value in table if valid_from <= day]
    if not valid:
        raise LookupError(f"no {name} known for {day.isoformat()}")
    return valid[-1]


def vat_rate(day: date) -> Decimal:
    """Finnish general VAT rate on `day`, as a fraction (0.255 = 25.5 %)."""
    return _rate_on(_VAT_RATES, day, "VAT rate")


def electricity_tax_c_per_kwh(day: date, *, include_vat: bool = True) -> Decimal:
    """Household (class I) electricity tax in cents/kWh on `day`."""
    excl_vat = _rate_on(_ELECTRICITY_TAX_CLASS_I_EXCL_VAT, day, "electricity tax")
    if not include_vat:
        return excl_vat
    return excl_vat * (1 + vat_rate(day))


def _require_non_negative(**values: Decimal) -> None:
    for name, value in values.items():
        if value < 0:
            raise ValueError(f"{name} must not be negative, got {value}")


@dataclass(frozen=True, slots=True)
class SpotContract:
    """Exchange-price contract. Prices as on Finnish consumer price lists: including VAT."""

    margin_c_per_kwh: Decimal  # retailer's margin on top of the spot price
    transfer_c_per_kwh: Decimal  # network company's transfer fee (siirtomaksu)
    monthly_fees_eur: Decimal  # retailer + network basic fees per month

    def __post_init__(self) -> None:
        _require_non_negative(
            margin_c_per_kwh=self.margin_c_per_kwh,
            transfer_c_per_kwh=self.transfer_c_per_kwh,
            monthly_fees_eur=self.monthly_fees_eur,
        )


@dataclass(frozen=True, slots=True)
class FixedContract:
    """Fixed-price contract. Prices including VAT."""

    energy_c_per_kwh: Decimal  # the fixed energy price
    transfer_c_per_kwh: Decimal
    monthly_fees_eur: Decimal

    def __post_init__(self) -> None:
        _require_non_negative(
            energy_c_per_kwh=self.energy_c_per_kwh,
            transfer_c_per_kwh=self.transfer_c_per_kwh,
            monthly_fees_eur=self.monthly_fees_eur,
        )
