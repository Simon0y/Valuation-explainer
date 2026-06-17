"""Investment-report assembly — packages ALREADY-COMPUTED session results into a
downloadable Markdown or PDF report.

This module is pure: it imports NO Streamlit and makes NO network calls. It only formats a
:class:`ReportData` (plain values the caller has already collected from session state) into
two byte streams. That keeps it unit-testable in isolation and guarantees building a report
can never trigger a new FMP/Gemini call.

Two formats:
  * Markdown — bulletproof primary. Pure string assembly; always works.
  * PDF — a clean, SINGLE-PAGE analyst report via fpdf2: a compact header, a numeric
    valuation/multiples/peer/risk summary, and the AI investment thesis (Investment Thesis /
    Bull / Bear / Key Risks) as the written analysis, with the disclaimer pinned to the
    bottom. Auto page-break is disabled and the written analysis is budgeted against the
    remaining vertical space, so the report always fits on exactly one page.

Every section is OPTIONAL: a ``None``/empty field is skipped gracefully, so a partially
explored session still exports a clean report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DISCLAIMER = (
    "This report is for EDUCATIONAL purposes only and is NOT investment advice. It is "
    "generated from a simplified valuation model; portions (the investment thesis) are "
    "AI-assisted and may be inaccurate or out of date. Do your own research and consult a "
    "licensed financial professional before making any investment decision."
)


@dataclass
class ReportData:
    """Plain, already-computed values for one company's report. All optional except name.

    Rates are decimals (0.08 == 8%). Monetary values are in ``currency``. The caller
    collects these from session state; this module never computes valuation figures."""

    company_name: str
    symbol: str = ""
    report_date: str = ""
    currency: str = ""
    current_price: Optional[float] = None

    # value_per_share, upside (decimal), enterprise_value, equity_value, wacc,
    # terminal_growth, net_debt, shares_outstanding
    valuation: Optional[dict] = None

    # label -> multiple value, e.g. {"Trailing P/E (TTM)": 28.4, "EV/EBITDA": 19.1}
    multiples: dict = field(default_factory=dict)

    # source, peer_count, target_pe, median_peer_pe, target_growth
    peers: Optional[dict] = None

    # var_pct, es_pct, var_price, es_price, current_price, sigma, n_paths, horizon_days,
    # and (optional) times + bands {p5,p25,p50,p75,p95}
    risk: Optional[dict] = None

    ai_thesis: Optional[str] = None
    ai_news_included: bool = False
    # Short note shown in place of the analysis when a thesis was ATTEMPTED but is
    # unavailable (e.g. no Gemini key / rate limited). When both this and ``ai_thesis`` are
    # None, the AI section is omitted entirely (a thesis was never requested).
    ai_note: Optional[str] = None

    def __post_init__(self) -> None:
        # Single source of truth for the company's trailing P/E. The Peer Comparison shows
        # the target's P/E beside the peer median — both FMP TTM (priceToEarningsRatioTTM) —
        # so the comparison is apples-to-apples. When that value exists, force the Key
        # Multiples "Trailing P/E" to the exact same number so the company never displays two
        # different P/E values across sections. (Absent a peer P/E, Key Multiples keeps its
        # fundamentals-derived fallback, and there is no peer section to disagree with.)
        # The Key Multiples key carries its basis label ("Trailing P/E (TTM)" / "(annual)"),
        # so match it by prefix rather than an exact "Trailing P/E".
        target_pe = (self.peers or {}).get("target_pe")
        if target_pe is not None and self.multiples:
            pe_key = next(
                (k for k in self.multiples if str(k).startswith("Trailing P/E")), None
            )
            if pe_key is not None:
                self.multiples[pe_key] = target_pe


# --------------------------------------------------------------------------------------
# Formatting helpers (display only)
# --------------------------------------------------------------------------------------
def _compact(value) -> str:
    if value is None:
        return "—"
    a = abs(value)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{value / div:,.1f}{suffix}"
    return f"{value:,.0f}"


def _cur(value, currency: str, dp: int = 2) -> str:
    if value is None:
        return "—"
    suffix = f" {currency}" if currency and currency != "—" else ""
    return f"{value:,.{dp}f}{suffix}"


def _pct(value, dp: int = 1, sign: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:{'+' if sign else ''}.{dp}%}"


# --------------------------------------------------------------------------------------
# Markdown (primary, bulletproof)
# --------------------------------------------------------------------------------------
def build_markdown(data: ReportData) -> str:
    cur = data.currency or ""
    out: list[str] = []

    # ---- Header ----
    out.append(f"# Investment Report: {data.company_name} ({data.symbol})")
    meta = []
    if data.report_date:
        meta.append(f"**Date:** {data.report_date}")
    if data.current_price is not None:
        meta.append(f"**Current price:** {_cur(data.current_price, cur)}")
    if cur and cur != "—":
        meta.append(f"**Currency:** {cur}")
    if meta:
        out.append("  \n".join(meta))

    # ---- Valuation ----
    v = data.valuation
    if v:
        out.append("\n## Valuation (DCF)")
        rows = []
        if v.get("value_per_share") is not None:
            rows.append(f"- **DCF fair value / share:** {_cur(v['value_per_share'], cur)}")
        if v.get("upside") is not None:
            verdict = "undervalued" if v["upside"] > 0 else "overvalued"
            rows.append(
                f"- **Upside / downside vs market:** {_pct(v['upside'], sign=True)} "
                f"(DCF implies the stock is **{verdict}**)"
            )
        if v.get("enterprise_value") is not None:
            rows.append(f"- **Enterprise value:** {_compact(v['enterprise_value'])} {cur}".rstrip())
        if v.get("equity_value") is not None:
            rows.append(f"- **Equity value:** {_compact(v['equity_value'])} {cur}".rstrip())
        if v.get("wacc") is not None:
            rows.append(f"- **WACC (discount rate):** {_pct(v['wacc'], dp=2)}")
        if v.get("terminal_growth") is not None:
            rows.append(f"- **Terminal growth:** {_pct(v['terminal_growth'], dp=2)}")
        out.append("\n".join(rows))

    # ---- Multiples ----
    if data.multiples:
        out.append("\n## Key Multiples")
        out.append("\n".join(f"- **{label}:** {value:,.1f}x" for label, value in data.multiples.items()))

    # ---- Peers ----
    p = data.peers
    if p and p.get("peer_count"):
        out.append("\n## Peer Comparison")
        src = {"stock-peers": "FMP stock-peers", "screener": "sector/industry screener"}.get(
            p.get("source", ""), p.get("source", "peer set")
        )
        line = f"- Compared against **{p['peer_count']}** peers (via {src})."
        out.append(line)
        if p.get("target_pe") is not None and p.get("median_peer_pe") is not None:
            rel = "above" if p["target_pe"] > p["median_peer_pe"] else "below"
            out.append(
                f"- Trailing P/E **{p['target_pe']:,.1f}x** vs peer median "
                f"**{p['median_peer_pe']:,.1f}x**, trading **{rel}** the peer median."
            )
        elif p.get("target_pe") is not None:
            out.append(f"- Trailing P/E **{p['target_pe']:,.1f}x**.")

    # ---- Risk ----
    r = data.risk
    if r:
        out.append("\n## Risk: Monte Carlo (GBM), 1-year, 95%")
        if r.get("var_pct") is not None:
            out.append(
                f"- **95% Value at Risk (VaR):** −{r['var_pct']:.1%}"
                + (f" (to {_cur(r.get('var_price'), cur)})" if r.get("var_price") is not None else "")
            )
        if r.get("es_pct") is not None:
            out.append(
                f"- **95% Expected Shortfall (ES / CVaR):** −{r['es_pct']:.1%}"
                + (f" (avg {_cur(r.get('es_price'), cur)} in the worst 5%)" if r.get("es_price") is not None else "")
            )
        if r.get("sigma") is not None:
            out.append(f"- Estimated annualized volatility: {_pct(r['sigma'])}.")
        out.append(
            "- *Market-price risk simulated from historical volatility (GBM assumes "
            "lognormal returns and constant volatility); separate from the DCF.*"
        )

    # ---- AI thesis ----
    if data.ai_thesis:
        out.append("\n## AI Investment Thesis")
        news = (
            "Recent news headlines were included."
            if data.ai_news_included
            else "Generated from the valuation numbers alone (news unavailable)."
        )
        out.append(f"*AI-generated (Google Gemini). {news}*\n")
        out.append(data.ai_thesis.strip())
    elif data.ai_note:
        out.append("\n## AI Investment Thesis")
        out.append(f"*{data.ai_note}*")

    # ---- Footer ----
    out.append("\n---")
    out.append(f"_{DISCLAIMER}_")

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# PDF — a clean, single-page analyst report via fpdf2 (never crashes)
# --------------------------------------------------------------------------------------
_LAT1 = {
    "—": "-", "–": "-", "−": "-", "×": "x", "•": "-", "≥": ">=", "≤": "<=",
    "≈": "~", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "⚠": "!",
    "₍": "(", "₎": ")", "→": "->", "∞": "inf",
}


def _lat1(text: str) -> str:
    """Make text safe for fpdf2's latin-1 core fonts (replace fancy glyphs, drop the rest).

    The middle dot (·, U+00B7) used as a separator is itself in latin-1, so it survives."""
    for bad, good in _LAT1.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


# Palette (RGB) — restrained, matches the app's institutional skin.
_INK = (17, 24, 39)        # near-black body
_INK_DARK = (11, 14, 20)   # title
_GREY = (110, 116, 128)    # captions / sub-line
_NAVY = (30, 58, 95)       # section headers / thesis headings
_RULE = (208, 213, 221)    # hairline rules


def _thesis_elements(thesis: str) -> list[tuple[str, str]]:
    """Parse the markdown thesis into a flat list of (kind, text): 'h' for a heading,
    'p' for a paragraph. Consecutive prose / bullet lines are merged into one paragraph so
    the written analysis stays compact (a few sentences per section)."""
    elements: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            elements.append(("p", " ".join(buf)))
            buf.clear()

    for raw in thesis.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped:
            flush()
        elif stripped.startswith("#"):
            flush()
            elements.append(("h", stripped.lstrip("#").strip()))
        elif stripped.startswith(("- ", "* ")):
            buf.append(stripped[2:].strip())
        else:
            buf.append(stripped)
    flush()
    return elements


def build_pdf(data: ReportData) -> bytes:
    """Assemble the report as a clean, single-page PDF.

    Raises RuntimeError only if fpdf2 itself is unavailable; otherwise it always returns
    bytes. Auto page-break is OFF and the written analysis is budgeted against the space
    left above the footer, so the output is always exactly one page."""
    try:
        from fpdf import FPDF
        from fpdf.enums import MethodReturnValue, XPos, YPos
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError("PDF export requires the 'fpdf2' package.") from exc

    cur = data.currency or ""

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(auto=False)  # we manage one-page fit ourselves
    pdf.add_page()
    W = pdf.epw  # effective printable width

    BOTTOM = 12.0
    DISC_RESERVE = 16.0                       # vertical band reserved for the footer
    body_limit = pdf.h - BOTTOM - DISC_RESERVE  # written analysis must stop above this

    def flow(text: str, h: float, size: float, style: str = "",
             color: tuple = _INK) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(W, h, _lat1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def measure(text: str, h: float, size: float, style: str = "") -> float:
        pdf.set_font("Helvetica", style, size)
        return pdf.multi_cell(
            W, h, _lat1(text), dry_run=True, output=MethodReturnValue.HEIGHT
        )

    def rule(gap_before: float = 1.4, gap_after: float = 1.8) -> None:
        pdf.ln(gap_before)
        pdf.set_draw_color(*_RULE)
        pdf.set_line_width(0.2)
        y = pdf.get_y()
        pdf.line(pdf.l_margin, y, pdf.l_margin + W, y)
        pdf.ln(gap_after)

    def section(title: str) -> None:
        pdf.ln(1.2)
        flow(title, 4.8, 10.5, "B", _NAVY)

    sep = "   ·   "

    # ---- Header ----
    flow(f"{data.company_name} ({data.symbol})", 6.6, 15, "B", _INK_DARK)
    sub = []
    if data.report_date:
        sub.append(f"Report date: {data.report_date}")
    if data.current_price is not None:
        sub.append(f"Current price: {_cur(data.current_price, cur)}")
    if cur and cur != "—":
        sub.append(f"Reporting currency: {cur}")
    sub.append("One-page analyst summary")
    flow(sep.join(sub), 4.6, 9, "", _GREY)
    rule()

    # ---- Valuation ----
    v = data.valuation
    if v:
        section("Valuation - Discounted Cash Flow (DCF)")
        line1 = []
        if v.get("value_per_share") is not None:
            line1.append(f"DCF fair value / share: {_cur(v['value_per_share'], cur)}")
        if v.get("upside") is not None:
            verdict = "undervalued" if v["upside"] > 0 else "overvalued"
            line1.append(f"Upside vs market: {_pct(v['upside'], sign=True)} ({verdict})")
        if line1:
            flow(sep.join(line1), 4.8, 9.5, "", _INK)
        line2 = []
        if v.get("enterprise_value") is not None:
            line2.append(f"Enterprise value: {_compact(v['enterprise_value'])}")
        if v.get("equity_value") is not None:
            line2.append(f"Equity value: {_compact(v['equity_value'])}")
        if v.get("wacc") is not None:
            line2.append(f"WACC: {_pct(v['wacc'], dp=2)}")
        if v.get("terminal_growth") is not None:
            line2.append(f"Terminal growth: {_pct(v['terminal_growth'], dp=2)}")
        if line2:
            flow(sep.join(line2), 4.8, 9.5, "", _INK)

    # ---- Multiples ----
    if data.multiples:
        section("Key Multiples")
        flow(sep.join(f"{label}: {value:,.1f}x" for label, value in data.multiples.items()),
             4.8, 9.5, "", _INK)

    # ---- Peers (one-line takeaway) ----
    p = data.peers
    if p and p.get("peer_count"):
        section("Peer Comparison")
        src = {"stock-peers": "FMP stock-peers", "screener": "sector/industry screener"}.get(
            p.get("source", ""), p.get("source", "peer set")
        )
        if p.get("target_pe") is not None and p.get("median_peer_pe") is not None:
            rel = "above" if p["target_pe"] > p["median_peer_pe"] else "below"
            takeaway = (
                f"Trailing P/E {p['target_pe']:,.1f}x vs peer median "
                f"{p['median_peer_pe']:,.1f}x - trading {rel} the median of {p['peer_count']} "
                f"peers (via {src})."
            )
        elif p.get("target_pe") is not None:
            takeaway = (
                f"Trailing P/E {p['target_pe']:,.1f}x across {p['peer_count']} peers (via {src})."
            )
        else:
            takeaway = f"Compared against {p['peer_count']} peers (via {src})."
        flow(takeaway, 4.8, 9.5, "", _INK)

    # ---- Risk ----
    r = data.risk
    if r and (r.get("var_pct") is not None or r.get("es_pct") is not None):
        section("Risk - Monte Carlo (GBM), 1-year, 95%")
        parts = []
        if r.get("var_pct") is not None:
            extra = f" (to {_cur(r.get('var_price'), cur)})" if r.get("var_price") is not None else ""
            parts.append(f"95% Value at Risk: -{r['var_pct']:.1%}{extra}")
        if r.get("es_pct") is not None:
            extra = (
                f" (avg {_cur(r.get('es_price'), cur)} in worst 5%)"
                if r.get("es_price") is not None else ""
            )
            parts.append(f"95% Expected Shortfall: -{r['es_pct']:.1%}{extra}")
        if r.get("sigma") is not None:
            parts.append(f"Annualized volatility: {_pct(r['sigma'])}")
        flow(sep.join(parts), 4.8, 9.5, "", _INK)

    # ---- AI investment thesis (the written analysis) ----
    if data.ai_thesis or data.ai_note:
        section("AI Investment Thesis")
        if data.ai_thesis:
            news = (
                "Recent news headlines were included."
                if data.ai_news_included
                else "Generated from the valuation numbers alone (news unavailable)."
            )
            flow(f"AI-generated (Google Gemini). {news}", 4.0, 8, "I", _GREY)
            pdf.ln(0.6)
            for kind, text in _thesis_elements(data.ai_thesis):
                h = 4.6 if kind == "h" else 4.2
                size = 9.5 if kind == "h" else 9.0
                style = "B" if kind == "h" else ""
                color = _NAVY if kind == "h" else _INK
                lead = 1.0 if kind == "h" else 0.0
                needed = lead + measure(text, h, size, style)
                if pdf.get_y() + needed > body_limit:
                    if body_limit - pdf.get_y() > 4.0:
                        flow("(Full analysis in the Markdown export.)", 4.0, 8, "I", _GREY)
                    break
                if lead:
                    pdf.ln(lead)
                flow(text, h, size, style, color)
        else:
            flow(data.ai_note, 4.4, 9, "I", _GREY)

    # ---- Footer (disclaimer pinned to the bottom) ----
    pdf.set_y(pdf.h - BOTTOM - DISC_RESERVE + 1.0)
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + W, pdf.get_y())
    pdf.ln(1.8)
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_GREY)
    pdf.multi_cell(W, 3.5, _lat1(DISCLAIMER), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    out = pdf.output()
    return bytes(out)
