"""Regression tests for the peer-drop diagnosis.

These pin the behaviour discovered live: on the FMP free tier, peers are dropped because the
per-symbol fundamentals endpoints (ratios-ttm / financial-growth) are 402-restricted to a
whitelist of popular symbols — NOT because the companies are unprofitable, and NOT (usually)
because of a rate limit. The count note must name that real reason.
"""
from __future__ import annotations

import app
from data.fmp_client import FMPPlanError, FMPRateLimitError
from data.peers import (
    STATUS_OK,
    STATUS_PLAN,
    STATUS_RATE_LIMIT,
    build_peer_comparison,
    fetch_peer_metrics,
)
from engine.models import CompanyProfile


class FakeClient:
    """Minimal FMP stand-in. `whitelist` symbols return data; others raise `error_for`."""

    def __init__(self, peers, whitelist, error_for=FMPPlanError):
        self._peers = peers
        self._whitelist = set(whitelist)
        self._error_for = error_for

    def get(self, endpoint, symbol, try_legacy=True, **extra):
        symbol = symbol.upper()
        if endpoint == "stock-peers":
            return [dict(symbol=s, companyName=s, mktCap=cap) for s, cap in self._peers]
        if symbol not in self._whitelist:
            raise self._error_for("off-plan symbol")
        if endpoint == "ratios-ttm":
            return [{"priceToEarningsRatioTTM": 25.0}]
        if endpoint == "financial-growth":
            return [{"revenueGrowth": 0.12}]
        raise AssertionError(f"unexpected endpoint {endpoint}")


def _profile(sym):
    return CompanyProfile(
        symbol=sym, name=sym, description="", sector="Tech", industry="Tech",
        currency="USD", market_cap=1.0e12, price=100.0, beta=1.0,
    )


# --- fetch_peer_metrics status mapping ------------------------------------------------

def test_metrics_status_ok():
    c = FakeClient(peers=[], whitelist={"GOOGL"})
    m = fetch_peer_metrics(c, "GOOGL")
    assert m.pe == 25.0 and m.revenue_growth == 0.12
    assert m.pe_status == STATUS_OK and m.growth_status == STATUS_OK


def test_metrics_status_plan_restricted():
    c = FakeClient(peers=[], whitelist={"GOOGL"}, error_for=FMPPlanError)
    m = fetch_peer_metrics(c, "ORCL")  # off whitelist → 402
    assert m.pe is None and m.revenue_growth is None
    assert m.pe_status == STATUS_PLAN and m.growth_status == STATUS_PLAN


def test_metrics_status_rate_limited():
    c = FakeClient(peers=[], whitelist={"GOOGL"}, error_for=FMPRateLimitError)
    m = fetch_peer_metrics(c, "ORCL")
    assert m.pe_status == STATUS_RATE_LIMIT and m.growth_status == STATUS_RATE_LIMIT


# --- drop-reason priority -------------------------------------------------------------

def test_drop_reason_plan_beats_missing():
    from data.peers import PeerPoint
    p = PeerPoint("ORCL", "ORCL", pe=None, revenue_growth=None, market_cap=5e11,
                  pe_status=STATUS_PLAN, growth_status=STATUS_PLAN)
    assert app._peer_drop_reason(p) == app._DROP_NOT_ON_PLAN


def test_drop_reason_rate_limit_beats_plan():
    from data.peers import PeerPoint
    p = PeerPoint("MU", "MU", pe=None, revenue_growth=None, market_cap=5e11,
                  pe_status=STATUS_RATE_LIMIT, growth_status=STATUS_PLAN)
    assert app._peer_drop_reason(p) == app._DROP_RATE_LIMITED


def test_drop_reason_negative_pe_is_missing_pe():
    from data.peers import PeerPoint
    p = PeerPoint("SONY", "SONY", pe=-62.0, revenue_growth=0.02, market_cap=1e11)
    assert app._peer_drop_reason(p) == app._DROP_NO_PE


# --- end-to-end count note matches reality (META scenario captured live) --------------

def test_meta_scenario_count_note():
    # META's real stock-peers, with only GOOGL + CSCO on the free-tier whitelist.
    peers = [("AMAT", 4.2e11), ("AVGO", 1.8e12), ("CSCO", 4.7e11), ("GOOGL", 4.2e12),
             ("GRMN", 4.5e10), ("IBM", 2.6e11), ("MU", 1.0e12), ("ORCL", 5.1e11)]
    c = FakeClient(peers=peers, whitelist={"META", "GOOGL", "CSCO"})
    comp = build_peer_comparison(c, "META", _profile("META"), max_peers=8)

    all_peers = [p for p in comp.points if not p.is_target]
    dropped = [(p.symbol, app._peer_drop_reason(p)) for p in all_peers]
    dropped = [(s, r) for s, r in dropped if r is not None]
    plotted = [p for p in all_peers if app._peer_drop_reason(p) is None]

    assert len(all_peers) == 8
    assert {p.symbol for p in plotted} == {"GOOGL", "CSCO"}
    assert len(dropped) == 6
    assert all(r == app._DROP_NOT_ON_PLAN for _, r in dropped)
    summary = app._summarize_drops([r for _, r in dropped])
    assert summary == "not on free plan ×6"
