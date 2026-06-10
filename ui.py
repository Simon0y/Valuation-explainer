"""Presentation helpers for the Streamlit frontend: glossary popovers and plotly charts.
This is UI code (it imports Streamlit/plotly) — it contains NO finance math and is kept
separate from the pure `engine/` package.

Visual language lives in `ui_theme.py` (the terminal skin + shared palette). The charts
below import that palette so the plots match the page: dark surfaces, an amber accent,
green/red reserved strictly for positive/negative deltas, and monospaced tabular figures.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from content.glossary import get as glossary_get
from engine.models import DCFResult, LBOResult
from ui_theme import (
    ACCENT,
    ACCENT_DEEP,
    BG,
    BORDER,
    GREEN,
    GRID,
    MONO,
    MUTED,
    PANEL,
    PANEL_ALT,
    RED,
    SANS,
    TEXT,
    TEXT_BRIGHT,
)

# Chart-local aliases onto the shared terminal palette.
SURFACE = PANEL          # chart paper/plot background (tile surface)
ACCENT_LINE = "#7d8794"  # subordinate secondary line (muted, kept below the accent bars)
INK = TEXT_BRIGHT        # bright figures on dark
HAIRLINE = BORDER        # connectors / axis lines


# --------------------------------------------------------------------------------------
# Glossary popovers
# --------------------------------------------------------------------------------------
def term_popover(key: str) -> None:
    """Render a single clickable glossary “chip” that expands to a plain-language def."""
    entry = glossary_get(key)
    with st.popover(entry["term"].split(" — ")[0]):
        st.markdown(f"**{entry['term']}**")
        st.markdown(entry["long"])


def term_row(keys: list[str], label: str = "Key terms — click any to learn more:") -> None:
    """Render a horizontal row of glossary chips."""
    st.caption(label)
    cols = st.columns(len(keys))
    for col, key in zip(cols, keys):
        with col:
            term_popover(key)


# --------------------------------------------------------------------------------------
# Plotly styling — dark terminal surface, amber accent, thin gridlines, clean fonts
# --------------------------------------------------------------------------------------
def _style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=SANS.replace("'", ""), color=TEXT, size=12),
        height=height,
        margin=dict(l=10, r=10, t=28, b=10),
        showlegend=False,
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=HAIRLINE, font_size=12,
                        font_family=MONO.replace("'", "")),
    )
    fig.update_xaxes(showgrid=False, color=MUTED, linecolor=HAIRLINE, ticks="outside",
                     tickcolor=HAIRLINE)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=True,
                     zerolinecolor=HAIRLINE, color=MUTED,
                     tickfont=dict(family=MONO.replace("'", "")))
    return fig


def _fmt_compact(value: float) -> str:
    """Compact money label for chart annotations (e.g. 1.9T, 58B, 940M)."""
    a = abs(value)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{value/div:,.1f}{suffix}"
    return f"{value:,.0f}"


# --------------------------------------------------------------------------------------
# DCF waterfall: forecast PV -> + terminal PV -> = EV -> - net debt -> = equity
# (increases green, decreases red — terminal convention; totals amber)
# --------------------------------------------------------------------------------------
def dcf_waterfall(result: DCFResult, currency: str) -> go.Figure:
    x = [
        "PV of forecast FCFF",
        "PV of terminal value",
        "Enterprise value",
        "Less: net debt",
        "Equity value",
    ]
    measure = ["relative", "relative", "total", "relative", "total"]
    y = [
        result.sum_pv_fcff,
        result.pv_terminal_value,
        0.0,
        -result.net_debt,
        0.0,
    ]
    text = [
        _fmt_compact(result.sum_pv_fcff),
        _fmt_compact(result.pv_terminal_value),
        _fmt_compact(result.enterprise_value),
        _fmt_compact(-result.net_debt),
        _fmt_compact(result.equity_value),
    ]
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=measure,
            x=x,
            y=y,
            text=text,
            textposition="outside",
            textfont=dict(family=MONO.replace("'", ""), color=INK, size=11),
            connector=dict(line=dict(color=HAIRLINE, width=1)),
            increasing=dict(marker=dict(color=GREEN)),
            decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=ACCENT)),
        )
    )
    fig.update_yaxes(title_text=f"Value ({currency})", title_font=dict(color=MUTED, size=11))
    return _style(fig, height=380)


# --------------------------------------------------------------------------------------
# LBO debt-paydown chart: ending debt by year (amber bars) with EBITDA (subordinate line)
# --------------------------------------------------------------------------------------
def lbo_debt_chart(result: LBOResult, currency: str) -> go.Figure:
    labels = ["Entry"] + [f"Year {y.year}" for y in result.schedule]
    debt = [result.entry_debt] + [y.ending_debt for y in result.schedule]
    ebitda = [result.assumptions.entry_ebitda] + [y.ebitda for y in result.schedule]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=labels, y=debt, name="Net debt outstanding",
            marker=dict(color=ACCENT), width=0.6,
            text=[_fmt_compact(d) for d in debt], textposition="outside",
            textfont=dict(family=MONO.replace("'", ""), color=INK, size=10),
            hovertemplate="%{x}<br>Debt: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=labels, y=ebitda, name="EBITDA", mode="lines+markers",
            line=dict(color=ACCENT_LINE, width=2), marker=dict(size=6, color=ACCENT_LINE),
            hovertemplate="%{x}<br>EBITDA: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title_text=f"Debt ({currency})", secondary_y=False,
                     title_font=dict(color=MUTED, size=11))
    fig.update_yaxes(title_text=f"EBITDA ({currency})", secondary_y=True, showgrid=False,
                     title_font=dict(color=MUTED, size=11))
    fig = _style(fig, height=380)
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", y=1.14, x=0, font=dict(size=11, color=MUTED),
                    bgcolor="rgba(0,0,0,0)"),
    )
    return fig


# --------------------------------------------------------------------------------------
# DCF sensitivity heatmap: fair value / share across a WACC × terminal-growth grid.
# `values` is rows=terminal growth, cols=WACC; cells where g∞ >= WACC are NaN (blank).
# The caller supplies the base-case cell indices so we can outline it.
# --------------------------------------------------------------------------------------
def sensitivity_heatmap(
    wacc_axis: list[float],
    tg_axis: list[float],
    values: list[list[float]],
    base_col: int,
    base_row: int,
    currency: str,
) -> go.Figure:
    x_labels = [f"{w:.2%}" for w in wacc_axis]
    y_labels = [f"{g:.2%}" for g in tg_axis]

    # vmin/vmax over the valid (non-NaN) cells, for the colorscale + text contrast.
    flat = [v for row in values for v in row if v == v]  # v == v filters out NaN
    vmin = min(flat) if flat else 0.0
    vmax = max(flat) if flat else 1.0
    span = (vmax - vmin) or 1.0

    # Dark panel (low) → amber (high) — stays within the app's terminal palette.
    colorscale = [[0.0, PANEL_ALT], [0.5, ACCENT_DEEP], [1.0, ACCENT]]

    fig = go.Figure(
        go.Heatmap(
            z=values,
            x=x_labels,
            y=y_labels,
            colorscale=colorscale,
            hoverongaps=False,
            xgap=2,
            ygap=2,
            colorbar=dict(
                title=dict(text=f"Value/share ({currency})", font=dict(color=MUTED, size=11)),
                tickfont=dict(color=MUTED, size=10, family=MONO.replace("'", "")),
                outlinewidth=0, thickness=12, len=0.9,
            ),
            hovertemplate="WACC %{x}<br>Terminal growth %{y}"
                          "<br>Value/share: %{z:,.2f}<extra></extra>",
        )
    )

    # Per-cell value annotations with contrast-aware text colour (light on dark cells,
    # dark on bright amber cells). NaN cells get a muted dash to show they're intentional.
    annotations = []
    for r, row in enumerate(values):
        for c, v in enumerate(row):
            if v != v:  # NaN
                annotations.append(dict(
                    x=x_labels[c], y=y_labels[r], text="—", showarrow=False,
                    font=dict(color=MUTED, size=11, family=MONO.replace("'", "")),
                ))
                continue
            norm = (v - vmin) / span
            txt_color = BG if norm > 0.55 else TEXT_BRIGHT
            annotations.append(dict(
                x=x_labels[c], y=y_labels[r], text=f"{v:,.2f}", showarrow=False,
                font=dict(color=txt_color, size=10.5, family=MONO.replace("'", "")),
            ))

    # Outline the base-case cell (categorical axes index cells at 0,1,2,…).
    base_outline = dict(
        type="rect", xref="x", yref="y",
        x0=base_col - 0.5, x1=base_col + 0.5,
        y0=base_row - 0.5, y1=base_row + 0.5,
        line=dict(color=TEXT_BRIGHT, width=2.5), fillcolor="rgba(0,0,0,0)", layer="above",
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=SANS.replace("'", ""), color=TEXT, size=12),
        height=380, margin=dict(l=10, r=10, t=30, b=10),
        annotations=annotations, shapes=[base_outline],
        xaxis=dict(title=dict(text="WACC (discount rate)", font=dict(color=MUTED, size=11)),
                   color=MUTED, tickfont=dict(family=MONO.replace("'", ""), size=10),
                   showgrid=False, constrain="domain"),
        # go.Heatmap places z row 0 at the bottom, so ascending terminal growth reads
        # upward (higher growth → higher up), the natural orientation for the y-axis.
        yaxis=dict(title=dict(text="Terminal growth (g∞)", font=dict(color=MUTED, size=11)),
                   color=MUTED, tickfont=dict(family=MONO.replace("'", ""), size=10),
                   showgrid=False),
    )
    return fig


# --------------------------------------------------------------------------------------
# Peers bubble chart: relative valuation — X = P/E, Y = revenue growth YoY, size = mkt cap.
# Target company in the amber accent (drawn on top); peers muted grey so it stands out.
# `points` are display-ready dicts: {symbol, pe, growth (decimal), market_cap, cap_label,
# is_target}. The caller filters out null/garbage rows before passing them in.
# --------------------------------------------------------------------------------------
def peer_bubble(points: list[dict], pe_label: str) -> go.Figure:
    peers = [p for p in points if not p["is_target"]]
    target = [p for p in points if p["is_target"]]

    caps = [p["market_cap"] for p in points if p["market_cap"]]
    maxcap = max(caps) if caps else 1.0
    sizeref = 2.0 * maxcap / (62.0**2)  # ~62px largest bubble (Plotly area sizing)

    def _trace(group, fill, line_c, text_c, name, opacity):
        return go.Scatter(
            x=[p["pe"] for p in group],
            y=[p["growth"] * 100.0 for p in group],   # decimal → percent for the axis
            mode="markers+text",
            text=[p["symbol"] for p in group],
            textposition="middle center",
            textfont=dict(family=MONO.replace("'", ""), size=9, color=text_c),
            customdata=[[p["cap_label"]] for p in group],
            marker=dict(
                size=[p["market_cap"] for p in group],
                sizemode="area", sizeref=sizeref, sizemin=6,
                color=fill, opacity=opacity, line=dict(width=1.2, color=line_c),
            ),
            name=name,
            hovertemplate=(
                "<b>%{text}</b><br>" + pe_label + ": %{x:.1f}×<br>"
                "Rev growth YoY: %{y:+.1f}%<br>Market cap: %{customdata[0]}<extra></extra>"
            ),
        )

    fig = go.Figure()
    if peers:
        fig.add_trace(_trace(peers, MUTED, "#9aa4b2", TEXT_BRIGHT, "Peers", 0.45))
    if target:
        fig.add_trace(_trace(target, ACCENT, TEXT_BRIGHT, BG, target[0]["symbol"], 0.95))

    fig = _style(fig, height=460)
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=MUTED),
                    bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(title_text=pe_label, title_font=dict(color=MUTED, size=11),
                     ticksuffix="×", zeroline=False)
    fig.update_yaxes(title_text="Revenue growth YoY", title_font=dict(color=MUTED, size=11),
                     ticksuffix="%")
    return fig


# --------------------------------------------------------------------------------------
# Risk probability cone: median GBM path with shaded 5–95% and 25–75% bands fanning out
# over the year from the current price. Amber palette; the present price is marked at t=0.
# `times_years` and the band arrays come straight from engine.montecarlo (no math here).
# --------------------------------------------------------------------------------------
def risk_cone(
    times_years,
    bands: dict,
    current_price: float,
    currency: str,
    var_price: float | None = None,
) -> go.Figure:
    months = [t * 12.0 for t in times_years]  # x-axis reads in months ahead (0 → 12)

    def _band(lower, upper, fill, name):
        # An upper trace then a filled-to-previous lower trace = a shaded ribbon.
        return [
            go.Scatter(
                x=months, y=list(upper), mode="lines", line=dict(width=0),
                hoverinfo="skip", showlegend=False, name=f"{name} upper",
            ),
            go.Scatter(
                x=months, y=list(lower), mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor=fill, hoverinfo="skip", name=name,
            ),
        ]

    fig = go.Figure()
    # Outer 5–95% ribbon (faint amber), then inner 25–75% ribbon (deeper amber).
    for tr in _band(bands["p5"], bands["p95"], "rgba(232,163,61,0.14)", "5–95% range"):
        fig.add_trace(tr)
    for tr in _band(bands["p25"], bands["p75"], "rgba(232,163,61,0.30)", "25–75% range"):
        fig.add_trace(tr)

    # Median path (amber line).
    fig.add_trace(go.Scatter(
        x=months, y=list(bands["p50"]), mode="lines",
        line=dict(color=ACCENT, width=2.2), name="Median path",
        hovertemplate="Month %{x:.0f}<br>Median: %{y:,.2f}<extra></extra>",
    ))

    # Current price: a horizontal reference line + a marked point at t=0.
    fig.add_hline(y=current_price, line=dict(color=ACCENT_LINE, width=1, dash="dot"),
                  annotation_text=f"Now {current_price:,.2f}",
                  annotation_position="top left",
                  annotation_font=dict(color=MUTED, size=10, family=MONO.replace("'", "")))
    fig.add_trace(go.Scatter(
        x=[0], y=[current_price], mode="markers",
        marker=dict(color=ACCENT, size=9, line=dict(color=BG, width=1.5)),
        name="Current price",
        hovertemplate="Today<br>%{y:,.2f}<extra></extra>",
    ))

    # 95% VaR threshold price (dashed red) — the 1-year downside cutoff.
    if var_price is not None:
        fig.add_hline(y=var_price, line=dict(color=RED, width=1, dash="dash"),
                      annotation_text=f"95% VaR {var_price:,.2f}",
                      annotation_position="bottom left",
                      annotation_font=dict(color=RED, size=10, family=MONO.replace("'", "")))

    fig = _style(fig, height=420)
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=11, color=MUTED),
                    bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(title_text="Months ahead", title_font=dict(color=MUTED, size=11),
                     range=[0, 12], dtick=2, zeroline=False)
    fig.update_yaxes(title_text=f"Simulated price ({currency})",
                     title_font=dict(color=MUTED, size=11))
    return fig
