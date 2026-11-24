"""Tests for the spot-hinta.fi HTTP client, using a fake server (httpx.MockTransport)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from finland_energy_mcp.sources.base import PriceSource
from finland_energy_mcp.sources.errors import (
    PriceSourceError,
    RateLimitedError,
    SourceFormatError,
    SourceUnavailableError,
)
from finland_energy_mcp.sources.spot_hinta import SpotHintaSource

BODY = (
    Path(__file__).parent / "fixtures" / "spot_hinta_today_and_day_forward_2026-11-24.json"
).read_text()


class FakeClock:
    """A clock the test can move forward (instead of waiting in real time)."""

    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class FakeServer:
    """Records requests and answers each with `respond(request)`."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


def source_for(server: FakeServer, clock: FakeClock | None = None) -> SpotHintaSource:
    client = httpx.Client(
        transport=httpx.MockTransport(server.handle), base_url=SpotHintaSource.BASE_URL
    )
    return SpotHintaSource(client=client, clock=clock or FakeClock())


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=BODY)


# --- happy path ----------------------------------------------------------------


def test_fetches_and_parses_today_and_tomorrow() -> None:
    server = FakeServer(ok)
    prices = source_for(server).latest_prices()
    assert len(prices) == 192
    assert len(server.requests) == 1
    assert server.requests[0].method == "GET"
    assert server.requests[0].url.path == "/TodayAndDayForward"


def test_identifies_itself_with_a_user_agent() -> None:
    server = FakeServer(ok)
    source_for(server).latest_prices()
    assert server.requests[0].headers["User-Agent"].startswith("finland-energy-mcp/")


def test_is_a_price_source() -> None:
    source: PriceSource = source_for(FakeServer(ok))  # mypy checks this matches the interface
    assert source.name == "spot-hinta.fi"


# --- caching (respects the 1 request/minute limit) ------------------------------------


def test_reuses_the_answer_within_the_cache_time() -> None:
    server, clock = FakeServer(ok), FakeClock()
    source = source_for(server, clock)
    source.latest_prices()
    clock.now += timedelta(minutes=14)
    source.latest_prices()
    assert len(server.requests) == 1


def test_asks_again_after_the_cache_time() -> None:
    server, clock = FakeServer(ok), FakeClock()
    source = source_for(server, clock)
    source.latest_prices()
    clock.now += timedelta(minutes=15)
    source.latest_prices()
    assert len(server.requests) == 2


def test_cache_time_can_never_be_below_the_rate_limit() -> None:
    with pytest.raises(ValueError, match="minute"):
        SpotHintaSource(cache_for=timedelta(seconds=30))


# --- failures ------------------------------------------------------------------------


def test_rate_limit_becomes_rate_limited_error_and_is_not_cached() -> None:
    answers = iter([httpx.Response(429), httpx.Response(200, text=BODY)])
    server = FakeServer(lambda _: next(answers))
    source = source_for(server)
    with pytest.raises(RateLimitedError):
        source.latest_prices()
    assert len(source.latest_prices()) == 192  # tried again, not a cached error


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_mean_the_source_is_unavailable(status: int) -> None:
    with pytest.raises(SourceUnavailableError, match=str(status)):
        source_for(FakeServer(lambda _: httpx.Response(status))).latest_prices()


def test_timeout_means_the_source_is_unavailable() -> None:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(SourceUnavailableError, match="timed out"):
        source_for(FakeServer(time_out)).latest_prices()


def test_other_http_errors_are_reported_with_their_status() -> None:
    with pytest.raises(PriceSourceError, match="404"):
        source_for(FakeServer(lambda _: httpx.Response(404))).latest_prices()


def test_unexpected_body_is_a_format_error() -> None:
    with pytest.raises(SourceFormatError):
        source_for(
            FakeServer(lambda _: httpx.Response(200, text="<html>maintenance</html>"))
        ).latest_prices()


# --- resources -----------------------------------------------------------------------


def test_closes_its_own_http_client_when_used_with_with() -> None:
    with SpotHintaSource() as source:
        client = source._client
    assert client.is_closed


def test_leaves_an_injected_client_open() -> None:
    client = httpx.Client(transport=httpx.MockTransport(ok))
    with SpotHintaSource(client=client):
        pass
    assert not client.is_closed
    client.close()
