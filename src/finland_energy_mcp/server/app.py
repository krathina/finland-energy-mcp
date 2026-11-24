"""The MCP server: tools an AI assistant can call to answer Finnish electricity price questions.

`build_server` takes the price source, settings and clock as arguments (dependency injection), so
tests can run the real server with fake data and a fixed time.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from finland_energy_mcp import about
from finland_energy_mcp.core.planner import Window, cheapest_window
from finland_energy_mcp.core.pricing import (
    FINNISH_TIME,
    PriceBreakdown,
    breakdown_series,
    finnish_date,
)
from finland_energy_mcp.core.tariff import electricity_tax_c_per_kwh, vat_rate
from finland_energy_mcp.server.schemas import (
    Assumptions,
    CheapestTime,
    DayPrices,
    DayRange,
    DaySummary,
    PeriodPrice,
    PriceNow,
    PriceParts,
    StartNow,
)
from finland_energy_mcp.server.settings import Settings
from finland_energy_mcp.sources.base import PriceSource
from finland_energy_mcp.sources.errors import PriceSourceError

INSTRUCTIONS = (
    "Finnish household electricity prices (spot contracts). Prices are what a household pays "
    "per kWh including VAT: spot price + retailer margin + transfer fee + electricity tax. "
    "Times are Finnish local time. Tomorrow's prices are published around 14:00 Finnish time. "
    "Always mention the assumed margin and transfer fee when giving prices."
)
_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)  # reads an external API
_CENT = Decimal("0.01")


def _now_utc() -> datetime:
    return datetime.now(UTC)


def build_server(
    source: PriceSource,
    settings: Settings,
    *,
    clock: Callable[[], datetime] = _now_utc,
) -> MCPServer:
    """Create the MCP server with its tools."""
    server = MCPServer(
        about.name(),
        version=about.version(),
        website_url=about.home_page(),
        instructions=INSTRUCTIONS,
    )

    def household_prices() -> list[PriceBreakdown]:
        try:
            series = source.latest_prices()
        except PriceSourceError as error:
            raise ToolError(f"Could not get prices from {source.name}: {error}") from error
        return breakdown_series(series, settings.contract, vat_on_negative=settings.vat_on_negative)

    def assumptions(day: date) -> Assumptions:
        return Assumptions(
            source=source.name,
            margin_c_per_kwh=_r(settings.margin_c_per_kwh),
            transfer_c_per_kwh=_r(settings.transfer_c_per_kwh),
            vat_percent=float(vat_rate(day) * 100),
            electricity_tax_c_per_kwh=_r(electricity_tax_c_per_kwh(day)),
            note=(
                "Prices include VAT. Margin and transfer fee are assumptions; set your own with "
                "the FINLAND_ENERGY_MARGIN_C_PER_KWH and FINLAND_ENERGY_TRANSFER_C_PER_KWH "
                "environment variables."
            ),
        )

    @server.tool(annotations=_READ_ONLY)
    def get_price_now() -> PriceNow:
        """The household electricity price right now (current 15-minute period), split into
        spot price, margin, transfer fee and tax, with today's lowest, highest and average price
        for context. Use for questions like "how much is electricity now?" or "is it cheap now?"."""
        now = clock()
        prices = household_prices()
        current = next((p for p in prices if p.start <= now < p.end), None)
        if current is None:
            raise ToolError(f"{source.name} has no price for the current moment.")
        today = [p for p in prices if finnish_date(p.start) == finnish_date(now)]
        totals = [p.total_c_per_kwh for p in today]
        return PriceNow(
            period_start=_local(current.start),
            period_end=_local(current.end),
            price_c_per_kwh=PriceParts(
                spot=_r(current.spot_c_per_kwh),
                margin=_r(current.margin_c_per_kwh),
                transfer=_r(current.transfer_c_per_kwh),
                electricity_tax=_r(current.electricity_tax_c_per_kwh),
                total=_r(current.total_c_per_kwh),
            ),
            today_c_per_kwh=DayRange(
                min=_r(min(totals)), max=_r(max(totals)), average=_r(_mean(totals))
            ),
            assumptions=assumptions(finnish_date(now)),
        )

    @server.tool(annotations=_READ_ONLY)
    def get_prices(
        day: Annotated[
            Literal["today", "tomorrow"],
            Field(description="Which Finnish calendar day"),
        ] = "today",
        resolution: Annotated[
            Literal["hour", "15min"],
            Field(description="'hour' (24 rows, easier to read) or '15min' (the market's own)"),
        ] = "hour",
    ) -> DayPrices:
        """Household electricity prices for today or tomorrow, per hour or per 15 minutes, with
        the day's cheapest and most expensive times. Use for "prices today/tomorrow?" or to
        see when electricity is cheap. Tomorrow's prices appear around 14:00 Finnish time."""
        target = finnish_date(clock()) + timedelta(days=1 if day == "tomorrow" else 0)
        periods = [p for p in household_prices() if finnish_date(p.start) == target]
        if not periods:
            if day == "tomorrow":
                raise ToolError(
                    f"Prices for tomorrow ({target.isoformat()}) are not published yet. The "
                    "day-ahead market publishes them around 14:00 Finnish time."
                )
            raise ToolError(f"{source.name} has no prices for today ({target.isoformat()}).")
        rows = _hourly(periods) if resolution == "hour" else [_row(p) for p in periods]
        cheapest = min(rows, key=lambda r: r.total_c_per_kwh)
        dearest = max(rows, key=lambda r: r.total_c_per_kwh)
        return DayPrices(
            day=target,
            resolution=resolution,
            periods=rows,
            summary=DaySummary(
                min_c_per_kwh=cheapest.total_c_per_kwh,
                max_c_per_kwh=dearest.total_c_per_kwh,
                average_c_per_kwh=_r(_mean([p.total_c_per_kwh for p in periods])),
                cheapest_start=cheapest.start,
                most_expensive_start=dearest.start,
            ),
            assumptions=assumptions(target),
        )

    @server.tool(annotations=_READ_ONLY)
    def find_cheapest_time(
        duration_minutes: Annotated[
            int,
            Field(
                ge=15,
                le=1440,
                multiple_of=15,
                description="How long it runs, in whole quarter-hours (e.g. 120 for 2 hours)",
            ),
        ],
        earliest_start: Annotated[
            datetime | None,
            Field(
                description="Earliest start; without a UTC offset it is Finnish time. Default: now"
            ),
        ] = None,
        finish_by: Annotated[
            datetime | None,
            Field(
                description="Must be finished by; Finnish time if no offset. Default: as late "
                "as prices are known"
            ),
        ] = None,
        energy_kwh: Annotated[
            float | None,
            Field(ge=0, description="Energy it uses in total, to estimate the cost in euros"),
        ] = None,
    ) -> CheapestTime:
        """Find the cheapest continuous time to run something (sauna, laundry, dishwasher, EV
        charging) for a given duration, between an earliest start and a deadline. Also shows
        what starting right now would cost instead. Prices are known until the end of today,
        or tomorrow after about 14:00 Finnish time."""
        now = clock()
        prices = household_prices()
        duration = timedelta(minutes=duration_minutes)
        earliest = max(_finnish(earliest_start), now) if earliest_start else now
        deadline = _finnish(finish_by) if finish_by else prices[-1].end
        known_until = _local(prices[-1].end).isoformat(timespec="minutes")
        # Check unknown prices first: with no finish_by, the default deadline is the end of the
        # known prices, which would otherwise give a confusing "finish_by" message.
        if earliest + duration > prices[-1].end:
            raise ToolError(
                f"Prices are only known until {known_until}, so a {duration_minutes}-minute job "
                "can't be planned from that start. Tomorrow's prices appear around 14:00 Finnish "
                "time."
            )
        if deadline <= earliest:
            raise ToolError("finish_by must be after the earliest start (and after now).")
        kwh = None if energy_kwh is None else Decimal(str(energy_kwh))
        try:
            best = cheapest_window(
                prices, duration, earliest=earliest, deadline=deadline, energy_kwh=kwh
            )
        except ValueError as error:
            raise ToolError(
                f"No {duration_minutes}-minute window fits between "
                f"{_local(earliest).isoformat(timespec='minutes')} and "
                f"{_local(deadline).isoformat(timespec='minutes')} (prices known until "
                f"{known_until})."
            ) from error
        return CheapestTime(
            start=_local(best.start),
            end=_local(best.end),
            duration_minutes=duration_minutes,
            average_c_per_kwh=_r(best.average_c_per_kwh),
            cost_eur=None if best.cost_eur is None else _r(best.cost_eur),
            if_started_now=_start_now(prices, now, duration, kwh, best),
            assumptions=assumptions(finnish_date(best.start)),
        )

    return server


