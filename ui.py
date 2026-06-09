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
    BORDER,
    GREEN,
    GRID,
    MONO,
    MUTED,
    PANEL,
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
