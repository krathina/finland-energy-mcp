"""Tests for loading the tax tables from tariff_rates.toml (shipped inside the package)."""

from datetime import date
from decimal import Decimal

import pytest

from finland_energy_mcp.core.tariff import load_rate_tables, parse_rate_tables

GOOD = """
[[vat]]
valid_from = 2013-01-01
rate = 0.24
source = "https://example.org/vat"

[[vat]]
valid_from = 2024-09-01
rate = 0.255
source = "https://example.org/vat"

[[electricity_tax_class_1]]
valid_from = 2025-01-01
c_per_kwh_excl_vat = 2.253
source = "https://example.org/tax"
"""


def test_parses_dates_and_exact_decimals() -> None:
    tables = parse_rate_tables(GOOD)
    assert tables.vat == ((date(2013, 1, 1), Decimal("0.24")), (date(2024, 9, 1), Decimal("0.255")))
    assert tables.electricity_tax_class_1 == ((date(2025, 1, 1), Decimal("2.253")),)


def test_the_shipped_file_loads_and_every_rate_has_a_source() -> None:
    tables = load_rate_tables()  # the real file inside the package
    assert len(tables.vat) >= 2
    assert len(tables.electricity_tax_class_1) >= 2


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("this is = not toml [", "TOML"),
        (GOOD.replace("[[vat]]", "[[other]]"), "vat"),
        (GOOD.replace('source = "https://example.org/tax"', ""), "source"),
        (GOOD.replace("rate = 0.24", "rate = -0.24"), "negative"),
        (GOOD.replace("2024-09-01", "2012-01-01"), "order"),
        (GOOD.replace("rate = 0.24", 'rate = "0.24"'), "number"),
    ],
)
def test_a_broken_file_is_refused_with_a_clear_message(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_rate_tables(text)
