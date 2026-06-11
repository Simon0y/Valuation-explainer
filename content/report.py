"""Investment-report assembly — packages ALREADY-COMPUTED session results into a
downloadable Markdown or PDF report.

This module is pure: it imports NO Streamlit and makes NO network calls. It only formats a
:class:`ReportData` (plain values the caller has already collected from session state) into
two byte streams. That keeps it unit-testable in isolation and guarantees building a report
can never trigger a new FMP/Gemini call.

Two formats:
  * Markdown — bulletproof primary. Pure string assembly; always works.
  * PDF — richer secondary via fpdf2. The optional price-cone chart is drawn with
    matplotlib (reliable PNG on Streamlit Cloud, no Plotly/kaleido). If the chart — or any
    other optional step — fails, it is skipped and the PDF is still produced.

Every section is OPTIONAL: a ``None``/empty field is skipped gracefully, so a partially
explored session still exports a clean report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
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

    # label -> multiple value, e.g. {"Trailing P/E": 28.4, "EV/EBITDA": 19.1}
    multiples: dict = field(default_factory=dict)

    # source, peer_count, target_pe, median_peer_pe, target_growth
    peers: Optional[dict] = None

    # var_pct, es_pct, var_price, es_price, current_price, sigma, n_paths, horizon_days,
    # and (optional) times + bands {p5,p25,p50,p75,p95} for the PDF chart
    risk: Optional[dict] = None

    ai_thesis: Optional[str] = None
    ai_news_included: bool = False


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
    out.append(f"# Investment Report — {data.company_name} ({data.symbol})")
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
                f"**{p['median_peer_pe']:,.1f}x** — trading **{rel}** the peer median."
            )
        elif p.get("target_pe") is not None:
            out.append(f"- Trailing P/E **{p['target_pe']:,.1f}x**.")

    # ---- Risk ----
    r = data.risk
    if r:
        out.append("\n## Risk — Monte Carlo (GBM), 1-year, 95%")
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

    # ---- Footer ----
    out.append("\n---")
    out.append(f"_{DISCLAIMER}_")

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# PDF (secondary, richer) via fpdf2 — never crashes; chart is best-effort
# --------------------------------------------------------------------------------------
_LAT1 = {
    "—": "-", "–": "-", "−": "-", "×": "x", "•": "-", "≥": ">=", "≤": "<=",
    "≈": "~", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "⚠": "!",
    "₍": "(", "₎": ")", "→": "->",
}


def _lat1(text: str) -> str:
    """Make text safe for fpdf2's latin-1 core fonts (replace fancy glyphs, drop the rest)."""
    for bad, good in _LAT1.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def _risk_cone_png(risk: dict) -> Optional[bytes]:
    """Render the price-risk cone (median + 5–95% / 25–75% bands) as a PNG via matplotlib.

    Returns the PNG bytes, or None if the data is absent or anything fails (the PDF then
    simply omits the chart). Uses the non-interactive Agg backend — no display needed."""
    bands = (risk or {}).get("bands")
    times = (risk or {}).get("times")
    if not bands or times is None:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        months = [t * 12.0 for t in times]
        fig, ax = plt.subplots(figsize=(6.6, 3.4), dpi=150)
        amber, deep, red, grey = "#e8a33d", "#c9882c", "#f85149", "#7d8794"
        ax.fill_between(months, bands["p5"], bands["p95"], color=amber, alpha=0.16, label="5–95%")
        ax.fill_between(months, bands["p25"], bands["p75"], color=amber, alpha=0.30, label="25–75%")
        ax.plot(months, bands["p50"], color=amber, lw=2.0, label="Median path")
        cp = risk.get("current_price")
        if cp is not None:
            ax.axhline(cp, color=grey, ls=":", lw=1.0)
        if risk.get("var_price") is not None:
            ax.axhline(risk["var_price"], color=red, ls="--", lw=1.0, label="95% VaR")
        ax.set_xlabel("Months ahead")
        ax.set_ylabel("Simulated price")
        ax.set_xlim(0, 12)
        ax.legend(loc="upper left", fontsize=7, frameon=False)
        ax.set_title("Monte Carlo price cone (1-year)", fontsize=9)
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — chart is best-effort; never break the PDF
        return None


