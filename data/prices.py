"""Fetch a historical daily close series from FMP for the price-risk engine.

Lives in the data layer (it talks to FMP) and does NO finance math — it returns a plain
list of closing prices in chronological order (oldest → newest), which `engine.montecarlo`
turns into drift/volatility estimates and a Monte Carlo simulation.

This is a SINGLE cached call per ticker (see the `st.cache_data` wrapper in the UI). FMP's
end-of-day history endpoint has changed names across plan tiers, so we try the modern
``/stable`` name first and fall back to the legacy one; both share the ``date``/``close``
field shape (the legacy endpoint nests rows under a ``historical`` key, which we unwrap).
"""

from __future__ import annotations

from typing import Any

from data.fmp_client import FMPClient, FMPError, FMPNotFound

# Candidate endpoint names, newest first. `client.get` already tries stable then legacy
# URL *shapes* for each name; we additionally try both names because FMP renamed this one.
_PRICE_ENDPOINTS = ("historical-price-eod/full", "historical-price-full")


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_rows(payload: list) -> list[dict]:
    """Normalize FMP's response into a flat list of daily price rows.

    Stable returns a bare list of ``{date, close, ...}`` rows. Legacy returns a single
    object ``{"symbol": ..., "historical": [ ... ]}`` which `client.get` wraps into a
    one-element list — so we detect and unwrap the ``historical`` key here.
    """
    if len(payload) == 1 and isinstance(payload[0], dict) and "historical" in payload[0]:
        nested = payload[0].get("historical") or []
        return [r for r in nested if isinstance(r, dict)]
    return [r for r in payload if isinstance(r, dict)]


def fetch_price_history(client: FMPClient, symbol: str, max_points: int = 756) -> list[float]:
    """Return up to ``max_points`` most-recent daily closes, oldest → newest.

    ``max_points`` defaults to ~3 years of trading days, enough for a stable volatility
    estimate while keeping the volatility "current". Raises an ``FMPError`` subclass on a
    provider/plan/rate-limit error, or ``FMPNotFound`` if no usable closes come back — the
    UI catches these and shows a clean "Price data unavailable" message.
    """
    last_error: FMPError | None = None
    for endpoint in _PRICE_ENDPOINTS:
        try:
            payload = client.get(endpoint, symbol)
        except FMPNotFound as exc:
            last_error = exc
            continue  # try the next endpoint name
        rows = _extract_rows(payload)
        # Pair each close with its date so we can sort chronologically regardless of the
        # order FMP returns (stable is oldest→newest; legacy is newest→oldest).
        dated = [
            (str(r.get("date") or ""), _num(r.get("close") or r.get("adjClose") or r.get("price")))
            for r in rows
        ]
        closes = [(d, c) for d, c in dated if c is not None and c > 0]
        if not closes:
            last_error = FMPNotFound(f"FMP returned no usable closing prices for '{symbol}'.")
            continue
        closes.sort(key=lambda dc: dc[0])  # ascending date → oldest first
        prices = [c for _, c in closes]
        return prices[-max_points:]

    raise last_error or FMPNotFound(f"No price history available for '{symbol}'.")
