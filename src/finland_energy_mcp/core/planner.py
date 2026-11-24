"""Find the cheapest time to run something (sauna, laundry, EV charging).

Works on household prices (see pricing.py), so the answer reflects what the household pays.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol


class Priced(Protocol):
    """What the planner needs from each period. Any object with these read-only attributes
    fits (structural typing), e.g. pricing.PriceBreakdown; it doesn't have to inherit this."""

    @property
    def start(self) -> datetime: ...
    @property
    def end(self) -> datetime: ...
    @property
    def total_c_per_kwh(self) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class Window:
    """A continuous run of periods: when to start, when it ends, and what it costs."""

    start: datetime
    end: datetime
    average_c_per_kwh: Decimal
    cost_eur: Decimal | None  # set only when the energy use was given


def cheapest_window(
    prices: Sequence[Priced],
    duration: timedelta,
    *,
    earliest: datetime | None = None,
    deadline: datetime | None = None,
    energy_kwh: Decimal | None = None,
) -> Window:
    """The cheapest continuous window of `duration` that starts at or after `earliest` and ends
    by `deadline`. Ties go to the earliest window.

    `prices` must be consecutive periods of equal length (as produced from a PriceSeries).
    `energy_kwh`, if given, is spread evenly over the window to compute the cost in euros.
    """
    candidates = [
        p
        for p in prices
        if (earliest is None or p.start >= earliest) and (deadline is None or p.end <= deadline)
    ]
    if not candidates:
        raise ValueError("no window: no prices between the earliest start and the deadline")

    period = candidates[0].end - candidates[0].start
    if duration <= timedelta(0) or duration % period:
        raise ValueError(f"duration must be a positive multiple of the price period ({period})")
    count = duration // period
    if count > len(candidates):
        raise ValueError(f"no window of {duration} fits between the earliest start and deadline")

    # Sliding window: keep a running sum; moving one step adds the next period, drops the first.
    totals = [p.total_c_per_kwh for p in candidates]
    window_sum = sum(totals[:count], Decimal(0))
    best_sum, best_index = window_sum, 0
    for i in range(1, len(totals) - count + 1):
        window_sum += totals[i + count - 1] - totals[i - 1]
        if window_sum < best_sum:  # strictly less: ties keep the earlier window
            best_sum, best_index = window_sum, i

    average = best_sum / count
    return Window(
        start=candidates[best_index].start,
        end=candidates[best_index + count - 1].end,
        average_c_per_kwh=average,
        cost_eur=None if energy_kwh is None else energy_kwh * average / 100,
    )
