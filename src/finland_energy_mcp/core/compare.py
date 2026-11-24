"""Fixed-price contract vs spot contract, for a given usage.

On spot, the cost depends on *when* power is used; on fixed, only on *how much*. So the
comparison needs usage per period, aligned with the price series.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finland_energy_mcp.core.models import PriceSeries
from finland_energy_mcp.core.pricing import breakdown, finnish_date
from finland_energy_mcp.core.tariff import FixedContract, SpotContract, electricity_tax_c_per_kwh


@dataclass(frozen=True, slots=True)
class ContractCost:
    """What one contract would have cost."""

    energy_eur: Decimal  # all per-kWh parts: energy, margin, transfer, tax, VAT
    fees_eur: Decimal  # monthly basic fees for the months included
    average_c_per_kwh: Decimal  # energy_eur per kWh used, in cents (usage-weighted)

    @property
    def total_eur(self) -> Decimal:
        """Energy plus fees."""
        return self.energy_eur + self.fees_eur


@dataclass(frozen=True, slots=True)
class Comparison:
    """Spot vs fixed for the same usage."""

    total_kwh: Decimal
    spot: ContractCost
    fixed: ContractCost
    break_even_fixed_c_per_kwh: Decimal  # fixed energy price at which both cost the same

    @property
    def cheaper(self) -> Literal["spot", "fixed", "same"]:
        """Which contract costs less."""
        if self.spot.total_eur < self.fixed.total_eur:
            return "spot"
        if self.fixed.total_eur < self.spot.total_eur:
            return "fixed"
        return "same"

    @property
    def saving_eur(self) -> Decimal:
        """How much the cheaper contract saves."""
        return abs(self.spot.total_eur - self.fixed.total_eur)


def flat_usage(series: PriceSeries, total_kwh: Decimal) -> list[Decimal]:
    """Spread `total_kwh` evenly over every period of `series`."""
    share = total_kwh / len(series)
    return [share] * len(series)


def compare_contracts(
    series: PriceSeries,
    usage_kwh: Sequence[Decimal],
    spot: SpotContract,
    fixed: FixedContract,
    *,
    fee_months: Decimal = Decimal(0),
    vat_on_negative: bool = False,
) -> Comparison:
    """Cost of `usage_kwh` (one value per period of `series`) on each contract.

    `fee_months`: how many months of basic fees to include (0 = energy costs only).
    """
    if len(usage_kwh) != len(series):
        raise ValueError(f"usage has {len(usage_kwh)} values but prices have {len(series)} periods")
    if any(u < 0 for u in usage_kwh):
        raise ValueError("usage must not be negative")
    total_kwh = sum(usage_kwh, Decimal(0))
    if total_kwh == 0:
        raise ValueError("usage must not be zero in total")

    spot_cents = Decimal(0)
    fixed_cents = Decimal(0)
    fixed_cents_without_energy = Decimal(0)  # transfer + tax: needed for the break-even price
    for point, used in zip(series, usage_kwh, strict=True):
        spot_cents += used * breakdown(point, spot, vat_on_negative=vat_on_negative).total_c_per_kwh
        other = fixed.transfer_c_per_kwh + electricity_tax_c_per_kwh(finnish_date(point.start))
        fixed_cents += used * (fixed.energy_c_per_kwh + other)
        fixed_cents_without_energy += used * other

    spot_cost = _cost(spot_cents, spot.monthly_fees_eur * fee_months, total_kwh)
    fixed_cost = _cost(fixed_cents, fixed.monthly_fees_eur * fee_months, total_kwh)

    # Solve fixed_total(E) == spot_total for the fixed energy price E (cents/kWh):
    #   (E * total_kwh + fixed_cents_without_energy) / 100 + fixed_fees = spot_total
    break_even = (
        (spot_cost.total_eur - fixed_cost.fees_eur) * 100 - fixed_cents_without_energy
    ) / total_kwh

    return Comparison(
        total_kwh=total_kwh,
        spot=spot_cost,
        fixed=fixed_cost,
        break_even_fixed_c_per_kwh=break_even,
    )


def _cost(cents: Decimal, fees_eur: Decimal, total_kwh: Decimal) -> ContractCost:
    return ContractCost(
        energy_eur=cents / 100,
        fees_eur=fees_eur,
        average_c_per_kwh=cents / total_kwh,
    )
