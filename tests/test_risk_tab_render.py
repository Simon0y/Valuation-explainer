"""Headless render test for the Risk tab — runs the real Streamlit app via AppTest on
SYNTHETIC data with every FMP/network path patched out, asserting it renders with zero
exceptions and produces the VaR/ES metric cards.

This proves the requirement: "Risk tab renders on synthetic data with 0 exceptions; no
live FMP calls made." `requests.Session.get` is patched to hard-fail, so any accidental
live call would raise and fail the test rather than hit the (exhausted) FMP quota.
"""

import math

import numpy as np
import pytest

# Patch targets live in the data layer; app.py does `from data.X import Y`, so patching the
# source attributes before AppTest execs app.py rebinds the names inside the app.
import data.prices
import data.fundamentals
import data.peers
from engine.models import CompanyFinancials, CompanyProfile, FinancialYear

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


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


def test_risk_tab_renders_on_synthetic_data_no_network(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "TEST")

    # Hard-fail any real HTTP call so a stray live request can't slip through.
    import requests

    def _boom(*_a, **_k):
        raise AssertionError("live network call attempted during synthetic render test")

    monkeypatch.setattr(requests.Session, "get", _boom)

    # Synthetic data for every FMP-backed path the app touches.
    monkeypatch.setattr(data.prices, "fetch_price_history", lambda *a, **k: _synthetic_prices())
    monkeypatch.setattr(data.fundamentals, "fetch_financials", lambda *a, **k: _synthetic_financials())
    monkeypatch.setattr(data.fundamentals, "fetch_profile", lambda *a, **k: _synthetic_financials().profile)

    from data.peers import PeerComparison
    monkeypatch.setattr(
        data.peers, "build_peer_comparison",
        lambda *a, **k: PeerComparison(points=[], source="none", pe_label="Trailing P/E (TTM)"),
    )

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()

    assert not at.exception, f"app raised: {[e.value for e in at.exception]}"

    labels = [m.label for m in at.metric]
    assert any("VaR" in lbl for lbl in labels), f"no VaR metric rendered; got {labels}"
    assert any("Expected Shortfall" in lbl for lbl in labels), f"no ES metric; got {labels}"
