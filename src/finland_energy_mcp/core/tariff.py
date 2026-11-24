"""Dated tax rates and household electricity contracts (Finland).

The rates live in tariff_rates.toml next to this file, each with the source it was checked
against. The file is loaded once and validated, so a broken edit fails immediately.
"""

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from importlib import resources
from typing import Any

RateTable = tuple[tuple[date, Decimal], ...]  # (valid_from, value) pairs, oldest first


@dataclass(frozen=True, slots=True)
class RateTables:
    """The dated rate tables from tariff_rates.toml."""

    vat: RateTable  # fraction, 0.255 = 25.5 %
    electricity_tax_class_1: RateTable  # cents/kWh without VAT


def parse_rate_tables(text: str) -> RateTables:
    """Read and validate the TOML text of a rates file. Raises ValueError if anything is wrong."""
    try:
        # parse_float=Decimal: read 0.255 exactly, never as a binary float.
        data = tomllib.loads(text, parse_float=Decimal)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"tariff rates file is not valid TOML: {error}") from error
    return RateTables(
        vat=_table(data, "vat", "rate"),
        electricity_tax_class_1=_table(data, "electricity_tax_class_1", "c_per_kwh_excl_vat"),
    )


@cache  # read the file only once (like a lazily initialised static field in Java)
def load_rate_tables() -> RateTables:
    """The rate tables shipped inside the package (tariff_rates.toml)."""
    file = resources.files("finland_energy_mcp.core").joinpath("tariff_rates.toml")
    return parse_rate_tables(file.read_text(encoding="utf-8"))


def _table(data: dict[str, Any], name: str, value_key: str) -> RateTable:
    """Validate one [[name]] list and turn it into (valid_from, value) pairs."""
    entries = data.get(name)
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"tariff rates file needs at least one [[{name}]] entry")
    rows: list[tuple[date, Decimal]] = []
    for number, entry in enumerate(entries, start=1):
        where = f"[[{name}]] entry {number}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: expected a table")
        valid_from, value, source = (
            entry.get("valid_from"),
            entry.get(value_key),
            entry.get("source"),
        )
        if not isinstance(valid_from, date) or isinstance(valid_from, datetime):
            raise ValueError(f"{where}: valid_from must be a date like 2026-04-01")
        if isinstance(value, bool) or not isinstance(value, Decimal | int):
            raise ValueError(f"{where}: {value_key} must be a number")
        if value < 0:
            raise ValueError(f"{where}: {value_key} must not be negative")
        if not isinstance(source, str) or not source.startswith(("http://", "https://")):
            raise ValueError(f"{where}: source must be a link to where the rate was checked")
        rows.append((valid_from, Decimal(value)))
    if any(later[0] <= earlier[0] for earlier, later in zip(rows, rows[1:], strict=False)):
        raise ValueError(f"[[{name}]] entries must be in date order, oldest first")
    return tuple(rows)


def _rate_on(table: RateTable, day: date, name: str) -> Decimal:
    """Return the value valid on `day`: the last entry whose valid_from is not after it."""
    valid = [value for valid_from, value in table if valid_from <= day]
    if not valid:
        raise LookupError(f"no {name} known for {day.isoformat()}")
    return valid[-1]


def vat_rate(day: date) -> Decimal:
    """Finnish general VAT rate on `day`, as a fraction (0.255 = 25.5 %)."""
    return _rate_on(load_rate_tables().vat, day, "VAT rate")


def electricity_tax_c_per_kwh(day: date, *, include_vat: bool = True) -> Decimal:
    """Household (class I) electricity tax in cents/kWh on `day`."""
    excl_vat = _rate_on(load_rate_tables().electricity_tax_class_1, day, "electricity tax")
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
