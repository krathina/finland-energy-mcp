"""The interface every price source implements."""

from typing import Protocol

from finland_energy_mcp.core.models import PriceSeries


class PriceSource(Protocol):
    """Something that can provide the latest Finnish day-ahead prices.

    Structural interface: a class fits if it has these members; no inheritance needed.
    """

    @property
    def name(self) -> str:
        """Short source name for messages and attribution, e.g. "spot-hinta.fi"."""
        ...

    def latest_prices(self) -> PriceSeries:
        """Today's prices, plus tomorrow's once published (around 14:00 Finnish time).

        Raises a PriceSourceError subclass on failure.
        """
        ...
