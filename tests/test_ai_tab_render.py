"""Headless render test for the AI Insights tab — runs the real app via AppTest on
SYNTHETIC data with a MOCKED Gemini response (no real key/SDK) and every FMP/network path
patched out. Proves: the tab renders, a click produces the Bull/Bear/Risk report, there are
zero exceptions, and no live FMP/Gemini calls are made.
"""

import math

import numpy as np
import pytest

import data.prices
import data.fundamentals
import data.peers
import data.news
import ai_thesis
from engine.models import CompanyFinancials, CompanyProfile, FinancialYear

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

_MOCK_THESIS = (
    "## Bull Case\n"
    "- The DCF implies the stock is +25% undervalued versus the market.\n"
    "- EV/EBITDA of 19x is reasonable for the growth profile.\n\n"
    "## Bear Case\n"
    "- A trailing P/E of 28x leaves little margin for error.\n"
    "- The DCF leans on an 8.5% WACC and 2.5% terminal growth.\n\n"
    "## Risk Factors\n"
    "- Multiple compression if rates rise.\n"
    "- Execution risk on revenue growth assumptions.\n"
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
    monkeypatch.setenv("GEMINI_API_KEY", "TEST")

    import requests

    def _boom(*_a, **_k):
        raise AssertionError("live network call attempted during render test")

    monkeypatch.setattr(requests.Session, "get", _boom)

    monkeypatch.setattr(data.prices, "fetch_price_history", lambda *a, **k: _synthetic_prices())
    monkeypatch.setattr(data.fundamentals, "fetch_financials", lambda *a, **k: _synthetic_financials())
    monkeypatch.setattr(data.fundamentals, "fetch_profile", lambda *a, **k: _synthetic_financials().profile)
    monkeypatch.setattr(data.news, "fetch_recent_headlines", lambda *a, **k: ["Synthetic Co beats earnings"])

    from data.peers import PeerComparison
    monkeypatch.setattr(
        data.peers, "build_peer_comparison",
        lambda *a, **k: PeerComparison(points=[], source="none", pe_label="Trailing P/E (TTM)"),
    )
    # Mock Gemini entirely — no SDK, no key, no network.
    monkeypatch.setattr(ai_thesis, "generate_ai_thesis", lambda ctx, key, **kw: _MOCK_THESIS)


def _gen_button(at):
    for b in at.button:
        if b.key == "gen_ai_thesis":
            return b
    raise AssertionError("generate-thesis button not found")


def test_ai_tab_renders_and_generates_on_click(monkeypatch):
    _patch_everything(monkeypatch)

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, f"app raised on initial render: {[e.value for e in at.exception]}"

    # Before any click, the tab invites the user to generate — and the generate button exists.
    btn = _gen_button(at)

    btn.click()
    at.run()
    assert not at.exception, f"app raised after generate: {[e.value for e in at.exception]}"

    md = "\n".join(m.value for m in at.markdown)
    assert "Bull Case" in md
    assert "Bear Case" in md
    assert "Risk Factors" in md

    captions = "\n".join(c.value for c in at.caption)
    assert "not investment advice" in captions.lower()


def test_ai_tab_without_key_shows_enable_message(monkeypatch):
    _patch_everything(monkeypatch)
    # Remove the Gemini key so the tab should show the "add a key" message, not a button.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception

    info = "\n".join(i.value for i in at.info)
    assert "Gemini API key" in info
