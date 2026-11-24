"""Market price data types.

The Nordic day-ahead market publishes one price per period (15 minutes since autumn 2025) in
EUR/MWh, without VAT. These types hold those prices and refuse invalid data early.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

_C_PER_KWH_PER_EUR_PER_MWH = Decimal("0.1")  # 1 EUR/MWh = 100 c / 1000 kWh = 0.1 c/kWh


def eur_per_mwh_to_c_per_kwh(eur_per_mwh: Decimal) -> Decimal:
    """Convert a market price (EUR/MWh) to the unit households see (cents/kWh)."""
    return eur_per_mwh * _C_PER_KWH_PER_EUR_PER_MWH


@dataclass(frozen=True, slots=True)
class PricePoint:
    """One market period: [start, end) and its spot price in EUR/MWh, excluding VAT.

    Times are stored in UTC. Python subtracts datetimes that share a timezone by wall clock,
    which is wrong across clock changes; in UTC every hour is a real hour.
    """

    start: datetime
    end: datetime
    spot_eur_per_mwh: Decimal

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must have a timezone")
        # Frozen dataclass: normal assignment is blocked, so set the normalised values directly.
        object.__setattr__(self, "start", self.start.astimezone(UTC))
        object.__setattr__(self, "end", self.end.astimezone(UTC))
        if self.end <= self.start:
            raise ValueError("end must be after start")

    @property
    def duration(self) -> timedelta:
        """Length of the period (15 minutes on the current market)."""
        return self.end - self.start

    @property
    def spot_c_per_kwh(self) -> Decimal:
        """Spot price in cents/kWh, excluding VAT."""
        return eur_per_mwh_to_c_per_kwh(self.spot_eur_per_mwh)


class PriceSeries:
    """An ordered, gap-free run of price points (for example one delivery day).

    Validated on creation, so code that receives a PriceSeries can trust it.
    """

    def __init__(self, points: Iterable[PricePoint]) -> None:
        self._points = tuple(points)
        if not self._points:
            raise ValueError("a price series must not be empty")
        for previous, current in zip(self._points, self._points[1:], strict=False):
            if current.start != previous.end:
                raise ValueError(
                    f"gap or overlap between {previous.end.isoformat()} "
                    f"and {current.start.isoformat()}"
                )

    @property
    def start(self) -> datetime:
        """Start of the first period."""
        return self._points[0].start

    @property
    def end(self) -> datetime:
        """End of the last period."""
        return self._points[-1].end

    def __len__(self) -> int:
        return len(self._points)

    def __iter__(self) -> Iterator[PricePoint]:
        return iter(self._points)

    def __getitem__(self, index: int) -> PricePoint:
        return self._points[index]
