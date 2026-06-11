"""Tests for the investment-report assembly (content/report.py).

Fully offline and pure — no Streamlit, no FMP, no Gemini. Builds a report from a MOCKED
session (plain values) and checks the Markdown has the key sections and the PDF bytes are
produced without error, including the best-effort matplotlib chart.
"""

from content.report import DISCLAIMER, ReportData, build_markdown, build_pdf


def _full_risk_bands(n: int = 253) -> dict:
    times = [i / 252.0 for i in range(n)]
    # Monotone, correctly-ordered synthetic bands fanning out from 100.
    bands = {
        "p5": [100.0 - i * 0.10 for i in range(n)],
        "p25": [100.0 - i * 0.04 for i in range(n)],
        "p50": [100.0 + i * 0.02 for i in range(n)],
        "p75": [100.0 + i * 0.06 for i in range(n)],
        "p95": [100.0 + i * 0.12 for i in range(n)],
    }
    return {"times": times, "bands": bands}


def _full_report() -> ReportData:
    rb = _full_risk_bands()
    return ReportData(
        company_name="Synthetic Co",
        symbol="SYN",
        report_date="2026-06-10",
        currency="USD",
        current_price=120.0,
        valuation={
            "value_per_share": 150.0,
            "upside": 0.25,
            "enterprise_value": 2.0e12,
            "equity_value": 1.9e12,
            "wacc": 0.085,
            "terminal_growth": 0.025,
        },
        multiples={"Trailing P/E": 28.4, "EV/EBITDA": 19.1, "EV/Sales": 7.2},
        peers={"source": "stock-peers", "peer_count": 6, "target_pe": 28.4, "median_peer_pe": 22.0},
        risk={
            "var_pct": 0.38, "es_pct": 0.44, "var_price": 74.0, "es_price": 67.0,
            "current_price": 120.0, "sigma": 0.28, "n_paths": 10000, "horizon_days": 252,
            **rb,
        },
        ai_thesis=(
            "## Bull Case\n- DCF implies +25% upside.\n"
            "## Bear Case\n- 28x P/E is rich.\n"
            "## Risk Factors\n- Multiple compression."
        ),
        ai_news_included=True,
    )


def test_markdown_has_all_key_sections():
    md = build_markdown(_full_report())
    assert "# Investment Report — Synthetic Co (SYN)" in md
    assert "2026-06-10" in md
    assert "## Valuation (DCF)" in md
    assert "150.00 USD" in md            # fair value
    assert "+25.0%" in md                 # upside
    assert "undervalued" in md
    assert "## Key Multiples" in md
    assert "28.4x" in md
    assert "## Peer Comparison" in md
    assert "6" in md                      # peer count
    assert "## Risk" in md
    assert "Value at Risk" in md
    assert "Expected Shortfall" in md
    assert "## AI Investment Thesis" in md
    assert "Bull Case" in md and "Bear Case" in md and "Risk Factors" in md
    assert DISCLAIMER in md
    assert "not investment advice" in md.lower()


def test_markdown_skips_missing_sections_gracefully():
    # Only a header + valuation present; everything else must be omitted, not error.
    data = ReportData(
        company_name="Bare Co", symbol="BARE", report_date="2026-06-10",
        valuation={"value_per_share": 10.0},
    )
    md = build_markdown(data)
    assert "Bare Co" in md
    assert "## Valuation (DCF)" in md
    assert "## Key Multiples" not in md
    assert "## Peer Comparison" not in md
    assert "## Risk" not in md
    assert "## AI Investment Thesis" not in md
    assert DISCLAIMER in md  # footer always present


def test_pdf_bytes_produced_with_chart():
    pdf = build_pdf(_full_report())
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 1000
    assert bytes(pdf[:5]) == b"%PDF-"


def test_pdf_bytes_produced_without_risk_chart():
    # No risk bands → chart skipped, but PDF must still build cleanly.
    data = _full_report()
    data.risk = {"var_pct": 0.30, "es_pct": 0.36}  # no times/bands
    pdf = build_pdf(data)
    assert bytes(pdf[:5]) == b"%PDF-"
    assert len(pdf) > 500


def test_pdf_minimal_report():
    data = ReportData(company_name="X", symbol="X")
    pdf = build_pdf(data)
    assert bytes(pdf[:5]) == b"%PDF-"


def test_markdown_handles_overvalued_direction():
    data = ReportData(
        company_name="Y", symbol="Y",
        valuation={"value_per_share": 8.0, "upside": -0.2},
    )
    md = build_markdown(data)
    assert "-20.0%" in md
    assert "overvalued" in md
