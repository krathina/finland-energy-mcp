"""spot-hinta.fi: free Nordic day-ahead prices (https://api.spot-hinta.fi, docs at /swagger/ui).

Response of GET /TodayAndDayForward (region FI by default) is a JSON list of objects like
    {"Rank": 13, "DateTime": "2026-11-24T00:00:00+02:00", "PriceNoTax": 0.01706,
     "PriceWithTax": 0.02141}
- DateTime: start of the period, with the Finnish UTC offset.
- PriceNoTax: EUR/kWh without VAT. We use only this and add VAT ourselves for the right date.
- Documented limit: one request per minute per IP, at most 1,440 per day (HTTP 429 above it).
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Self

import httpx

from finland_energy_mcp.about import user_agent
from finland_energy_mcp.core.models import PricePoint, PriceSeries
from finland_energy_mcp.sources.errors import (
    PriceSourceError,
    RateLimitedError,
    SourceFormatError,
    SourceUnavailableError,
)

_EUR_PER_MWH_PER_EUR_PER_KWH = Decimal(1000)
_DEFAULT_PERIOD = timedelta(minutes=15)  # used when the response has a single entry


def parse_spot_hinta(text: str) -> PriceSeries:
    """Turn the raw JSON text of a spot-hinta.fi price list into a PriceSeries.

    Raises SourceFormatError if the data is not what we expect.
    """
    try:
        # parse_float=Decimal: read 0.01706 exactly, never as a binary float.
        data = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError as error:
        raise SourceFormatError(f"response is not valid JSON: {error}") from error
    if not isinstance(data, list):
        raise SourceFormatError(f"expected a JSON list, got {type(data).__name__}")
    if not data:
        raise SourceFormatError("response is an empty list")

    rows = sorted((_parse_row(item) for item in data), key=lambda row: row[0])
    period = _period(rows)
    try:
        return PriceSeries(
            PricePoint(start=start, end=start + period, spot_eur_per_mwh=price)
            for start, price in rows
        )
    except ValueError as error:  # gaps, overlaps: PriceSeries explains which
        raise SourceFormatError(str(error)) from error


def _parse_row(item: object) -> tuple[datetime, Decimal]:
    """One list entry -> (start time, price in EUR/MWh without VAT)."""
    if not isinstance(item, dict):
        raise SourceFormatError(f"expected an object in the list, got {type(item).__name__}")

    raw_time = item.get("DateTime")
    if not isinstance(raw_time, str):
        raise SourceFormatError(f"missing or invalid DateTime in {item}")
    try:
        start = datetime.fromisoformat(raw_time)
    except ValueError as error:
        raise SourceFormatError(f"invalid DateTime {raw_time!r}") from error
    if start.tzinfo is None:
        raise SourceFormatError(f"DateTime {raw_time!r} has no timezone offset")

    raw_price = item.get("PriceNoTax")
    if isinstance(raw_price, bool) or not isinstance(raw_price, Decimal | int):
        raise SourceFormatError(f"missing or invalid PriceNoTax in {item}")
    try:
        price = Decimal(raw_price) * _EUR_PER_MWH_PER_EUR_PER_KWH
    except InvalidOperation as error:
        raise SourceFormatError(f"invalid PriceNoTax in {item}") from error
    return start, price


def _period(rows: list[tuple[datetime, Decimal]]) -> timedelta:
    """Length of one period: the smallest step between starts (so a missing one shows as a gap)."""
    if len(rows) == 1:
        return _DEFAULT_PERIOD
    return min(b[0] - a[0] for a, b in zip(rows, rows[1:], strict=False))


class SpotHintaSource:
    """HTTP client for spot-hinta.fi, with a cache that keeps us within its rate limit.

    Use as a context manager (`with SpotHintaSource() as source:`) so its HTTP connection is
    closed. A client passed in by the caller is left for the caller to close.
    """

    DEFAULT_BASE_URL = "https://api.spot-hinta.fi"
    _RATE_LIMIT = timedelta(minutes=1)  # documented: one request per minute per IP

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cache_for: timedelta = timedelta(minutes=15),
        timeout_seconds: float = 10.0,
    ) -> None:
        if cache_for < self._RATE_LIMIT:
            raise ValueError("cache_for must be at least one minute (the source's rate limit)")
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._clock = clock
        self._cache_for = cache_for
        self._cached: tuple[datetime, PriceSeries] | None = None

    @property
    def name(self) -> str:
        """Source name, for messages and attribution."""
        return "spot-hinta.fi"

    def latest_prices(self) -> PriceSeries:
        """Today's prices and tomorrow's (once published); cached for `cache_for`."""
        now = self._clock()
        if self._cached is not None and now - self._cached[0] < self._cache_for:
            return self._cached[1]
        series = parse_spot_hinta(self._get("/TodayAndDayForward"))
        self._cached = (now, series)  # cache only successful, valid answers
        return series

    def _get(self, path: str) -> str:
        try:
            # Set per request, so it is sent even with a client passed in by the caller.
            response = self._client.get(path, headers={"User-Agent": user_agent()})
        except httpx.TimeoutException as error:
            raise SourceUnavailableError(f"{self.name} timed out: {error}") from error
        except httpx.TransportError as error:
            raise SourceUnavailableError(f"{self.name} could not be reached: {error}") from error

        status = response.status_code
        if status == 429:
            raise RateLimitedError(f"{self.name} rate limit reached (HTTP 429); try again later")
        if status >= 500:
            raise SourceUnavailableError(f"{self.name} failed with HTTP {status}")
        if status != 200:
            raise PriceSourceError(f"{self.name} answered with unexpected HTTP {status}")
        return response.text

    def close(self) -> None:
        """Close the HTTP connection, if this object created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
