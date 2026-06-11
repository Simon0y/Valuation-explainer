"""Fetch recent news headlines for a ticker from FMP — strictly OPTIONAL and fail-soft.

The AI Insights tab grounds its thesis in the valuation numbers; news is a nice-to-have
that adds colour when available. So every error here (plan/rate-limit/missing/shape) is
swallowed and yields an empty list — the caller then generates the thesis from the numbers
alone and notes that news wasn't included. This module does NO finance math.

FMP has shuffled its news endpoints across plan tiers, so we try a few names and read the
headline from whichever field is present (``title``/``text``). `client.get` already handles
the stable-vs-legacy URL shapes per name.
"""

from __future__ import annotations

from typing import Any

from data.fmp_client import FMPClient, FMPError

# Candidate news endpoints, newest first. We also pass `symbols=` (stable's param name) in
# addition to the `symbol=` the client always sends, so either shape can match.
_NEWS_ENDPOINTS = ("news/stock", "stock_news")


def _headline(row: dict) -> str | None:
    for key in ("title", "headline", "text"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def fetch_recent_headlines(client: FMPClient, symbol: str, limit: int = 5) -> list[str]:
    """Return up to ``limit`` recent headlines, or ``[]`` on ANY error (never raises)."""
    for endpoint in _NEWS_ENDPOINTS:
        try:
            rows: Any = client.get(endpoint, symbol, symbols=symbol, limit=limit)
        except FMPError:
            continue
        except Exception:  # noqa: BLE001 — news is optional; never let it crash the tab
            continue
        if not isinstance(rows, list):
            continue
        headlines: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                h = _headline(row)
                if h:
                    headlines.append(h)
            if len(headlines) >= limit:
                break
        if headlines:
            return headlines
    return []
