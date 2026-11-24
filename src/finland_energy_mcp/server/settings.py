"""Server settings, read from environment variables (all optional).

Every variable starts with FINLAND_ENERGY_; see .env.example for the full list. Contract defaults
are an example Helsinki spot contract, not anyone's real contract, and every tool answer repeats
the values it used.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from finland_energy_mcp.core.tariff import SpotContract
from finland_energy_mcp.sources.spot_hinta import SpotHintaSource

ENV_PREFIX = "FINLAND_ENERGY_"


@dataclass(frozen=True, slots=True)
class Settings:
    """All settings with their defaults. `Settings()` gives the defaults; use `from_env()`."""

    # Household contract (cents/kWh incl. VAT) used to turn market prices into household prices.
    margin_c_per_kwh: Decimal = Decimal("0.49")
    transfer_c_per_kwh: Decimal = Decimal("3.5")
    vat_on_negative: bool = False
    # Price source: spot-hinta.fi.
    spot_hinta_base_url: str = SpotHintaSource.DEFAULT_BASE_URL
    request_timeout_seconds: float = 10.0
    cache_for: timedelta = timedelta(minutes=15)

    @property
    def contract(self) -> SpotContract:
        """The spot contract these settings describe (monthly fees are not used by the tools)."""
        return SpotContract(
            margin_c_per_kwh=self.margin_c_per_kwh,
            transfer_c_per_kwh=self.transfer_c_per_kwh,
            monthly_fees_eur=Decimal(0),
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        """Read the FINLAND_ENERGY_* variables; anything not set (or empty) keeps its default.

        Raises ValueError naming the variable when a value is invalid.
        """
        d = cls()  # the defaults
        return cls(
            margin_c_per_kwh=_decimal(env, "MARGIN_C_PER_KWH", d.margin_c_per_kwh),
            transfer_c_per_kwh=_decimal(env, "TRANSFER_C_PER_KWH", d.transfer_c_per_kwh),
            vat_on_negative=_bool(env, "VAT_ON_NEGATIVE", d.vat_on_negative),
            spot_hinta_base_url=_url(env, "SPOT_HINTA_BASE_URL", d.spot_hinta_base_url),
            request_timeout_seconds=_positive_float(
                env, "REQUEST_TIMEOUT_SECONDS", d.request_timeout_seconds
            ),
            cache_for=timedelta(minutes=_minutes(env, "CACHE_MINUTES", d.cache_for)),
        )


# --- one small reader per kind of value ---------------------------------------------------


def _raw(env: Mapping[str, str], key: str) -> str | None:
    """The variable's value without surrounding spaces, or None if unset or empty."""
    value = env.get(ENV_PREFIX + key, "").strip()
    return value or None


def _decimal(env: Mapping[str, str], key: str, default: Decimal) -> Decimal:
    raw = _raw(env, key)
    if raw is None:
        return default
    try:
        return Decimal(raw.replace(",", "."))  # accept the Finnish decimal comma too
    except InvalidOperation as error:
        raise ValueError(f"{ENV_PREFIX}{key} must be a number, got {raw!r}") from error


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = _raw(env, key)
    return default if raw is None else raw.lower() in {"1", "true", "yes"}


def _url(env: Mapping[str, str], key: str, default: str) -> str:
    raw = _raw(env, key)
    if raw is None:
        return default
    if not raw.startswith(("http://", "https://")):
        raise ValueError(f"{ENV_PREFIX}{key} must start with http:// or https://, got {raw!r}")
    return raw.rstrip("/")


def _positive_float(env: Mapping[str, str], key: str, default: float) -> float:
    value = float(_decimal(env, key, Decimal(str(default))))
    if value <= 0:
        raise ValueError(f"{ENV_PREFIX}{key} must be greater than 0, got {value}")
    return value


def _minutes(env: Mapping[str, str], key: str, default: timedelta) -> int:
    value = _decimal(env, key, Decimal(int(default.total_seconds() // 60)))
    if value != value.to_integral_value():
        raise ValueError(f"{ENV_PREFIX}{key} must be a whole number of minutes, got {value}")
    if value < 1:
        raise ValueError(f"{ENV_PREFIX}{key} must be at least 1 (rate limit), got {value}")
    return int(value)
