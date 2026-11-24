"""What a household really pays per kWh, period by period.

total = spot x (1 + VAT) + margin + transfer fee + electricity tax (incl. VAT)

Market prices come without VAT; contract prices are given including VAT (as on Finnish
consumer price lists). Rates are those valid on the Finnish local date of the period's start.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from finland_energy_mcp.core.models import PricePoint, PriceSeries
from finland_energy_mcp.core.tariff import SpotContract, electricity_tax_c_per_kwh, vat_rate

FINNISH_TIME = ZoneInfo("Europe/Helsinki")


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    """The household price of one period, in cents/kWh, every part including VAT."""

    start: datetime
    end: datetime
    spot_c_per_kwh: Decimal
    margin_c_per_kwh: Decimal
    transfer_c_per_kwh: Decimal
    electricity_tax_c_per_kwh: Decimal

    @property
    def total_c_per_kwh(self) -> Decimal:
        """Everything the household pays per kWh in this period."""
        return (
            self.spot_c_per_kwh
            + self.margin_c_per_kwh
            + self.transfer_c_per_kwh
            + self.electricity_tax_c_per_kwh
        )


def finnish_date(moment: datetime) -> date:
    """The calendar date in Finland at `moment` (which may be given in any timezone)."""
    return moment.astimezone(FINNISH_TIME).date()


def breakdown(
    point: PricePoint,
    contract: SpotContract,
    *,
    vat_on_negative: bool = False,
) -> PriceBreakdown:
    """Price one market period for a household on `contract`.

    `vat_on_negative`: whether VAT is applied when the spot price is below zero. Many Finnish
    retailers pass a negative price on without VAT, so the default is False; check the contract.
    """
    day = finnish_date(point.start)
    spot = point.spot_c_per_kwh
    if spot >= 0 or vat_on_negative:
        spot = spot * (1 + vat_rate(day))
    return PriceBreakdown(
        start=point.start,
        end=point.end,
        spot_c_per_kwh=spot,
        margin_c_per_kwh=contract.margin_c_per_kwh,
        transfer_c_per_kwh=contract.transfer_c_per_kwh,
        electricity_tax_c_per_kwh=electricity_tax_c_per_kwh(day),
    )


def breakdown_series(
    series: PriceSeries,
    contract: SpotContract,
    *,
    vat_on_negative: bool = False,
) -> list[PriceBreakdown]:
    """Price every period of `series`, in order."""
    return [breakdown(p, contract, vat_on_negative=vat_on_negative) for p in series]
