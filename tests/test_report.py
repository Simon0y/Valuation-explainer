"""Tests for the investment-report assembly (content/report.py).

Fully offline and pure — no Streamlit, no FMP, no Gemini. Builds a report from a MOCKED
session (plain values) and checks the Markdown has the key sections and the PDF bytes are
produced without error, including the best-effort matplotlib chart.
"""

import re

from content.report import DISCLAIMER, ReportData, build_markdown, build_pdf


def _page_count(pdf: bytes) -> int:
    # fpdf2 writes one "/Type /Page" per page plus one "/Type /Pages" tree root.
    return len(re.findall(rb"/Type\s*/Page(?![s])", bytes(pdf)))


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
    assert "# Investment Report: Synthetic Co (SYN)" in md
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


def test_pdf_is_exactly_one_page():
    # A full report with a four-section thesis must stay on a single page.
    data = _full_report()
    data.ai_thesis = (
        "## Investment Thesis\nThe DCF implies +25% upside; multiples look full.\n"
        "## Bull Case\nMargins sustain growth and the gap closes.\n"
        "## Bear Case\nA rich 28x P/E leaves little room for error.\n"
        "## Key Risks\nDemand cyclicality, competition, and FX."
    )
    assert _page_count(build_pdf(data)) == 1


def test_pdf_long_thesis_still_one_page():
    # An over-long thesis is budgeted against the footer, so the PDF never spills to page 2.
    data = _full_report()
    data.ai_thesis = "\n\n".join(
        f"## {h}\n" + ("A long sentence that pads the section considerably. " * 14)
        for h in ("Investment Thesis", "Bull Case", "Bear Case", "Key Risks")
    )
    assert _page_count(build_pdf(data)) == 1


def test_pdf_failsoft_note_when_no_thesis_one_page():
    # No thesis but a note (e.g. no Gemini key) → numeric sections + note, still one page.
    data = _full_report()
    data.ai_thesis = None
    data.ai_note = "AI thesis unavailable - no Gemini API key configured; numeric analysis only."
    pdf = build_pdf(data)
    assert _page_count(pdf) == 1


def test_markdown_shows_note_when_thesis_unavailable():
    data = ReportData(
        company_name="Z", symbol="Z",
        ai_note="AI thesis unavailable - generation failed; numeric analysis only.",
    )
    md = build_markdown(data)
    assert "## AI Investment Thesis" in md
    assert "AI thesis unavailable" in md


def test_trailing_pe_single_source_no_conflict():
    # Key Multiples carries a stale 38.2x under the labeled TTM key; the peer pull carries the
    # FMP TTM P/E (35.0x). The report reconciles by prefix to ONE value — the peer/TTM source —
    # so the same company never shows two different trailing P/Es.
    data = ReportData(
        company_name="Conflict Co", symbol="CFL",
        multiples={"Trailing P/E (TTM)": 38.2, "EV/EBITDA": 19.1},
        peers={"source": "stock-peers", "peer_count": 5,
               "target_pe": 35.0, "median_peer_pe": 28.0},
    )
    # Reconciled in-memory: both sections reference the same number (matched by prefix, so the
    # basis label is preserved).
    assert data.multiples["Trailing P/E (TTM)"] == 35.0

    md = build_markdown(data)
    # Exactly one trailing-P/E value appears for the company in the rendered report.
    assert "38.2x" not in md
    assert md.count("35.0x") == 2  # once in Key Multiples, once in Peer Comparison


def test_trailing_pe_fallback_when_no_peers():
    # No peer P/E available → Key Multiples keeps its supplied figure and basis label, and
    # there is no peer section to contradict it.
    data = ReportData(
        company_name="Solo Co", symbol="SOLO",
        multiples={"Trailing P/E (annual)": 30.0},
    )
    assert data.multiples["Trailing P/E (annual)"] == 30.0
    md = build_markdown(data)
    assert "30.0x" in md
    assert "Trailing P/E (annual)" in md  # basis is never ambiguous
    assert "## Peer Comparison" not in md


def test_markdown_handles_overvalued_direction():
    data = ReportData(
        company_name="Y", symbol="Y",
        valuation={"value_per_share": 8.0, "upside": -0.2},
    )
    md = build_markdown(data)
    assert "-20.0%" in md
    assert "overvalued" in md
