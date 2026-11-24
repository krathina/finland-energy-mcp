"""What the tools return. These pydantic models become the JSON output schemas the AI sees.

Prices are cents/kWh including VAT, rounded to 2 decimals here at the edge (the core keeps exact
Decimals). Times are Finnish local time with their UTC offset.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ContractFrom = Literal["user", "user (partly example defaults)", "example defaults"]


class Assumptions(BaseModel):
    """What the numbers are based on, so the answer can be explained honestly."""

    source: str = Field(description="Where the market prices came from")
    margin_c_per_kwh: float = Field(description="Retailer margin assumed, c/kWh incl. VAT")
    transfer_c_per_kwh: float = Field(description="Network transfer fee assumed, c/kWh incl. VAT")
    contract_from: ContractFrom = Field(
        description="Whether margin and transfer fee came from the user or are example defaults"
    )
    vat_percent: float
    electricity_tax_c_per_kwh: float = Field(description="Household electricity tax incl. VAT")
    note: str


class PriceParts(BaseModel):
    """One period's household price split into its parts, c/kWh incl. VAT."""

    spot: float = Field(description="Market (spot) price incl. VAT")
    margin: float
    transfer: float
    electricity_tax: float
    total: float = Field(description="What the household pays per kWh")


class DayRange(BaseModel):
    """Lowest, highest and average household price of a day, c/kWh."""

    min: float
    max: float
    average: float


class PriceNow(BaseModel):
    """The household electricity price right now."""

    period_start: datetime
    period_end: datetime
    price_c_per_kwh: PriceParts
    today_c_per_kwh: DayRange
    assumptions: Assumptions


class PeriodPrice(BaseModel):
    """Household price of one period (15 minutes or one hour)."""

    start: datetime
    end: datetime
    total_c_per_kwh: float
    spot_c_per_kwh: float = Field(description="Market part incl. VAT")


class DaySummary(BaseModel):
    """Quick facts about a day's prices."""

    min_c_per_kwh: float
    max_c_per_kwh: float
    average_c_per_kwh: float
    cheapest_start: datetime
    most_expensive_start: datetime


class DayPrices(BaseModel):
    """Household prices for one day."""

    day: date
    resolution: Literal["hour", "15min"]
    periods: list[PeriodPrice]
    summary: DaySummary
    assumptions: Assumptions


class StartNow(BaseModel):
    """The same job started in the current period, for comparison."""

    start: datetime
    average_c_per_kwh: float
    cost_eur: float | None
    extra_cost_eur: float | None = Field(
        description="How much more starting now costs than the cheapest time"
    )


class CheapestTime(BaseModel):
    """The cheapest time to run something for a given duration."""

    start: datetime
    end: datetime
    duration_minutes: int
    average_c_per_kwh: float
    cost_eur: float | None = Field(description="Only when energy_kwh was given")
    if_started_now: StartNow | None = Field(
        description="Starting right away instead; missing if prices don't reach that far"
    )
    assumptions: Assumptions
