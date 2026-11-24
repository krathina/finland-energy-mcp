"""Household contract settings, read from environment variables.

Defaults are an example Helsinki spot contract, not anyone's real contract. Every tool answer
repeats the values it used, so the AI can say what it assumed.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from finland_energy_mcp.core.tariff import SpotContract

ENV_PREFIX = "FINLAND_ENERGY_"


@dataclass(frozen=True, slots=True)
class Settings:
    """Contract values used to turn market prices into household prices (cents/kWh incl. VAT)."""

    margin_c_per_kwh: Decimal = Decimal("0.49")
    transfer_c_per_kwh: Decimal = Decimal("3.5")
    vat_on_negative: bool = False

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
        """Read FINLAND_ENERGY_MARGIN_C_PER_KWH, FINLAND_ENERGY_TRANSFER_C_PER_KWH and
        FINLAND_ENERGY_VAT_ON_NEGATIVE; anything not set keeps its default."""
        defaults = cls()
        return cls(
            margin_c_per_kwh=_decimal(env, "MARGIN_C_PER_KWH", defaults.margin_c_per_kwh),
            transfer_c_per_kwh=_decimal(env, "TRANSFER_C_PER_KWH", defaults.transfer_c_per_kwh),
            vat_on_negative=env.get(ENV_PREFIX + "VAT_ON_NEGATIVE", "").lower()
            in {"1", "true", "yes"},
        )


def _decimal(env: Mapping[str, str], key: str, default: Decimal) -> Decimal:
    raw = env.get(ENV_PREFIX + key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return Decimal(raw.strip().replace(",", "."))  # accept the Finnish decimal comma too
    except InvalidOperation as error:
        raise ValueError(f"{ENV_PREFIX}{key} must be a number, got {raw!r}") from error
