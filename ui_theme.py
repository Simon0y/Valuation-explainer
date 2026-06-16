"""Light institutional theme for the Streamlit frontend.

This module owns the *visual language* only — a clean, restrained, asset-manager-inspired
skin (white / off-white surfaces, near-black text, hairline-bordered flat cards, a single
muted-navy accent reserved for active states, links and headline numbers, and a clean
sans-serif (Inter) typeface throughout with right-aligned tabular figures). It contains NO
finance math and NO layout logic; it just exposes the shared palette and one `inject_css()`
entry point.

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

# One clean sans-serif throughout (Inter) — a modern, institutional dashboard look. Inter is
# pulled from Google Fonts in inject_css(); the stack degrades to IBM Plex Sans / system-ui.
SANS = "'Inter', 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
NUM = SANS  # chart number labels share the sans; HTML numbers get tabular-nums via CSS


def inject_css() -> None:
    """Inject the light institutional skin. Idempotent; call once after set_page_config."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        /* ---- Base: Inter sans-serif throughout, comfortable reading measure ---- */
        .stApp {{ background: {BG}; }}
        /* Set the sans at the root + on emotion-class wrappers so it inherits everywhere. */
        html, body, .stApp, [class*="css"], [class*="st-"] {{
            font-family: {SANS};
            color: {TEXT};
        }}
        html, body, .stApp {{ font-size: 16px; }}
        body {{ font-feature-settings: "tnum" 1, "lnum" 1; line-height: 1.5; }}
        /* Streamlit sets an explicit heading font with high specificity; override it. */
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{
            font-family: {SANS} !important;
        }}
        /* Keep Material icon glyphs on their ligature font, never let the serif leak in,
           or icons render as raw text (e.g. "keyboard_double_arrow_right"). */
        [data-testid="stIconMaterial"] {{
            font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
        }}
        .block-container {{ padding-top: 2.4rem; padding-bottom: 3.5rem; max-width: 1180px; }}

        /* ---- Headers: near-black, restrained sans (no tight tracking) ---- */
        /* Restrained page title; tighten the gap to the caption beneath it. */
        h1 {{ font-weight: 700; letter-spacing: -0.01em; color: {TEXT_BRIGHT};
              font-size: 1.45rem; line-height: 1.2; margin: 0 0 0.15rem; padding-bottom: 0; }}
        /* The page-title caption sits directly under h1, pull it up snug. */
        h1 + div [data-testid="stCaptionContainer"],
        [data-testid="stHeading"] + div [data-testid="stCaptionContainer"] {{ margin-top: -0.1rem; }}
        h2 {{ font-weight: 700; letter-spacing: 0; color: {TEXT_BRIGHT};
              font-size: 1.3rem; margin-top: 0.6rem; }}
        h3 {{ font-weight: 700; letter-spacing: 0; color: {TEXT_BRIGHT};
              font-size: 1.05rem; }}
        [data-testid="stCaptionContainer"], .stCaption, small {{ color: {MUTED}; }}
        a, a:visited {{ color: {ACCENT}; text-decoration: none; }}
        a:hover {{ color: {ACCENT_DEEP}; text-decoration: underline; }}

        /* ---- Metric tiles: flat card, subtle border, no shadow, equal height ---- */
        /* Make the column wrapper stretch so sibling cards share a row height. */
        [data-testid="stColumn"] {{ display: flex; flex-direction: column; }}
        [data-testid="stColumn"] > div,
        [data-testid="stColumn"] [data-testid="stVerticalBlock"] {{ height: 100%; }}
        [data-testid="stMetric"] {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 14px 18px;
            box-shadow: none;
            height: 100%;
            display: flex; flex-direction: column; justify-content: space-between;
        }}
        [data-testid="stMetricLabel"] {{ width: 100%; }}
        [data-testid="stMetricLabel"] p {{
            color: {MUTED}; font-size: 0.74rem; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.06em;
        }}
        /* Let the value wrap and shrink-to-fit so long text (e.g. an industry name) is
           never clipped to "Consumer Elec…". clamp() auto-sizes between 0.95rem and 1.4rem. */
        [data-testid="stMetricValue"] {{
            font-variant-numeric: tabular-nums;
            font-weight: 700; color: {TEXT_BRIGHT};
            font-size: clamp(0.95rem, 1.4vw + 0.6rem, 1.4rem);
            line-height: 1.2; letter-spacing: 0;
            white-space: normal; overflow-wrap: anywhere; text-align: right;
        }}
        [data-testid="stMetricValue"] > div {{ width: 100%; text-align: right; }}
        /* The value text lives in an inner markdown container that Streamlit clips with
           nowrap+ellipsis, so unclip it and the full label wraps instead of becoming "…". */
        [data-testid="stMetricValue"] [data-testid="stMarkdownContainer"],
        [data-testid="stMetricValue"] [data-testid="stMarkdownContainer"] p {{
            white-space: normal !important; overflow: visible !important;
            text-overflow: clip !important; text-align: right; margin: 0;
        }}
        [data-testid="stMetricDelta"] {{
            font-variant-numeric: tabular-nums;
            font-weight: 400; font-size: 0.9rem; text-align: right;
            justify-content: flex-end;
        }}
        [data-testid="stMetricDelta"] svg {{ display: none; }}   /* drop arrow glyph */

        /* ---- Tables: thin rules, right-aligned tabular figures ---- */
        [data-testid="stTable"] {{ overflow-x: auto; }}
        [data-testid="stTable"] table {{
            border-collapse: collapse; width: 100%; font-size: 0.95rem;
            background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
        }}
        [data-testid="stTable"] thead th {{
            background: {PANEL_ALT}; color: {MUTED};
            font-weight: 700; font-size: 0.74rem; text-transform: uppercase;
            letter-spacing: 0.05em; text-align: right;
            border-bottom: 1px solid {BORDER_BRIGHT}; padding: 10px 16px; white-space: nowrap;
        }}
        [data-testid="stTable"] thead th:first-child {{ text-align: left; }}
        [data-testid="stTable"] tbody th {{
            text-align: left; font-weight: 700; color: {TEXT};
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
            font-weight: 400; color: {MUTED}; padding: 0.5rem 1.05rem;
            font-size: 1.0rem; letter-spacing: 0;
        }}
        [data-testid="stTabs"] button[role="tab"]:hover {{ color: {TEXT_BRIGHT}; }}
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
            color: {ACCENT}; font-weight: 700;
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

        /* ---- Alerts: hairline panels, restrained, compact padding ---- */
        [data-testid="stAlert"] {{
            border-radius: 6px; border: 1px solid {BORDER}; background: {PANEL};
            color: {TEXT};
        }}
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {{
            font-size: 0.86rem; line-height: 1.4; margin: 0;
        }}
        /* The sidebar "FMP API key loaded" box was bulky, so trim its padding. */
        [data-testid="stSidebar"] [data-testid="stAlert"] {{ padding: 0.55rem 0.75rem; }}

        /* ---- Sidebar: white surface + hairline, even control spacing ---- */
        [data-testid="stSidebar"] {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: 1.5rem; }}
        [data-testid="stSidebar"] h2 {{ font-size: 1.05rem; }}
        [data-testid="stSidebar"] h3 {{ font-size: 0.82rem; color: {MUTED};
            text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }}
        /* Even, predictable vertical rhythm between every sidebar control. */
        [data-testid="stSidebar"] [data-testid="stElementContainer"] {{ margin-bottom: 0.35rem; }}
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] label,
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
            font-size: 0.85rem; font-weight: 500; line-height: 1.3;
        }}
        /* Keep widget labels on a tidy line rather than breaking mid-phrase. */
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{ overflow-wrap: normal; }}
        [data-testid="stSidebar"] hr {{ margin: 0.85rem 0; }}

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
