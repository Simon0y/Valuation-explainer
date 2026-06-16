"""Tests for the AI thesis module — fully offline (no SDK, no API key, no network).

`build_prompt` is pure and deterministic; `generate_ai_thesis` is exercised via an injected
fake model factory so we never touch Gemini or the SDK.
"""

import pytest

from ai_thesis import (
    AIError,
    AIKeyError,
    AIRateLimitError,
    ThesisContext,
    build_prompt,
    build_report_prompt,
    generate_ai_thesis,
    generate_report_thesis,
)


def _ctx() -> ThesisContext:
    return ThesisContext(
        company_name="Synthetic Co",
        symbol="SYN",
        currency="USD",
        sector="Technology",
        industry="Software",
        value_per_share=150.0,
        market_price=120.0,
        gap_vs_market=0.25,
        enterprise_value=2.0e12,
        equity_value=1.9e12,
        wacc=0.085,
        terminal_growth=0.025,
        revenue_growth=0.08,
        ebit_margin=0.30,
        multiples={"Trailing P/E": 28.4, "EV/EBITDA": 19.1},
        target_pe=28.4,
        median_peer_pe=22.0,
        peer_count=6,
        annualized_vol=0.32,
        var_pct=0.41,
        es_pct=0.52,
        headlines=["Synthetic Co beats earnings", "New product launched"],
        news_included=True,
    )


def test_prompt_asks_for_exactly_the_six_sections():
    p = build_prompt(_ctx())
    for heading in (
        "## Investment Thesis",
        "## Bull Case",
        "## Bear Case",
        "## Key Risks",
        "## Valuation Commentary",
        "## Catalysts",
    ):
        assert heading in p, heading
    # The old three-section name is gone (renamed to Key Risks).
    assert "## Risk Factors" not in p
    # No buy/sell recommendation, and the not-investment-advice disclaimer is requested.
    assert "no buy/sell recommendation" in p.lower()
    assert "not investment advice" in p.lower()
    # Accuracy guardrail: reason only from the data, don't invent figures.
    assert "do not invent" in p.lower()


def test_prompt_is_grounded_in_the_numbers():
    p = build_prompt(_ctx())
    assert "150.00" in p          # DCF value/share
    assert "120.00" in p          # market price
    assert "+25.0%" in p          # gap vs market
    assert "undervalued" in p     # direction of the gap
    assert "8.50%" in p           # WACC
    assert "28.4x" in p           # a multiple
    assert "22.0x" in p           # peer median P/E
    assert "41.0%" in p           # 1-year 95% VaR
    assert "52.0%" in p           # 1-year 95% Expected Shortfall
    assert "Synthetic Co beats earnings" in p  # a headline


def test_prompt_notes_when_news_absent():
    ctx = ThesisContext(company_name="X", symbol="X", news_included=False)
    p = build_prompt(ctx)
    assert "Recent news: not available" in p


def test_prompt_omits_missing_optional_fields():
    # With no DCF numbers, the DATA block must not invent value/gap lines.
    ctx = ThesisContext(company_name="X", symbol="X")
    p = build_prompt(ctx)
    assert "DCF intrinsic value per share:" not in p
    assert "DCF gap vs market:" not in p
    assert "WACC (discount rate):" not in p
    # The new risk/peer fact lines must also be omitted when their data is absent.
    assert "Value-at-Risk" not in p
    assert "Expected Shortfall" not in p
    assert "Peer median trailing P/E" not in p
    assert "Trailing P/E vs peers" not in p


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self, text):
        self._text = text

    def generate_content(self, _prompt):
        return _FakeResponse(self._text)


def test_report_prompt_has_four_concise_sections():
    p = build_report_prompt(_ctx())
    assert "## Investment Thesis" in p
    assert "## Bull Case" in p
    assert "## Bear Case" in p
    assert "## Key Risks" in p
    # Concise + grounded: word cap requested and the numbers are embedded.
    assert "180 words" in p
    assert "150.00" in p and "+25.0%" in p and "8.50%" in p
    assert "buy/sell recommendation" in p.lower()


def test_generate_report_thesis_uses_the_report_prompt():
    captured = {}

    class _CapModel:
        def generate_content(self, prompt):
            captured["prompt"] = prompt
            return _FakeResponse("## Investment Thesis\nView.\n## Bull Case\nUp.")

    out = generate_report_thesis(
        _ctx(), "FAKE_KEY", model_factory=lambda k, m: _CapModel()
    )
    assert "Investment Thesis" in out
    # It must have sent the four-section report prompt, not the three-section tab prompt.
    assert "## Key Risks" in captured["prompt"]
    assert "## Risk Factors" not in captured["prompt"]


def test_generate_with_mocked_factory_returns_text():
    canned = "## Bull Case\n- up\n## Bear Case\n- down\n## Risk Factors\n- risk"
    out = generate_ai_thesis(
        _ctx(), "FAKE_KEY", model_factory=lambda k, m: _FakeModel(canned)
    )
    assert out == canned


def test_generate_missing_key_raises_keyerror():
    with pytest.raises(AIKeyError):
        generate_ai_thesis(_ctx(), "", model_factory=lambda k, m: _FakeModel("x"))
    with pytest.raises(AIKeyError):
        generate_ai_thesis(_ctx(), None, model_factory=lambda k, m: _FakeModel("x"))


def test_generate_maps_rate_limit():
    def _boom(_k, _m):
        raise RuntimeError("429 ResourceExhausted: quota exceeded")

    with pytest.raises(AIRateLimitError):
        generate_ai_thesis(_ctx(), "FAKE_KEY", model_factory=_boom)


def test_generate_maps_other_errors_and_empty():
    def _boom(_k, _m):
        raise RuntimeError("some transport failure")

    with pytest.raises(AIError):
        generate_ai_thesis(_ctx(), "FAKE_KEY", model_factory=_boom)

    # Empty model output → AIError (not a silent empty string).
    with pytest.raises(AIError):
        generate_ai_thesis(_ctx(), "FAKE_KEY", model_factory=lambda k, m: _FakeModel("  "))