def build_pdf(data: ReportData) -> bytes:
    """Assemble the report as a PDF (same content as the Markdown, plus the risk chart).

    Raises RuntimeError only if fpdf2 itself is unavailable; otherwise it always returns
    bytes, skipping any optional piece (e.g. the chart) that fails."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError("PDF export requires the 'fpdf2' package.") from exc

    cur = data.currency or ""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    width = pdf.epw           # effective printable width = page width − left/right margins
    label_w = min(60.0, width * 0.42)  # label column; value gets the rest of the width

    # NOTE: fpdf2's multi_cell leaves the cursor at the cell's OWN left edge, not the page
    # margin, so consecutive rows would drift right and clip. Every helper below therefore
    # resets x to the left margin first, and ends each row with new_x=LMARGIN/new_y=NEXT so
    # the next row starts cleanly at the left margin on a fresh line — always within margins.
    def _line(text: str, h: float, size: float, bold: bool) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(width, h, _lat1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h1(text: str) -> None:
        _line(text, 8, 16, True)
        pdf.ln(1)

    def h2(text: str) -> None:
        pdf.ln(2)
        pdf.set_text_color(180, 120, 30)
        _line(text, 7, 12, True)
        pdf.set_text_color(0, 0, 0)

    def body(text: str, bold: bool = False) -> None:
        _line(text, 5.2, 10, bold)

    def kv(label: str, value: str) -> None:
        # Label left-aligned at the left margin; value wraps in the remaining width and
        # returns to the left margin on the next line. Nothing extends past the right margin.
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(label_w, 5.6, _lat1(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(width - label_w, 5.6, _lat1(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ---- Header ----
    h1(f"Investment Report — {data.company_name} ({data.symbol})")
    pdf.set_font("Helvetica", "", 10)
    if data.report_date:
        kv("Date", data.report_date)
    if data.current_price is not None:
        kv("Current price", _cur(data.current_price, cur))

    # ---- Valuation ----
    v = data.valuation
    if v:
        h2("Valuation (DCF)")
        if v.get("value_per_share") is not None:
            kv("DCF fair value / share", _cur(v["value_per_share"], cur))
        if v.get("upside") is not None:
            verdict = "undervalued" if v["upside"] > 0 else "overvalued"
            kv("Upside vs market", f"{_pct(v['upside'], sign=True)} ({verdict})")
        if v.get("enterprise_value") is not None:
            kv("Enterprise value", f"{_compact(v['enterprise_value'])} {cur}".strip())
        if v.get("equity_value") is not None:
            kv("Equity value", f"{_compact(v['equity_value'])} {cur}".strip())
        if v.get("wacc") is not None:
            kv("WACC", _pct(v["wacc"], dp=2))
        if v.get("terminal_growth") is not None:
            kv("Terminal growth", _pct(v["terminal_growth"], dp=2))

    # ---- Multiples ----
    if data.multiples:
        h2("Key Multiples")
        for label, value in data.multiples.items():
            kv(label, f"{value:,.1f}x")

    # ---- Peers ----
    p = data.peers
    if p and p.get("peer_count"):
        h2("Peer Comparison")
        src = {"stock-peers": "FMP stock-peers", "screener": "sector/industry screener"}.get(
            p.get("source", ""), p.get("source", "peer set")
        )
        body(f"Compared against {p['peer_count']} peers (via {src}).")
        if p.get("target_pe") is not None and p.get("median_peer_pe") is not None:
            rel = "above" if p["target_pe"] > p["median_peer_pe"] else "below"
            body(
                f"Trailing P/E {p['target_pe']:,.1f}x vs peer median "
                f"{p['median_peer_pe']:,.1f}x ({rel} the median)."
            )
        elif p.get("target_pe") is not None:
            body(f"Trailing P/E {p['target_pe']:,.1f}x.")

    # ---- Risk ----
    r = data.risk
    if r:
        h2("Risk - Monte Carlo (GBM), 1-year, 95%")
        if r.get("var_pct") is not None:
            extra = f" (to {_cur(r.get('var_price'), cur)})" if r.get("var_price") is not None else ""
            kv("95% Value at Risk", f"-{r['var_pct']:.1%}{extra}")
        if r.get("es_pct") is not None:
            extra = f" (avg {_cur(r.get('es_price'), cur)} in worst 5%)" if r.get("es_price") is not None else ""
            kv("95% Expected Shortfall", f"-{r['es_pct']:.1%}{extra}")
        if r.get("sigma") is not None:
            kv("Annualized volatility", _pct(r["sigma"]))
        png = _risk_cone_png(r)
        if png:
            try:
                pdf.ln(2)
                pdf.image(BytesIO(png), w=width)
            except Exception:  # noqa: BLE001 — image embed is best-effort
                pass

    # ---- AI thesis ----
    if data.ai_thesis:
        h2("AI Investment Thesis")
        news = (
            "Recent news headlines were included."
            if data.ai_news_included
            else "Generated from the valuation numbers alone (news unavailable)."
        )
        body(f"AI-generated (Google Gemini). {news}", bold=False)
        pdf.ln(1)
        for raw in data.ai_thesis.splitlines():
            line = raw.rstrip()
            if not line.strip():
                pdf.ln(1.5)
                continue
            stripped = line.lstrip("#").strip()
            if line.lstrip().startswith("#"):
                body(stripped, bold=True)
            elif line.lstrip().startswith(("- ", "* ")):
                body(f"  - {line.lstrip()[2:].strip()}")
            else:
                body(line)

    # ---- Footer ----
    pdf.ln(3)
    pdf.set_draw_color(180, 180, 180)
    pdf.cell(width, 0, "", border="T")
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(width, 4.2, _lat1(DISCLAIMER))

    out = pdf.output()
    return bytes(out)
