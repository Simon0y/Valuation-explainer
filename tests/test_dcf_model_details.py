"""Headless render test for the DCF tab's "Model Details" view — runs the real app via
AppTest on SYNTHETIC data with every FMP/network path patched out (no live calls).

Proves: the year-by-year DCF build renders (Revenue → … → PV of FCFF), the bridge renders
(Σ PV FCFF, terminal value + its PV, EV, − net debt, equity, value/share), and the bottom-line
**value per share in the table ties EXACTLY to the DCF headline metric**. It is a read-only
surfacing of the engine's own intermediates, so nothing about the valuation should change.
"""

import math

import numpy as np
import pytest

import data.prices
import data.fundamentals
import data.news
import data.peers
from engine.models import CompanyFinancials, CompanyProfile, FinancialYear

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

# Rows the Model Details forecast table must surface, in build order.
_FORECAST_ROWS = (
    "Revenue", "EBIT", "NOPAT (EBIT after tax)", "+ D&A", "− Capex",
    "− Δ Net working capital", "= Unlevered FCFF", "Discount factor", "PV of FCFF",
)
# Rows the bridge must surface.
_BRIDGE_ROWS = (
    "Σ PV of forecast FCFF", "+ PV of terminal value", "= Enterprise value",
    "− Net debt", "= Equity value", "÷ Shares outstanding", "= Value per share",
)


def _synthetic_prices(n_days: int = 756) -> list[float]:
    rng = np.random.default_rng(2024)
    dt = 1.0 / 252
    steps = (0.08 - 0.5 * 0.28**2) * dt + 0.28 * math.sqrt(dt) * rng.standard_normal(n_days)
    return list(180.0 * np.exp(np.cumsum(np.concatenate([[0.0], steps]))))


def _synthetic_financials() -> CompanyFinancials:
    profile = CompanyProfile(
        symbol="AAPL", name="Synthetic Co", description="A test company.",
        sector="Technology", industry="Consumer Electronics", currency="USD",
        market_cap=2.5e12, price=185.0, beta=1.2, website=None, exchange="NASDAQ",
    )
    years = [
        FinancialYear(
            fiscal_year=str(y), period="FY", reported_currency="USD",
            revenue=4.0e11 - i * 1.5e10, ebit=1.2e11 - i * 5e9, ebitda=1.3e11 - i * 5e9,
            depreciation_amortization=1.1e10, capex=-1.0e10, change_in_working_capital=-2.0e9,
            income_before_tax=1.1e11 - i * 5e9, income_tax_expense=1.7e10,
            total_debt=1.0e11, cash_and_st_investments=6.0e10, net_debt=4.0e10,
            shares_outstanding=1.55e10, long_term_investments=1.0e11,
        )
        for i, y in enumerate((2024, 2023, 2022))
    ]
    return CompanyFinancials(profile=profile, years=years)


def _patch_everything(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "TEST")
    fin = _synthetic_financials()

    import streamlit as st
    st.cache_data.clear()  # don't let a prior test's cached company shadow this one

    import requests

    def _boom(*_a, **_k):
        raise AssertionError("live network call attempted during render test")

    monkeypatch.setattr(requests.Session, "get", _boom)
    monkeypatch.setattr(data.prices, "fetch_price_history", lambda *a, **k: _synthetic_prices())
    monkeypatch.setattr(data.fundamentals, "fetch_financials", lambda *a, **k: fin)
    monkeypatch.setattr(data.fundamentals, "fetch_profile", lambda *a, **k: fin.profile)
    monkeypatch.setattr(data.news, "fetch_recent_headlines", lambda *a, **k: [])
    from data.peers import PeerComparison
    monkeypatch.setattr(
        data.peers, "build_peer_comparison",
        lambda *a, **k: PeerComparison(points=[], source="none", pe_label="Trailing P/E (TTM)"),
    )


def _find_table(at, *required_index_labels):
    """Return the first rendered table whose row index contains all the given labels."""
    for tbl in at.table:
        idx = [str(x) for x in tbl.value.index]
        if all(lbl in idx for lbl in required_index_labels):
            return tbl.value
    raise AssertionError(f"no table found with index labels {required_index_labels}")


def test_model_details_renders_and_ties_to_headline(monkeypatch):
    _patch_everything(monkeypatch)

    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised on render: {[e.value for e in at.exception]}"

    # Forecast table: all build-order rows present, one column per forecast year.
    forecast = _find_table(at, "= Unlevered FCFF", "PV of FCFF")
    for row in _FORECAST_ROWS:
        assert row in [str(x) for x in forecast.index], f"missing forecast row: {row}"
    assert forecast.shape[1] >= 1 and all(str(c).startswith("Year ") for c in forecast.columns)

    # Bridge table: every step from cash flows to value per share present.
    bridge = _find_table(at, "= Value per share", "= Enterprise value")
    for row in _BRIDGE_ROWS:
        assert row in [str(x) for x in bridge.index], f"missing bridge row: {row}"

    # The Model Details value/share must tie EXACTLY to the DCF headline metric.
    table_vps = str(bridge.loc["= Value per share", "Value"]).strip()
    headline = next(
        m for m in at.metric if "DCF value / share" in (m.label or "")
    )
    assert table_vps == headline.value.strip(), (
        f"Model Details value/share {table_vps!r} != headline {headline.value!r}"
    )
