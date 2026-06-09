"""Peer discovery and relative-valuation metrics via the FMP API.

Lives in the data layer (it talks to FMP) and performs NO finance math — it only fetches
and maps the few fields the Peers tab plots: trailing P/E, revenue growth (YoY) and market
cap, for the target company and its peers.

Endpoint strategy (all on FMP's modern ``/stable``; the legacy ``/api/v3`` was retired):

  * ``stock-peers``  — the company's peer set (symbol, name, market cap). Primary source.
  * ``company-screener`` — fallback when peers aren't on the plan: same sector/industry.
  * ``ratios-ttm`` — ``priceToEarningsRatioTTM`` (TRAILING P/E; the free tier exposes no
    reliable forward estimate, so we never fabricate one).
  * ``financial-growth`` — ``revenueGrowth`` for the latest fiscal year (YoY).

Every per-company fetch is best-effort: a 402/403/404 for one symbol yields ``None`` for
that field rather than failing the whole tab. Missing values are filtered out by the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from data.fmp_client import FMPClient, FMPError
from engine.models import CompanyProfile

EP_PEERS = "stock-peers"
EP_SCREENER = "company-screener"
EP_RATIOS_TTM = "ratios-ttm"
EP_GROWTH = "financial-growth"

# Trailing because the free tier has no forward-estimate endpoint we can trust.
PE_LABEL = "Trailing P/E (TTM)"


@dataclass(frozen=True)
class PeerPoint:
    """One company on the relative-valuation chart. Rates are decimals (0.06 == 6%)."""

    symbol: str
    name: str
    pe: Optional[float]              # trailing P/E (TTM)
    revenue_growth: Optional[float]  # latest fiscal-year YoY revenue growth, decimal
    market_cap: Optional[float]
    is_target: bool = False


@dataclass(frozen=True)
class PeerComparison:
    """Result of a peer pull: the points (target first) and provenance for honest labels."""

    points: list[PeerPoint]
    source: str            # "stock-peers", "screener", or "none"
    pe_label: str


def _num(value: Any) -> Optional[float]:
    """Coerce to float, returning None for missing/blank/non-numeric values."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: dict, *keys: str) -> Optional[Any]:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _trailing_pe(client: FMPClient, symbol: str) -> Optional[float]:
    try:
        rows = client.get(EP_RATIOS_TTM, symbol)
    except FMPError:
        return None
    return _num(_first(rows[0], "priceToEarningsRatioTTM", "peRatioTTM"))


def _revenue_growth_yoy(client: FMPClient, symbol: str) -> Optional[float]:
    try:
        rows = client.get(EP_GROWTH, symbol, limit=1)
    except FMPError:
        return None
    # financial-growth returns newest-first; the latest fiscal year is row[0].
    return _num(_first(rows[0], "revenueGrowth"))


def _discover_peers(
    client: FMPClient, symbol: str, profile: CompanyProfile, cap: int
) -> tuple[list[tuple[str, Optional[float], str]], str]:
    """Return ([(peer_symbol, market_cap, name), ...], source_label).

    Primary: the FMP ``stock-peers`` endpoint (which also hands us each peer's market cap
    and name). Fallback: the sector/industry screener. Both degrade to an empty list on a
    plan/network error so the tab can show a graceful note instead of crashing.
    """
    sym_u = symbol.upper()

    # 1) stock-peers — preferred (returns symbol, companyName, price, mktCap).
    try:
        rows = client.get(EP_PEERS, symbol)
        peers = [
            (
                str(_first(r, "symbol")).upper(),
                _num(_first(r, "mktCap", "marketCap")),
                str(_first(r, "companyName", "name") or _first(r, "symbol")),
            )
            for r in rows
            if _first(r, "symbol") and str(_first(r, "symbol")).upper() != sym_u
        ]
        if peers:
            return peers[:cap], "stock-peers"
    except FMPError:
        pass

    # 2) Screener fallback — same sector/industry (often premium; tolerated if it fails).
    try:
        rows = client.get(
            EP_SCREENER, "",
            sector=profile.sector, industry=profile.industry,
            limit=cap + 5, isActivelyTrading="true",
        )
        peers = [
            (
                str(_first(r, "symbol")).upper(),
                _num(_first(r, "marketCap", "mktCap")),
                str(_first(r, "companyName", "name") or _first(r, "symbol")),
            )
            for r in rows
            if _first(r, "symbol") and str(_first(r, "symbol")).upper() != sym_u
        ]
        if peers:
            return peers[:cap], "screener"
    except FMPError:
        pass

    return [], "none"


def build_peer_comparison(
    client: FMPClient, symbol: str, profile: CompanyProfile, max_peers: int = 12
) -> PeerComparison:
    """Assemble the target + up to ``max_peers`` peers with P/E, revenue growth, market cap.

    The target's market cap comes from its profile; peers' caps come from the discovery
    payload (with no fabrication if absent). P/E and revenue growth are fetched per symbol.
    """
    target = PeerPoint(
        symbol=symbol.upper(),
        name=profile.name,
        pe=_trailing_pe(client, symbol),
        revenue_growth=_revenue_growth_yoy(client, symbol),
        market_cap=profile.market_cap,
        is_target=True,
    )

    peer_syms, source = _discover_peers(client, symbol, profile, max_peers)

    points: list[PeerPoint] = [target]
    for psym, mcap, pname in peer_syms:
        points.append(
            PeerPoint(
                symbol=psym,
                name=pname,
                pe=_trailing_pe(client, psym),
                revenue_growth=_revenue_growth_yoy(client, psym),
                market_cap=mcap,
                is_target=False,
            )
        )

    return PeerComparison(points=points, source=source, pe_label=PE_LABEL)
