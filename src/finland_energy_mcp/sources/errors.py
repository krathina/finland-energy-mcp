"""Errors raised by price sources. Callers can catch PriceSourceError for all of them."""


class PriceSourceError(Exception):
    """Base class: something went wrong getting prices from a source."""


class SourceFormatError(PriceSourceError):
    """The source answered, but not in the format we expect (it may have changed its API)."""


class RateLimitedError(PriceSourceError):
    """The source refused because we asked too often (HTTP 429)."""


class SourceUnavailableError(PriceSourceError):
    """The source could not be reached or failed (timeout, network error, HTTP 5xx)."""
