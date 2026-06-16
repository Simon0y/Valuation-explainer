"""Headless render test for the AI Insights tab — runs the real app via AppTest on
SYNTHETIC data with a MOCKED Gemini response (no real key/SDK) and every FMP/network path
patched out. Proves: the tab renders the six-section research note across DIFFERENT tickers
(not just AAPL), a click produces all six sections, the mock receives a context grounded in
THAT company's numbers, there are zero exceptions, and no live FMP/Gemini calls are made.
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

_SIX_SECTIONS = (
    "Investment Thesis", "Bull Case", "Bear Case",
    "Key Risks", "Valuation Commentary", "Catalysts",
)

_MOCK_THESIS = (
    "## Investment Thesis\nThe DCF gap vs market frames the view.\n\n"
    "## Bull Case\nUpside if the growth/margin assumptions hold.\n\n"
    "## Bear Case\nRich multiples vs peers leave little room.\n\n"
    "## Key Risks\nThe 1-year 95% VaR quantifies the downside.\n\n"
    "## Valuation Commentary\nDCF value vs price given the WACC.\n\n"
    "## Catalysts\nDevelopments that could close the gap.\n"
)


def _synthetic_prices(n_days: int = 756) -> list[float]:
    rng = np.random.default_rng(2024)
    dt = 1.0 / 252
    steps = (0.08 - 0.5 * 0.28**2) * dt + 0.28 * math.sqrt(dt) * rng.standard_normal(n_days)
    return list(180.0 * np.exp(np.cumsum(np.concatenate([[0.0], steps]))))


def _synthetic_financials(
    symbol: str = "AAPL",
    name: str = "Synthetic Co",
    sector: str = "Technology",
    industry: str = "Consumer Electronics",
) -> CompanyFinancials:
    profile = CompanyProfile(
        symbol=symbol, name=name, description="A test company.",
        sector=sector, industry=industry, currency="USD",
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


def _patch_everything(monkeypatch, fin: CompanyFinancials | None = None, capture: dict | None = None):
    fin = fin or _synthetic_financials()
    monkeypatch.setenv("FMP_API_KEY", "TEST")
    monkeypatch.setenv("GEMINI_API_KEY", "TEST")

    # @st.cache_data persists across AppTest runs in this process; clear it so a prior test's
    # cached financials for the same ticker don't shadow this test's synthetic company.
    import streamlit as st
    st.cache_data.clear()

    import requests

    def _boom(*_a, **_k):
        raise AssertionError("live network call attempted during render test")

    monkeypatch.setattr(requests.Session, "get", _boom)

    monkeypatch.setattr(data.prices, "fetch_price_history", lambda *a, **k: _synthetic_prices())
    monkeypatch.setattr(data.fundamentals, "fetch_financials", lambda *a, **k: fin)
    monkeypatch.setattr(data.fundamentals, "fetch_profile", lambda *a, **k: fin.profile)
    monkeypatch.setattr(data.news, "fetch_recent_headlines", lambda *a, **k: [f"{fin.profile.name} beats earnings"])

    from data.peers import PeerComparison
    monkeypatch.setattr(
        data.peers, "build_peer_comparison",
        lambda *a, **k: PeerComparison(points=[], source="none", pe_label="Trailing P/E (TTM)"),
    )

    # Mock Gemini entirely — but capture the grounded context the app handed us so the test
    # can assert it is specific to THIS company (no SDK, no key, no network).
    def _fake_generate(ctx, key, **kw):
        if capture is not None:
            capture["ctx"] = ctx
        return _MOCK_THESIS

    monkeypatch.setattr(ai_thesis, "generate_ai_thesis", _fake_generate)


def _gen_button(at):
    for b in at.button:
        if b.key == "gen_ai_thesis":
            return b
    raise AssertionError("generate-thesis button not found")


def _set_ticker(at, symbol):
    """Type a ticker into the sidebar input (drives the symbol the app loads and the
    @st.cache_data key, so each parametrized ticker is a distinct, fresh load)."""
    for t in at.text_input:
        if t.label == "Ticker":
            t.set_value(symbol)
            return
    raise AssertionError("ticker input not found")


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
    for section in _SIX_SECTIONS:
        assert section in md, section
    assert "Risk Factors" not in md  # old heading is gone

    captions = "\n".join(c.value for c in at.caption)
    assert "not investment advice" in captions.lower()


@pytest.mark.parametrize(
    "symbol,name,sector,industry",
    [
        ("AAPL", "Apple Inc.", "Technology", "Consumer Electronics"),
        ("META", "Meta Platforms, Inc.", "Communication Services", "Internet Content & Information"),
        ("SAP", "SAP SE", "Technology", "Software - Application"),
    ],
)
def test_ai_tab_renders_for_multiple_tickers(monkeypatch, symbol, name, sector, industry):
    """The six-section note renders end-to-end for several different companies, and the
    context handed to the model is grounded in THAT company (not AAPL-flavored)."""
    capture: dict = {}
    fin = _synthetic_financials(symbol=symbol, name=name, sector=sector, industry=industry)
    _patch_everything(monkeypatch, fin=fin, capture=capture)

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, f"{symbol}: app raised on render: {[e.value for e in at.exception]}"

    _set_ticker(at, symbol)
    at.run()
    assert not at.exception, f"{symbol}: app raised after ticker set: {[e.value for e in at.exception]}"

    _gen_button(at).click()
    at.run()
    assert not at.exception, f"{symbol}: app raised after generate: {[e.value for e in at.exception]}"

    # All six sections rendered.
    md = "\n".join(m.value for m in at.markdown)
    for section in _SIX_SECTIONS:
        assert section in md, f"{symbol}: missing {section}"

    # The model received a context specific to this company.
    ctx = capture["ctx"]
    assert ctx.symbol == symbol and ctx.company_name == name and ctx.sector == sector


def test_ai_tab_without_key_shows_enable_message(monkeypatch):
    _patch_everything(monkeypatch)
    # Remove the Gemini key so the tab should show the "add a key" message, not a button.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception

    info = "\n".join(i.value for i in at.info)
    assert "Gemini API key" in info
