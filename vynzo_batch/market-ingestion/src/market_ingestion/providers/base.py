"""The contract every market-data provider adapter implements."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RawRecord:
    """A record exactly as the provider returned it. Raw data is immutable (rule 2).

    `bar_ts` is tz-aware UTC.
    """

    provider: str
    provider_symbol: str
    timeframe: str
    bar_ts: datetime
    payload: dict[str, Any]


class Provider(Protocol):
    name: str

    def fetch_bars(
        self, provider_symbol: str, timeframe: str, start: date | None, end: date
    ) -> list[RawRecord]:
        """Fetch bars; `start=None` means full history."""
        ...
