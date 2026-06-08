"""Presentation helpers for the Streamlit frontend: theme CSS, glossary popovers, and
plotly charts. This is UI code (it imports Streamlit/plotly) — it contains NO finance
math and is kept separate from the pure `engine/` package.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from content.glossary import get as glossary_get
from engine.models import DCFResult, LBOResult

# Palette — kept in sync with .streamlit/config.toml.
ACCENT = "#5B8DEF"
GREEN = "#3FB984"
RED = "#E06C75"
CARD_BG = "#161C28"
GRID = "#232B3A"
TEXT = "#E6E9EF"
MUTED = "#9AA4B2"


# --------------------------------------------------------------------------------------
# Theme / layout CSS
# --------------------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* Tighten the top padding and widen the readable column. */
        .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1200px; }

        /* Typography */
        html, body, [class*="css"] { font-feature-settings: "tnum"; }
        h1 { font-weight: 700; letter-spacing: -0.02em; }
        h2, h3 { font-weight: 650; letter-spacing: -0.01em; }

        /* Metric “cards” */
        [data-testid="stMetric"] {
            background: #161C28;
            border: 1px solid #232B3A;
            border-radius: 14px;
            padding: 16px 18px;
            box-shadow: 0 1px 0 rgba(255,255,255,0.02) inset;
        }
        [data-testid="stMetricLabel"] p { color: #9AA4B2; font-size: 0.82rem; }
        [data-testid="stMetricValue"] { font-size: 1.7rem; font-weight: 680; }

        /* Bordered containers read as panels */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 14px;
        }

        /* Expanders: calmer, card-like */
        [data-testid="stExpander"] details {
            border: 1px solid #232B3A;
            border-radius: 12px;
            background: rgba(22,28,40,0.5);
        }
        [data-testid="stExpander"] summary { font-weight: 600; }

        /* Tabs: larger, clearer active state */
        [data-testid="stTabs"] button[role="tab"] {
            font-size: 1.0rem; font-weight: 600; padding: 0.4rem 0.9rem;
        }

        /* Popover “chips” for glossary terms */
        div[data-testid="stPopover"] > button {
            border-radius: 999px;
            border: 1px solid #2C3A57;
            background: rgba(91,141,239,0.10);
            color: #BBD0FF;
            padding: 0.15rem 0.7rem;
            font-size: 0.8rem;
            font-weight: 600;
        }
        div[data-testid="stPopover"] > button:hover {
            border-color: #5B8DEF; background: rgba(91,141,239,0.18);
        }

        /* Section divider spacing */
        hr { margin: 1.4rem 0; border-color: #1E2735; }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
# Plotly styling
# --------------------------------------------------------------------------------------
def _style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=13),
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
        hoverlabel=dict(bgcolor=CARD_BG, font_size=12),
    )
    fig.update_xaxes(showgrid=False, color=MUTED)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
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
    # For "total" steps plotly ignores y and shows the running cumulative.
    y = [
        result.sum_pv_fcff,
        result.pv_terminal_value,
        0.0,
        -result.net_debt,          # subtracting net debt (negative net debt => adds)
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
            connector=dict(line=dict(color=GRID)),
            increasing=dict(marker=dict(color=GREEN)),
            decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=ACCENT)),
        )
    )
    fig.update_yaxes(title_text=f"Value ({currency})")
    return _style(fig, height=380)


# --------------------------------------------------------------------------------------
# LBO debt-paydown chart: ending debt by year (bars) with EBITDA (line, 2nd axis)
# --------------------------------------------------------------------------------------
def lbo_debt_chart(result: LBOResult, currency: str) -> go.Figure:
    labels = ["Entry"] + [f"Year {y.year}" for y in result.schedule]
    debt = [result.entry_debt] + [y.ending_debt for y in result.schedule]
    ebitda = [result.assumptions.entry_ebitda] + [y.ebitda for y in result.schedule]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=labels, y=debt, name="Net debt outstanding",
            marker=dict(color=ACCENT), opacity=0.85,
            text=[_fmt_compact(d) for d in debt], textposition="outside",
            hovertemplate="%{x}<br>Debt: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=labels, y=ebitda, name="EBITDA", mode="lines+markers",
            line=dict(color=GREEN, width=3), marker=dict(size=7),
            hovertemplate="%{x}<br>EBITDA: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=True,
    )
    fig.update_yaxes(title_text=f"Debt ({currency})", secondary_y=False)
    fig.update_yaxes(title_text=f"EBITDA ({currency})", secondary_y=True, showgrid=False)
    fig = _style(fig, height=380)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12, x=0))
    return fig
