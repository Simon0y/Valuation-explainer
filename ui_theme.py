"""Terminal theme for the Streamlit frontend.

This module owns the *visual language* only — a dark, institutional "terminal" skin
(near-black background, hairline-bordered tiles, monospaced tabular figures, a single
amber accent reserved for headers and headline numbers). It contains NO finance math and
NO layout logic; it just exposes the shared palette and one `inject_css()` entry point.

Charts (in `ui.py`) import the palette below so the plots match the page.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------------------
# Terminal palette — single source of truth (charts import these too)
# --------------------------------------------------------------------------------------
BG = "#0a0e14"            # app background — near-black
PANEL = "#11161f"         # tiles, cards, sidebar surface
PANEL_ALT = "#161c27"     # hover / alternating rows
BORDER = "#232b38"        # 1px hairline borders / dividers
BORDER_BRIGHT = "#2d3645" # slightly stronger rule (table header underline)
TEXT = "#c9d3df"          # primary text
TEXT_BRIGHT = "#e6edf3"   # headline numbers
MUTED = "#7d8794"         # labels, captions, axis ticks
ACCENT = "#e8a33d"        # single accent — headers, active tab, key totals (amber)
ACCENT_DEEP = "#c9882c"   # accent hover / pressed
GREEN = "#3fb950"         # positive delta only
RED = "#f85149"           # negative delta only
GRID = "#1b2230"          # faint chart gridlines

MONO = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def inject_css() -> None:
    """Inject the dark terminal skin. Idempotent; call once after set_page_config."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

        /* ---- Base ---- */
        .stApp {{ background: {BG}; }}
        html, body, .stApp, [class*="css"] {{
            font-family: {SANS};
            color: {TEXT};
        }}
        body {{ font-feature-settings: "tnum" 1, "lnum" 1; }}
        .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1240px; }}

        /* ---- Headers: the single accent ---- */
        h1 {{ font-weight: 700; letter-spacing: 0.01em; color: {ACCENT};
              font-size: 1.55rem; text-transform: uppercase; }}
        h2 {{ font-weight: 600; letter-spacing: 0.02em; color: {ACCENT};
              font-size: 1.05rem; text-transform: uppercase; margin-top: 0.4rem; }}
        h3 {{ font-weight: 600; letter-spacing: 0.02em; color: {TEXT_BRIGHT};
              font-size: 0.95rem; }}
        [data-testid="stCaptionContainer"], .stCaption, small {{ color: {MUTED}; }}
        a, a:visited {{ color: {ACCENT}; }}

        /* ---- Metric tiles: compact terminal cell ---- */
        [data-testid="stMetric"] {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 3px;
            padding: 10px 14px;
            box-shadow: none;
        }}
        [data-testid="stMetricLabel"] p {{
            color: {MUTED}; font-size: 0.66rem; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.09em;
        }}
        [data-testid="stMetricValue"] {{
            font-family: {MONO};
            font-variant-numeric: tabular-nums;
            font-weight: 600; color: {TEXT_BRIGHT}; font-size: 1.45rem;
            letter-spacing: -0.01em;
        }}
        [data-testid="stMetricDelta"] {{
            font-family: {MONO}; font-variant-numeric: tabular-nums;
            font-weight: 500; font-size: 0.78rem;
        }}
        [data-testid="stMetricDelta"] svg {{ display: none; }}   /* drop arrow glyph */

        /* ---- Tables: thin rules, mono right-aligned figures ---- */
        [data-testid="stTable"] {{ overflow-x: auto; }}
        [data-testid="stTable"] table {{
            border-collapse: collapse; width: 100%; font-size: 0.83rem;
            background: {PANEL}; border: 1px solid {BORDER};
        }}
        [data-testid="stTable"] thead th {{
            background: {PANEL_ALT}; color: {ACCENT};
            font-weight: 600; font-size: 0.66rem; text-transform: uppercase;
            letter-spacing: 0.06em; text-align: right;
            border-bottom: 1px solid {BORDER_BRIGHT}; padding: 9px 16px; white-space: nowrap;
        }}
        [data-testid="stTable"] thead th:first-child {{ text-align: left; }}
        [data-testid="stTable"] tbody th {{
            text-align: left; font-weight: 500; color: {TEXT};
            padding: 7px 16px; border-bottom: 1px solid {BORDER}; white-space: nowrap;
        }}
        [data-testid="stTable"] tbody td {{
            font-family: {MONO}; font-variant-numeric: tabular-nums;
            text-align: right; color: {TEXT_BRIGHT};
            padding: 7px 16px; border-bottom: 1px solid {BORDER}; white-space: nowrap;
        }}
        [data-testid="stTable"] tbody tr:last-child th,
        [data-testid="stTable"] tbody tr:last-child td {{ border-bottom: none; }}
        [data-testid="stTable"] tbody tr:hover td,
        [data-testid="stTable"] tbody tr:hover th {{ background: {PANEL_ALT}; }}

        /* ---- Tabs: minimal, amber active ---- */
        [data-testid="stTabs"] [data-baseweb="tab-list"] {{
            gap: 0.2rem; border-bottom: 1px solid {BORDER};
        }}
        [data-testid="stTabs"] button[role="tab"] {{
            font-weight: 600; color: {MUTED}; padding: 0.45rem 1.0rem;
            font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;
        }}
        [data-testid="stTabs"] button[role="tab"]:hover {{ color: {TEXT_BRIGHT}; }}
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{ color: {ACCENT}; }}
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; }}
        [data-testid="stTabs"] [data-baseweb="tab-border"] {{ background-color: {BORDER}; }}

        /* ---- Glossary chips (popover triggers) ---- */
        div[data-testid="stPopover"] > button {{
            border-radius: 3px; border: 1px solid {BORDER_BRIGHT}; background: {PANEL};
            color: {ACCENT}; padding: 0.12rem 0.6rem; font-size: 0.74rem; font-weight: 500;
            box-shadow: none;
        }}
        div[data-testid="stPopover"] > button:hover {{
            border-color: {ACCENT}; background: {PANEL_ALT}; color: {TEXT_BRIGHT};
        }}

        /* ---- Expanders ---- */
        [data-testid="stExpander"] details {{
            border: 1px solid {BORDER}; border-radius: 3px; background: {PANEL};
        }}
        [data-testid="stExpander"] summary {{ font-weight: 600; color: {TEXT_BRIGHT}; }}
        [data-testid="stExpander"] summary:hover {{ color: {ACCENT}; }}

        /* ---- Buttons: amber primary, square-ish ---- */
        [data-testid="stBaseButton-primary"] {{
            border-radius: 3px; font-weight: 600; color: {BG};
            background: {ACCENT}; border: 1px solid {ACCENT};
        }}
        [data-testid="stBaseButton-primary"]:hover {{
            background: {ACCENT_DEEP}; border-color: {ACCENT_DEEP}; color: {BG};
        }}

        /* ---- Alerts: hairline panels, no consumer pastel ---- */
        [data-testid="stAlert"] {{
            border-radius: 3px; border: 1px solid {BORDER}; background: {PANEL};
            color: {TEXT};
        }}

        /* ---- Sidebar: panel surface + hairline ---- */
        [data-testid="stSidebar"] {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
        [data-testid="stSidebar"] h2 {{ font-size: 0.82rem; }}
        [data-testid="stSidebar"] h3 {{ font-size: 0.78rem; color: {ACCENT};
            text-transform: uppercase; letter-spacing: 0.06em; }}

        /* ---- Inputs ---- */
        [data-testid="stTextInput"] input {{
            font-family: {MONO}; background: {BG}; color: {TEXT_BRIGHT};
            border: 1px solid {BORDER}; border-radius: 3px;
        }}
        [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {{ background: {ACCENT}; }}

        /* ---- Dividers ---- */
        hr {{ border-color: {BORDER}; margin: 1.1rem 0; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
