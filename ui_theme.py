"""Light institutional theme for the Streamlit frontend.

This module owns the *visual language* only — a clean, restrained, asset-manager-inspired
skin (white / off-white surfaces, near-black text, hairline-bordered flat cards, a single
muted-navy accent reserved for active states, links and headline numbers, and tabular
sans-serif figures). It contains NO finance math and NO layout logic; it just exposes the
shared palette and one `inject_css()` entry point.

Charts (in `ui.py`) import the palette below so the plots match the page.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------------------
# Light institutional palette — single source of truth (charts import these too)
# --------------------------------------------------------------------------------------
BG = "#f7f8fa"            # app background — off-white
PANEL = "#ffffff"         # tiles, cards, sidebar surface — white
PANEL_ALT = "#f1f3f6"     # hover / alternating rows
BORDER = "#e4e7ec"        # 1px hairline borders / dividers
BORDER_BRIGHT = "#d3d8e0" # slightly stronger rule (table header underline)
TEXT = "#1a1f29"          # primary text — near-black
TEXT_BRIGHT = "#0b0e14"   # headline numbers / headers — darkest
MUTED = "#6b7280"         # labels, captions, axis ticks — slate grey
ACCENT = "#1e3a5f"        # single accent — active tab, links, key totals (muted navy)
ACCENT_DEEP = "#16304d"   # accent hover / pressed
GREEN = "#1f7a4d"         # positive delta only (muted)
RED = "#b3261e"           # negative delta only (muted)
GRID = "#eef0f3"          # faint chart gridlines

# Numbers use the same grotesque sans with tabular figures (no monospace "terminal" feel).
SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
NUM = SANS  # chart number labels share the sans; HTML numbers get tabular-nums via CSS


def inject_css() -> None:
    """Inject the light institutional skin. Idempotent; call once after set_page_config."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* ---- Base ---- */
        .stApp {{ background: {BG}; }}
        html, body, .stApp, [class*="css"] {{
            font-family: {SANS};
            color: {TEXT};
        }}
        body {{ font-feature-settings: "tnum" 1, "lnum" 1; }}
        .block-container {{ padding-top: 2.6rem; padding-bottom: 3.5rem; max-width: 1240px; }}

        /* ---- Headers: near-black, title-case, restrained ---- */
        h1 {{ font-weight: 600; letter-spacing: -0.01em; color: {TEXT_BRIGHT};
              font-size: 1.6rem; }}
        h2 {{ font-weight: 600; letter-spacing: 0; color: {TEXT_BRIGHT};
              font-size: 1.12rem; margin-top: 0.5rem; }}
        h3 {{ font-weight: 600; letter-spacing: 0; color: {TEXT_BRIGHT};
              font-size: 0.96rem; }}
        [data-testid="stCaptionContainer"], .stCaption, small {{ color: {MUTED}; }}
        a, a:visited {{ color: {ACCENT}; text-decoration: none; }}
        a:hover {{ color: {ACCENT_DEEP}; text-decoration: underline; }}

        /* ---- Metric tiles: flat card, subtle border, no shadow ---- */
        [data-testid="stMetric"] {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 14px 18px;
            box-shadow: none;
        }}
        [data-testid="stMetricLabel"] p {{
            color: {MUTED}; font-size: 0.68rem; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.08em;
        }}
        [data-testid="stMetricValue"] {{
            font-variant-numeric: tabular-nums;
            font-weight: 600; color: {TEXT_BRIGHT}; font-size: 1.5rem;
            letter-spacing: -0.01em;
        }}
        [data-testid="stMetricDelta"] {{
            font-variant-numeric: tabular-nums;
            font-weight: 500; font-size: 0.8rem;
        }}
        [data-testid="stMetricDelta"] svg {{ display: none; }}   /* drop arrow glyph */

        /* ---- Tables: thin rules, right-aligned tabular figures ---- */
        [data-testid="stTable"] {{ overflow-x: auto; }}
        [data-testid="stTable"] table {{
            border-collapse: collapse; width: 100%; font-size: 0.85rem;
            background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
        }}
        [data-testid="stTable"] thead th {{
            background: {PANEL_ALT}; color: {MUTED};
            font-weight: 600; font-size: 0.68rem; text-transform: uppercase;
            letter-spacing: 0.06em; text-align: right;
            border-bottom: 1px solid {BORDER_BRIGHT}; padding: 10px 16px; white-space: nowrap;
        }}
        [data-testid="stTable"] thead th:first-child {{ text-align: left; }}
        [data-testid="stTable"] tbody th {{
            text-align: left; font-weight: 500; color: {TEXT};
            padding: 8px 16px; border-bottom: 1px solid {BORDER}; white-space: nowrap;
        }}
        [data-testid="stTable"] tbody td {{
            font-variant-numeric: tabular-nums;
            text-align: right; color: {TEXT_BRIGHT};
            padding: 8px 16px; border-bottom: 1px solid {BORDER}; white-space: nowrap;
        }}
        [data-testid="stTable"] tbody tr:last-child th,
        [data-testid="stTable"] tbody tr:last-child td {{ border-bottom: none; }}
        [data-testid="stTable"] tbody tr:hover td,
        [data-testid="stTable"] tbody tr:hover th {{ background: {PANEL_ALT}; }}

        /* ---- Tabs: minimal, navy active underline ---- */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {{
            gap: 0.4rem; border-bottom: 1px solid {BORDER};
        }}
        [data-testid="stTabs"] button[role="tab"] {{
            font-weight: 500; color: {MUTED}; padding: 0.5rem 1.0rem;
            font-size: 0.9rem; letter-spacing: 0;
        }}
        [data-testid="stTabs"] button[role="tab"]:hover {{ color: {TEXT_BRIGHT}; }}
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
            color: {ACCENT}; font-weight: 600;
        }}
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; }}
        [data-testid="stTabs"] [data-baseweb="tab-border"] {{ background-color: {BORDER}; }}

        /* ---- Glossary chips (popover triggers) ---- */
        div[data-testid="stPopover"] > button {{
            border-radius: 6px; border: 1px solid {BORDER_BRIGHT}; background: {PANEL};
            color: {ACCENT}; padding: 0.14rem 0.65rem; font-size: 0.78rem; font-weight: 500;
            box-shadow: none;
        }}
        div[data-testid="stPopover"] > button:hover {{
            border-color: {ACCENT}; background: {PANEL_ALT}; color: {ACCENT_DEEP};
        }}

        /* ---- Expanders ---- */
        [data-testid="stExpander"] details {{
            border: 1px solid {BORDER}; border-radius: 6px; background: {PANEL};
        }}
        [data-testid="stExpander"] summary {{ font-weight: 600; color: {TEXT_BRIGHT}; }}
        [data-testid="stExpander"] summary:hover {{ color: {ACCENT}; }}

        /* ---- Buttons: navy primary, flat ---- */
        [data-testid="stBaseButton-primary"] {{
            border-radius: 6px; font-weight: 600; color: #ffffff;
            background: {ACCENT}; border: 1px solid {ACCENT}; box-shadow: none;
        }}
        [data-testid="stBaseButton-primary"]:hover {{
            background: {ACCENT_DEEP}; border-color: {ACCENT_DEEP}; color: #ffffff;
        }}

        /* ---- Alerts: hairline panels, restrained ---- */
        [data-testid="stAlert"] {{
            border-radius: 6px; border: 1px solid {BORDER}; background: {PANEL};
            color: {TEXT};
        }}

        /* ---- Sidebar: white surface + hairline ---- */
        [data-testid="stSidebar"] {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
        [data-testid="stSidebar"] h2 {{ font-size: 0.9rem; }}
        [data-testid="stSidebar"] h3 {{ font-size: 0.8rem; color: {MUTED};
            text-transform: uppercase; letter-spacing: 0.06em; }}

        /* ---- Inputs ---- */
        [data-testid="stTextInput"] input {{
            font-variant-numeric: tabular-nums; background: {PANEL}; color: {TEXT_BRIGHT};
            border: 1px solid {BORDER_BRIGHT}; border-radius: 6px;
        }}
        [data-testid="stTextInput"] input:focus {{ border-color: {ACCENT}; }}
        [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {{ background: {ACCENT}; }}

        /* ---- Dividers ---- */
        hr {{ border-color: {BORDER}; margin: 1.3rem 0; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