# --- helpers ------------------------------------------------------------------------------


def _r(value: Decimal) -> float:
    """Round to 2 decimals for the answer (exact Decimals stay inside the core)."""
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _local(moment: datetime) -> datetime:
    return moment.astimezone(FINNISH_TIME)


def _row(p: PriceBreakdown) -> PeriodPrice:
    return PeriodPrice(
        start=_local(p.start),
        end=_local(p.end),
        total_c_per_kwh=_r(p.total_c_per_kwh),
        spot_c_per_kwh=_r(p.spot_c_per_kwh),
    )


def _hourly(periods: Sequence[PriceBreakdown]) -> list[PeriodPrice]:
    """Average quarter-hours into hours. Grouped in UTC: Finnish hours start on UTC hours, and
    UTC keeps the repeated hour of the autumn clock change as two separate hours."""
    hours: dict[datetime, list[PriceBreakdown]] = defaultdict(list)
    for p in periods:
        hours[p.start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)].append(p)
    return [
        PeriodPrice(
            start=_local(hour),
            end=_local(hour + timedelta(hours=1)),
            total_c_per_kwh=_r(_mean([p.total_c_per_kwh for p in group])),
            spot_c_per_kwh=_r(_mean([p.spot_c_per_kwh for p in group])),
        )
        for hour, group in sorted(hours.items())
    ]


def _finnish(moment: datetime) -> datetime:
    """A time from the AI: without an offset it means Finnish time."""
    return moment.replace(tzinfo=FINNISH_TIME) if moment.tzinfo is None else moment


def _start_now(
    prices: Sequence[PriceBreakdown],
    now: datetime,
    duration: timedelta,
    kwh: Decimal | None,
    best: Window,
) -> StartNow | None:
    """The same job starting in the current period, or None if prices don't reach that far."""
    current = next((p for p in prices if p.start <= now < p.end), None)
    if current is None or current.start + duration > prices[-1].end:
        return None
    now_window = cheapest_window(
        prices,
        duration,
        earliest=current.start,
        deadline=current.start + duration,
        energy_kwh=kwh,
    )
    extra = (
        None
        if now_window.cost_eur is None or best.cost_eur is None
        else now_window.cost_eur - best.cost_eur
    )
    return StartNow(
        start=_local(now_window.start),
        average_c_per_kwh=_r(now_window.average_c_per_kwh),
        cost_eur=None if now_window.cost_eur is None else _r(now_window.cost_eur),
        extra_cost_eur=None if extra is None else _r(extra),
    )
