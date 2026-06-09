"""Presentation helpers for the Streamlit frontend: theme CSS, glossary popovers, and
plotly charts. This is UI code (it imports Streamlit/plotly) — it contains NO finance
math and is kept separate from the pure `engine/` package.

Visual language: clean institutional finance. Light background, a single navy accent,
green/red reserved strictly for positive/negative deltas, Inter for text and IBM Plex
Mono (tabular figures) for all numbers.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from content.glossary import get as glossary_get
from engine.models import DCFResult, LBOResult

# Institutional palette.
NAVY = "#1e3a5f"          # single accent — key numbers, totals, active states
NAVY_DEEP = "#0b2545"
NAVY_LIGHT = "#5b7fa6"    # secondary line on charts (kept subordinate to NAVY)
INK = "#1a1a2e"           # near-black text
MUTED = "#6b7280"         # secondary text / axis labels
HAIRLINE = "#e3e6ea"      # 1px dividers / borders
GRID = "#eceef1"          # faint table row rules
GREEN = "#157f57"         # positive delta only
RED = "#c0392b"           # negative delta only
WHITE = "#ffffff"

MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


# --------------------------------------------------------------------------------------
# Theme / layout CSS
# --------------------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

        /* ---- Base typography ---- */
        html, body, .stApp, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #1a1a2e;
        }
        .block-container { padding-top: 2.0rem; padding-bottom: 3rem; max-width: 1180px; }

        h1 { font-weight: 700; letter-spacing: -0.02em; color: #1e3a5f; font-size: 1.85rem; }
        h2 { font-weight: 600; letter-spacing: -0.01em; color: #1a1a2e; font-size: 1.25rem;
             margin-top: 0.4rem; }
        h3 { font-weight: 600; letter-spacing: -0.01em; color: #1a1a2e; font-size: 1.02rem; }
        [data-testid="stCaptionContainer"], .stCaption, small { color: #6b7280; }

        /* Tabular figures for inline numbers in prose too */
        body { font-feature-settings: "tnum" 1, "lnum" 1; }

        /* ---- Metric cards: flat, hairline border, no shadow ---- */
        [data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e3e6ea;
            border-radius: 4px;
            padding: 14px 16px;
            box-shadow: none;
        }
        [data-testid="stMetricLabel"] p {
            color: #6b7280; font-size: 0.72rem; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.05em;
        }
        [data-testid="stMetricValue"] {
            font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
            font-variant-numeric: tabular-nums;
            font-weight: 600; color: #1e3a5f; font-size: 1.5rem;
        }
        [data-testid="stMetricDelta"] { font-variant-numeric: tabular-nums; font-weight: 500; }
        [data-testid="stMetricDelta"] svg { display: none; }  /* drop the arrow glyph */

        /* ---- Tables: thin rules, generous spacing, monospaced right-aligned numbers ---- */
        [data-testid="stTable"] { overflow-x: auto; }
        [data-testid="stTable"] table {
            border-collapse: collapse; width: 100%; font-size: 0.86rem; background: #fff;
        }
        [data-testid="stTable"] thead th {
            background: #ffffff; color: #1e3a5f;
            font-weight: 600; font-size: 0.70rem; text-transform: uppercase;
            letter-spacing: 0.04em; text-align: right;
            border-bottom: 1px solid #c9ced6; padding: 9px 16px; white-space: nowrap;
        }
        [data-testid="stTable"] thead th:first-child { text-align: left; }   /* index header */
        [data-testid="stTable"] tbody th {                                   /* row labels */
            text-align: left; font-weight: 500; color: #1a1a2e;
            padding: 8px 16px; border-bottom: 1px solid #eceef1; white-space: nowrap;
        }
        [data-testid="stTable"] tbody td {                                   /* figures */
            font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
            font-variant-numeric: tabular-nums;
            text-align: right; color: #1a1a2e;
            padding: 8px 16px; border-bottom: 1px solid #eceef1; white-space: nowrap;
        }
        [data-testid="stTable"] tbody tr:last-child th,
        [data-testid="stTable"] tbody tr:last-child td { border-bottom: none; }
        [data-testid="stTable"] tbody tr:hover td,
        [data-testid="stTable"] tbody tr:hover th { background: #f7f8fa; }

        /* ---- Tabs: minimal, navy active ---- */
        [data-testid="stTabs"] button[role="tab"] {
            font-weight: 600; color: #6b7280; padding: 0.4rem 0.9rem;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: #1e3a5f; }
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] { background-color: #1e3a5f; }
        [data-testid="stTabs"] [data-baseweb="tab-border"] { background-color: #e3e6ea; }

        /* ---- Glossary chips (popover triggers): understated, hairline ---- */
        div[data-testid="stPopover"] > button {
            border-radius: 3px; border: 1px solid #d4d9e0; background: #ffffff;
            color: #1e3a5f; padding: 0.12rem 0.6rem; font-size: 0.76rem; font-weight: 500;
            box-shadow: none;
        }
        div[data-testid="stPopover"] > button:hover {
            border-color: #1e3a5f; background: #f0f3f7; color: #0b2545;
        }

        /* ---- Expanders: hairline, minimal rounding ---- */
        [data-testid="stExpander"] details {
            border: 1px solid #e3e6ea; border-radius: 4px; background: #ffffff;
        }
        [data-testid="stExpander"] summary { font-weight: 600; color: #1a1a2e; }

        /* ---- Buttons: navy, square-ish ---- */
        [data-testid="stBaseButton-primary"] {
            border-radius: 4px; font-weight: 600; background: #1e3a5f; border: 1px solid #1e3a5f;
        }
        [data-testid="stBaseButton-primary"]:hover { background: #0b2545; border-color: #0b2545; }

        /* ---- Alerts: soften the consumer pastel into a hairline panel ---- */
        [data-testid="stAlert"] { border-radius: 4px; border: 1px solid #e3e6ea; }

        /* ---- Sidebar: hairline separation ---- */
        [data-testid="stSidebar"] { border-right: 1px solid #e3e6ea; }

        /* ---- Dividers ---- */
        hr { border-color: #e3e6ea; margin: 1.2rem 0; }
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
# Plotly styling — white background, navy bars, thin gridlines, clean fonts
# --------------------------------------------------------------------------------------
def _style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        font=dict(family=SANS.replace("'", ""), color=INK, size=12),
        height=height,
        margin=dict(l=10, r=10, t=28, b=10),
        showlegend=False,
        hoverlabel=dict(bgcolor=WHITE, bordercolor=HAIRLINE, font_size=12,
                        font_family=MONO.replace("'", "")),
    )
    fig.update_xaxes(showgrid=False, color=MUTED, linecolor=HAIRLINE, ticks="outside",
                     tickcolor=HAIRLINE)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=True,
                     zerolinecolor="#c9ced6", color=MUTED,
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
# (increases green, decreases red — terminal convention; totals navy)
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
            totals=dict(marker=dict(color=NAVY)),
        )
    )
    fig.update_yaxes(title_text=f"Value ({currency})", title_font=dict(color=MUTED, size=11))
    return _style(fig, height=380)


# --------------------------------------------------------------------------------------
# LBO debt-paydown chart: ending debt by year (navy bars) with EBITDA (subordinate line)
# --------------------------------------------------------------------------------------
def lbo_debt_chart(result: LBOResult, currency: str) -> go.Figure:
    labels = ["Entry"] + [f"Year {y.year}" for y in result.schedule]
    debt = [result.entry_debt] + [y.ending_debt for y in result.schedule]
    ebitda = [result.assumptions.entry_ebitda] + [y.ebitda for y in result.schedule]

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=labels, y=debt, name="Net debt outstanding",
            marker=dict(color=NAVY), width=0.6,
            text=[_fmt_compact(d) for d in debt], textposition="outside",
            textfont=dict(family=MONO.replace("'", ""), color=INK, size=10),
            hovertemplate="%{x}<br>Debt: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=labels, y=ebitda, name="EBITDA", mode="lines+markers",
            line=dict(color=NAVY_LIGHT, width=2), marker=dict(size=6, color=NAVY_LIGHT),
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
