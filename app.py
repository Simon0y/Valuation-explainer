"""Valuation Explainer — Streamlit UI (institutional "terminal" layout).

Enter a public-company ticker, see what it does and its real financials, then learn DCF and
LBO valuation interactively — with every piece of jargon explained in plain language.

This file is the ONLY place Streamlit is imported. It contains NO finance math: it reads
the API key, calls the `data/` layer, drives the pure `engine/`, and renders results.
The terminal skin lives in `ui_theme.py`; charts and glossary popovers in `ui.py`.

Layout: global inputs (ticker + DCF assumption sliders) live in the sidebar; the body is a
set of tabs — Overview · Valuation · Risk · AI Insights · Peers. Each tab has its own
`render_*_tab()` function so future features (Risk, AI Insights, Peers) have a clear home.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import date

import pandas as pd
import streamlit as st

import ui
import ui_theme
from content.report import ReportData, build_markdown, build_pdf
from data.fmp_client import (
    FMPAuthError,
    FMPClient,
    FMPError,
    FMPNotFound,
    FMPPlanError,
    FMPRateLimitError,
)
from data.fundamentals import fetch_financials, fetch_profile
from data.news import fetch_recent_headlines
from data.peers import PE_LABEL, PeerComparison, build_peer_comparison
from data.prices import fetch_price_history
from ai_thesis import (
    AIError,
    AIKeyError,
    AIRateLimitError,
    ThesisContext,
    generate_ai_thesis,
)
from engine.defaults import (
    default_dcf_assumptions,
    default_lbo_assumptions,
    default_wacc,
)
from engine.dcf import run_dcf
from engine.lbo import run_lbo
from engine.models import CompanyFinancials
from engine.montecarlo import run_price_risk

st.set_page_config(page_title="Valuation Explainer", page_icon="▪", layout="wide")
ui_theme.inject_css()


# --------------------------------------------------------------------------------------
# API key resolution: st.secrets -> env var -> .env. Passed into the client; never stored.
# --------------------------------------------------------------------------------------
def _read_dotenv(path: str = ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def resolve_api_key() -> str | None:
    try:
        if "FMP_API_KEY" in st.secrets:
            return st.secrets["FMP_API_KEY"]
    except Exception:
        pass
    if os.environ.get("FMP_API_KEY"):
        return os.environ["FMP_API_KEY"]
    return _read_dotenv().get("FMP_API_KEY")


def resolve_gemini_key() -> str | None:
    """Resolve the Gemini API key: st.secrets -> env var -> .env. Never hardcoded; the
    real key lives only in the gitignored secrets file / environment."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    return _read_dotenv().get("GEMINI_API_KEY")


@st.cache_data(show_spinner=False)
def load_financials(api_key: str, symbol: str, limit: int) -> CompanyFinancials:
    client = FMPClient(api_key)
    return fetch_financials(client, symbol, limit=limit)


# Each peer costs 2 FMP calls (trailing P/E + revenue growth), so a tight cap keeps a single
# load well under the free-tier budget. One load ≈ 1 (profile) + 2 (target) + 1 (peer
# discovery) + 2×peers calls — i.e. ~20 calls at 8 peers, down from ~28 at the old 12.
_MAX_PEERS = 8


# Hard cache: a 24h TTL means repeated views of the same ticker (across reruns and tab
# switches) cost ZERO further FMP calls — a few page views can't exhaust the daily quota.
@st.cache_data(show_spinner=False, ttl=24 * 3600, max_entries=64)
def load_peer_comparison(api_key: str, symbol: str) -> PeerComparison:
    """Cached peer pull (target + up to ``_MAX_PEERS`` peers with P/E, revenue growth, cap)."""
    client = FMPClient(api_key)
    profile = fetch_profile(client, symbol)
    return build_peer_comparison(client, symbol, profile, max_peers=_MAX_PEERS)


# Hard 24h cache: the Risk tab's ONE FMP dependency is this single price-history pull, so a
# day of reruns/tab-switches costs at most one call per ticker. Returns closes oldest→newest.
@st.cache_data(show_spinner=False, ttl=24 * 3600, max_entries=64)
def load_price_history(api_key: str, symbol: str) -> list[float]:
    """Cached daily close series (~3y) for the Monte Carlo price-risk engine."""
    client = FMPClient(api_key)
    return fetch_price_history(client, symbol)


# News is optional flavour for the AI thesis; cache it hard so a day of reruns/regenerations
# costs at most one extra FMP call. Returns [] on any provider error (fetcher is fail-soft).
@st.cache_data(show_spinner=False, ttl=24 * 3600, max_entries=64)
def load_recent_headlines(api_key: str, symbol: str) -> list[str]:
    """Cached recent headlines for ``symbol`` (best-effort; [] if unavailable)."""
    client = FMPClient(api_key)
    return fetch_recent_headlines(client, symbol, limit=5)


# --------------------------------------------------------------------------------------
# Formatting helpers (display only)
# --------------------------------------------------------------------------------------
def fmt_money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}"


def fmt_compact(value: float | None) -> str:
    if value is None:
        return "—"
    a = abs(value)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{value/div:,.1f}{suffix}"
    return f"{value:,.0f}"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def seed(key: str, value) -> None:
    """Seed a session_state slider value once, so a tab can read it (e.g. for a headline
    number) regardless of where the slider widget is physically rendered on the page."""
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------------------------------------------
# Stage 1 table — net debt here uses the SAME definition as the valuation equity bridge
# (total debt − cash & ST investments), not FMP's netDebt field.
# --------------------------------------------------------------------------------------
TABLE_ROWS: list[tuple[str, str]] = [
    ("Revenue", "revenue"),
    ("EBIT (operating income)", "ebit"),
    ("EBITDA", "ebitda"),
    ("D&A", "depreciation_amortization"),
    ("Capex (negative = outflow)", "capex"),
    ("Δ Working capital (CF sign)", "change_in_working_capital"),
    ("Total debt", "total_debt"),
    ("Cash & ST investments", "cash_and_st_investments"),
    ("Long-term investments", "long_term_investments"),
    ("Net debt  (= total debt − cash & ST inv)", "_net_debt_bridge"),
    ("Shares outstanding (diluted)", "shares_outstanding"),
]


def financials_table(fin: CompanyFinancials) -> pd.DataFrame:
    columns = [y.fiscal_year for y in fin.years]
    data: dict[str, list[str]] = {}
    for label, attr in TABLE_ROWS:
        row: list[str] = []
        for year in fin.years:
            if attr == "_net_debt_bridge":
                row.append(fmt_money(year.net_debt_for_bridge(False)))
            else:
                row.append(fmt_money(getattr(year, attr)))
        data[label] = row
    return pd.DataFrame(data, index=columns).T


# Slider state reset when the loaded company changes.
SLIDER_KEYS = [
    "dcf_wacc", "dcf_tg", "dcf_growth", "dcf_margin",
    "lbo_entry", "lbo_exit", "lbo_lev", "lbo_hold",
]

# Ticker format: letters, digits, dots and hyphens (covers BRK.B, SAP.DE, RDS-A).
TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


# ======================================================================================
# Sidebar — global inputs (ticker + DCF assumption sliders)
# ======================================================================================
def render_sidebar_setup(api_key: str | None) -> tuple[str, int, bool, bool]:
    """Render the top of the sidebar (data inputs) and return (symbol, years, lt_inv, go)."""
    with st.sidebar:
        st.header("Setup")
        if api_key:
            st.success("FMP API key loaded.")
        else:
            st.error(
                "No FMP API key found. Add it to `.streamlit/secrets.toml` "
                "(see `secrets.toml.example`) or set the `FMP_API_KEY` environment variable."
            )
        symbol = (
            st.text_input("Ticker", value="AAPL", help="e.g. AAPL, MSFT, NVDA")
            .strip()
            .upper()
        )
        years_to_load = st.slider(
            "Years of history", min_value=1, max_value=10, value=10,
            help=(
                "Requests up to this many years of annual statements. The API may return "
                "fewer (the free FMP tier often caps at ~5); only the years actually returned "
                "are shown — never padded or fabricated."
            ),
        )
        go = st.button("Load company", type="primary", disabled=not api_key)

        st.divider()
        st.subheader("Net debt definition")
        include_lt_inv = st.toggle(
            "Include long-term investments",
            value=False,
            help=(
                "Net debt = total debt − cash & short-term investments. The conventional "
                "definition EXCLUDES long-term marketable securities, which understates the "
                "cash of cash-rich firms (e.g. Apple). Turning this on subtracts long-term "
                "investments too, lowering net debt and RAISING equity value. Applies to the "
                "DCF equity bridge."
            ),
        )
    return symbol, years_to_load, include_lt_inv, go


def render_sidebar_dcf_controls(
    fin: CompanyFinancials, wacc_result, include_lt_inv: bool
) -> bool:
    """Seed and render the DCF assumption sliders in the sidebar (global inputs).

    Returns True if the DCF inputs are available (the Valuation tab reads the seeded
    session_state values). Values are seeded from this company's own history, then yours
    to adjust; the Valuation tab rebuilds the assumptions from session_state and recomputes.
    """
    with st.sidebar:
        st.divider()
        st.subheader("DCF assumptions")

        if wacc_result is None:
            st.caption(
                "A CAPM WACC needs a market cap — unavailable for this ticker, so the DCF "
                "sliders are hidden. (The LBO in the Valuation tab still works.)"
            )
            return False

        seed_assumptions = default_dcf_assumptions(
            fin, wacc=wacc_result.wacc, include_long_term_investments=include_lt_inv
        )
        if seed_assumptions is None:
            st.caption(
                "Not enough data to build a DCF (need revenue, EBIT, D&A, capex and shares)."
            )
            return False

        # Seed slider state once (clamped into the slider ranges).
        seed("dcf_wacc", round(_clamp(wacc_result.wacc, 0.03, 0.20), 4))
        seed("dcf_tg", round(_clamp(seed_assumptions.terminal_growth, 0.0, 0.05), 4))
        seed("dcf_growth", round(_clamp(seed_assumptions.revenue_growth, -0.10, 0.40), 4))
        seed("dcf_margin", round(_clamp(seed_assumptions.ebit_margin, 0.0, 0.60), 4))

        st.slider("WACC (discount rate)", 0.03, 0.20, step=0.0025,
                  format="%.4f", key="dcf_wacc",
                  help="Higher WACC → lower value. Seeded from CAPM.")
        st.slider("Terminal growth (g∞)", 0.0, 0.05, step=0.0025,
                  format="%.4f", key="dcf_tg",
                  help="Perpetual growth after the forecast. Must be < WACC.")
        st.slider("Revenue growth / yr", -0.10, 0.40, step=0.005,
                  format="%.3f", key="dcf_growth")
        st.slider("EBIT margin", 0.0, 0.60, step=0.005,
                  format="%.3f", key="dcf_margin")
        st.caption(
            "WACC and terminal growth are decimals (e.g. 0.0900 = 9.00%). Seeded from this "
            "company's history; move a slider and the Valuation tab updates live."
        )
    return True


def render_sidebar_footer() -> None:
    with st.sidebar:
        st.divider()
        st.caption(
            "**Educational use only — not investment advice.** Data may be delayed or "
            "incomplete; valuations are illustrative and depend entirely on the assumptions "
            "you set."
        )


# ======================================================================================
# Tab: Overview — company profile, key financials, current price/metrics
# ======================================================================================
def render_overview_tab(
    fin: CompanyFinancials, years_to_load: int
) -> None:
    profile = fin.profile
    latest = fin.latest
    cur = latest.reported_currency

    st.subheader(f"{profile.name}  ·  {profile.symbol}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sector", profile.sector)
    c2.metric("Industry", profile.industry)
    c3.metric(f"Market cap ({cur})", fmt_compact(profile.market_cap))
    c4.metric("Beta", "—" if profile.beta is None else f"{profile.beta:.2f}")

    # Current price tile (when available) — a terminal-style quote row.
    if profile.price is not None and profile.price > 0:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric(f"Price ({cur})", f"{profile.price:,.2f}")
        p2.metric(f"Latest revenue ({cur})", fmt_compact(latest.revenue))
        p3.metric(f"Latest EBITDA ({cur})", fmt_compact(latest.ebitda))
        p4.metric("Net debt (bridge)", fmt_compact(latest.net_debt_for_bridge(False)))

    if profile.description:
        with st.expander("What does this company do?", expanded=True):
            st.write(profile.description)
            if profile.website:
                st.caption(f"Website: {profile.website}")

    st.divider()

    st.subheader("Key financials")
    n_years = len(fin.years)
    if n_years < years_to_load:
        st.caption(
            f"Showing **{n_years}** year(s) — requested {years_to_load}, but the API "
            "returned fewer (common on the free FMP tier). Only the years actually returned "
            "are shown; nothing is padded or fabricated."
        )
    else:
        st.caption(f"Showing **{n_years}** year(s) of annual history.")
    st.caption(
        f"Reporting currency: **{cur}**. Figures are exactly as reported by the API (absolute "
        "units, newest year first). Capex is shown **negative** (a cash outflow); Δ working "
        "capital uses the **cash-flow-statement** sign (positive = working capital released "
        "cash)."
    )
    st.table(financials_table(fin))
    st.info(
        "**Net debt definition (consistent everywhere):** this app uses **total debt − cash & "
        "short-term investments** — the same figure the DCF equity bridge uses. FMP's own "
        "`netDebt` field subtracts only *cash & equivalents* (not short-term investments), so "
        "it can differ by tens of billions for cash-rich firms; we deliberately don't use it. "
        "Turning on *Include long-term investments* (sidebar) subtracts those too in the bridge.",
    )


# ======================================================================================
# Tab: Valuation — interactive DCF + LBO (the existing walkthroughs, charts, sliders)
# ======================================================================================
def render_valuation_tab(
    fin: CompanyFinancials, include_lt_inv: bool, wacc_result, dcf_ready: bool
) -> None:
    cur = fin.latest.reported_currency
    profile = fin.profile

    st.subheader("Value it yourself")
    st.caption(
        "Assumptions are **seeded from this company's own history** as a starting point, then "
        "yours to adjust. DCF assumption sliders live in the **sidebar**; lead with the "
        "headline number, then expand the steps to see every intermediate calculation."
    )

    tab_dcf, tab_lbo = st.tabs(["DCF", "LBO"])
    with tab_dcf:
        _render_dcf(fin, profile, cur, include_lt_inv, wacc_result, dcf_ready)
    with tab_lbo:
        _render_lbo(fin, cur)


# ----------------------------------------------------------------------------- DCF
def _render_dcf(
    fin: CompanyFinancials, profile, cur: str, include_lt_inv: bool, wacc_result, dcf_ready: bool
) -> None:
    if wacc_result is None:
        st.info(
            "Can't compute a CAPM WACC without a market cap, so the DCF is unavailable. "
            "(The LBO tab still works.)"
        )
        return
    if not dcf_ready:
        st.warning(
            "Not enough data to build a DCF (need revenue, EBIT, D&A, capex and shares)."
        )
        return

    # Read the (possibly user-adjusted) slider values seeded into the sidebar.
    wacc_v = st.session_state["dcf_wacc"]
    tg_v = st.session_state["dcf_tg"]
    growth_v = st.session_state["dcf_growth"]
    margin_v = st.session_state["dcf_margin"]

    # Rebuild assumptions from those values. The net-debt toggle flows through
    # default_dcf_assumptions' equity-bridge net debt.
    base = default_dcf_assumptions(
        fin, wacc=wacc_v, include_long_term_investments=include_lt_inv,
        terminal_growth=tg_v,
    )
    dcf_assumptions = replace(base, revenue_growth=growth_v, ebit_margin=margin_v)

    try:
        dcf = run_dcf(dcf_assumptions)
    except ValueError as exc:
        st.error(str(exc))
        st.caption("Adjust the DCF assumption sliders in the sidebar to fix this combination.")
        return

    # ---- Headline (progressive disclosure: number first) ----
    m1, m2, m3 = st.columns(3)
    if profile.price is not None and profile.price > 0:
        upside = dcf.value_per_share / profile.price - 1.0
        m1.metric(
            f"DCF value / share ({cur})",
            f"{dcf.value_per_share:,.2f}",
            delta=f"{upside:+.1%} vs market {profile.price:,.2f}",
        )
    else:
        m1.metric(f"DCF value / share ({cur})", f"{dcf.value_per_share:,.2f}")
    m2.metric(f"Enterprise value ({cur})", fmt_compact(dcf.enterprise_value))
    m3.metric(f"Equity value ({cur})", fmt_compact(dcf.equity_value))

    # Snapshot the already-computed DCF for the Export feature (Stage 6). This only records
    # values for packaging; it does not change the valuation or this tab's behavior.
    st.session_state["_report_valuation"] = {
        "value_per_share": dcf.value_per_share,
        "upside": (dcf.value_per_share / profile.price - 1.0)
        if (profile.price and profile.price > 0) else None,
        "enterprise_value": dcf.enterprise_value,
        "equity_value": dcf.equity_value,
        "wacc": dcf.assumptions.wacc,
        "terminal_growth": dcf.assumptions.terminal_growth,
    }

    st.plotly_chart(ui.dcf_waterfall(dcf, cur), use_container_width=True)

    ui.term_row(["fcff", "wacc", "terminal_value", "ev", "net_debt"])

    # ---- Sensitivity matrix (recomputes the same DCF across a WACC × g∞ grid) ----
    render_sensitivity_matrix(fin, include_lt_inv, wacc_v, tg_v, growth_v, margin_v, cur)

    # ---- Step-by-step walkthrough ----
    with st.expander("Step-by-step walkthrough"):
        st.markdown(
            "**Step 1 — Forecast unlevered free cash flow (FCFF) for each year.**  \n"
            "For every year: `FCFF = EBIT×(1−tax) + D&A − Capex − ΔNWC`."
        )
        fc_rows = {
            "Revenue": [], "EBIT": [], "NOPAT  EBIT×(1−tax)": [],
            "D&A": [], "Capex": [], "ΔNWC": [], "FCFF": [],
            "Discount factor": [], "PV of FCFF": [],
        }
        cols = []
        for y in dcf.years:
            cols.append(f"Year {y.year}")
            fc_rows["Revenue"].append(fmt_money(y.revenue))
            fc_rows["EBIT"].append(fmt_money(y.ebit))
            fc_rows["NOPAT  EBIT×(1−tax)"].append(fmt_money(y.nopat))
            fc_rows["D&A"].append(fmt_money(y.depreciation_amortization))
            fc_rows["Capex"].append(fmt_money(-y.capex))  # show as outflow
            fc_rows["ΔNWC"].append(fmt_money(-y.change_in_nwc))
            fc_rows["FCFF"].append(fmt_money(y.fcff))
            fc_rows["Discount factor"].append(f"{y.discount_factor:.4f}")
            fc_rows["PV of FCFF"].append(fmt_money(y.pv_fcff))
        st.table(pd.DataFrame(fc_rows, index=cols).T)
        st.caption(
            "Capex and ΔNWC are shown as the cash outflows the engine subtracts."
        )

        a = dcf_assumptions
        st.markdown(
            f"**Step 2 — Terminal value (Gordon growth).**  \n"
            f"`TV = FCFF₍last₎ × (1+g) / (WACC − g)` "
            f"= {fmt_money(dcf.years[-1].fcff)} × (1+{a.terminal_growth:.2%}) / "
            f"({a.wacc:.2%} − {a.terminal_growth:.2%}) = **{fmt_money(dcf.terminal_value)} {cur}**.  \n"
            f"Discounted back {a.forecast_years} years → "
            f"PV(TV) = **{fmt_money(dcf.pv_terminal_value)} {cur}**."
        )
        st.markdown(
            "**Step 3 — Bridge to equity value per share.**"
        )
        bridge = pd.DataFrame(
            {
                "Value": [
                    fmt_money(dcf.sum_pv_fcff),
                    fmt_money(dcf.pv_terminal_value),
                    fmt_money(dcf.enterprise_value),
                    fmt_money(-dcf.net_debt),
                    fmt_money(dcf.equity_value),
                    f"{dcf.shares_outstanding:,.0f}",
                    f"{dcf.value_per_share:,.2f}",
                ]
            },
            index=[
                "Σ PV of forecast FCFF",
                "+ PV of terminal value",
                "= Enterprise value",
                "− Net debt",
                "= Equity value",
                "÷ Shares outstanding",
                "= Value per share",
            ],
        )
        st.table(bridge)
        ui.term_row(
            ["capm", "beta", "erp", "nopat", "gordon_growth", "discount_factor"],
            label="More terms from these steps:",
        )


# ---- Sensitivity matrix --------------------------------------------------------------
# Grid geometry: WACC ±2pp over 7 steps (x), terminal growth ±1pp over 5 steps (y),
# centered on the current sidebar values (odd step counts ⇒ the center cell is the base).
SENS_WACC_HALF, SENS_WACC_STEPS = 0.02, 7
SENS_TG_HALF, SENS_TG_STEPS = 0.01, 5


def _linspace(center: float, half: float, steps: int) -> list[float]:
    """Evenly spaced values on [center−half, center+half]. With an odd `steps`, the
    middle element is exactly `center` (so the base-case cell matches the live DCF)."""
    if steps == 1:
        return [center]
    step = (2.0 * half) / (steps - 1)
    return [center - half + step * i for i in range(steps)]


def _argmin_close(axis: list[float], target: float) -> int:
    return min(range(len(axis)), key=lambda i: abs(axis[i] - target))


def render_sensitivity_matrix(
    fin: CompanyFinancials,
    include_lt_inv: bool,
    wacc_v: float,
    tg_v: float,
    growth_v: float,
    margin_v: float,
    cur: str,
) -> None:
    """Recompute fair value / share across a WACC × terminal-growth grid by calling the
    EXISTING DCF engine per cell — only WACC and terminal growth vary; revenue growth,
    EBIT margin, the net-debt toggle and everything else are held at the sidebar values.
    Cells where g∞ ≥ WACC are blanked (NaN): Gordon growth is undefined there."""
    wacc_axis = _linspace(wacc_v, SENS_WACC_HALF, SENS_WACC_STEPS)
    tg_axis = _linspace(tg_v, SENS_TG_HALF, SENS_TG_STEPS)

    # values[row=terminal growth][col=WACC]; NaN where the Gordon model is invalid.
    nan = float("nan")
    values: list[list[float]] = []
    for g in tg_axis:
        row: list[float] = []
        for w in wacc_axis:
            if g >= w:  # mirrors run_dcf's guard (wacc must exceed terminal growth)
                row.append(nan)
                continue
            cell_base = default_dcf_assumptions(
                fin, wacc=w, include_long_term_investments=include_lt_inv,
                terminal_growth=g,
            )
            cell = replace(cell_base, revenue_growth=growth_v, ebit_margin=margin_v)
            try:
                row.append(run_dcf(cell).value_per_share)
            except ValueError:
                row.append(nan)
        values.append(row)

    base_col = _argmin_close(wacc_axis, wacc_v)
    base_row = _argmin_close(tg_axis, tg_v)

    st.markdown("**Sensitivity — fair value / share**")
    st.caption(
        "How the DCF value/share moves as WACC (columns) and terminal growth (rows) vary "
        "around your sidebar inputs. The outlined cell is the base case; blank cells are "
        "where terminal growth ≥ WACC, which the Gordon model can't value."
    )
    st.plotly_chart(
        ui.sensitivity_heatmap(wacc_axis, tg_axis, values, base_col, base_row, cur),
        use_container_width=True,
    )


# ----------------------------------------------------------------------------- LBO
def _render_lbo(fin: CompanyFinancials, cur: str) -> None:
    seed_lbo = default_lbo_assumptions(fin)
    if seed_lbo is None:
        st.warning("Not enough data to build an LBO (need positive EBITDA and a market cap).")
        return

    entry_default = round(_clamp(seed_lbo.entry_ev_ebitda, 3.0, 30.0), 1)
    seed("lbo_entry", entry_default)
    seed("lbo_exit", entry_default)
    seed("lbo_lev", 5.0)
    seed("lbo_hold", 5)

    entry_v = st.session_state["lbo_entry"]
    exit_v = st.session_state["lbo_exit"]
    lev_v = st.session_state["lbo_lev"]
    hold_v = st.session_state["lbo_hold"]

    base_lbo = default_lbo_assumptions(fin, entry_leverage=lev_v, hold_years=int(hold_v))
    lbo_assumptions = replace(base_lbo, entry_ev_ebitda=entry_v, exit_ev_ebitda=exit_v)

    try:
        lbo = run_lbo(lbo_assumptions)
    except ValueError as exc:
        st.error(str(exc))
        lbo = None

    if lbo is not None:
        m1, m2, m3 = st.columns(3)
        m1.metric("IRR", f"{lbo.irr:.1%}")
        m2.metric("MOIC", f"{lbo.moic:.2f}×")
        m3.metric(f"Sponsor equity ({cur})", fmt_compact(lbo.sponsor_equity))

        st.plotly_chart(ui.lbo_debt_chart(lbo, cur), use_container_width=True)

        ui.term_row(["leverage", "cash_sweep", "moic", "irr", "ev_ebitda"])

    # ---- Adjust assumptions (always rendered, so a bad combo can be undone) ----
    with st.expander("Adjust assumptions", expanded=True):
        r1c1, r1c2 = st.columns(2)
        with r1c1:
            st.slider(
                "Entry EV/EBITDA (×)", 3.0, 30.0, step=0.5, key="lbo_entry",
                help=(
                    f"Purchase multiple. Today's market level ≈ "
                    f"{seed_lbo.entry_ev_ebitda:.1f}×. Lower it to a realistic "
                    "8–12× and watch IRR/MOIC rise."
                ),
            )
        with r1c2:
            st.slider("Exit EV/EBITDA (×)", 3.0, 30.0, step=0.5, key="lbo_exit",
                      help="Sale multiple at the end of the hold period.")
        r2c1, r2c2 = st.columns(2)
        with r2c1:
            st.slider("Entry leverage (× EBITDA)", 0.0, 8.0, step=0.25,
                      key="lbo_lev",
                      help="Opening debt as a multiple of entry EBITDA.")
        with r2c2:
            st.slider("Hold period (years)", 1, 10, step=1, key="lbo_hold")
        st.caption(
            "Interest, EBITDA growth and capex are seeded from history. If entry "
            "leverage exceeds the entry multiple, sponsor equity turns negative and "
            "the model flags it instead of producing a bogus return."
        )

    if lbo is not None:
        with st.expander("Step-by-step walkthrough"):
            st.markdown("**Step 1 — Sources & Uses** (they must balance).")
            su = lbo.sources_and_uses
            su_df = pd.DataFrame(
                {
                    "Uses": [
                        fmt_money(su["uses"]["purchase_enterprise_value"]),
                        fmt_money(su["uses"]["transaction_fees"]),
                        fmt_money(su["uses"]["total"]),
                    ],
                    "Sources": [
                        fmt_money(su["sources"]["debt"]),
                        fmt_money(su["sources"]["sponsor_equity"]),
                        fmt_money(su["sources"]["total"]),
                    ],
                },
                index=["Purchase EV / Debt", "Fees / Sponsor equity", "Total"],
            )
            st.table(su_df)

            st.markdown(
                "**Step 2 — Debt schedule with 100% cash sweep.**  \n"
                "Cash taxes are on `EBITDA − D&A − Interest`, so the **interest tax "
                "shield** is captured. Free cash flow then sweeps to pay down debt."
            )
            rows = {
                "EBITDA": [], "D&A": [], "Interest": [],
                "Taxable income  (EBITDA−D&A−Int)": [], "Cash taxes": [],
                "Capex": [], "FCF available": [], "Debt paydown": [],
                "Ending debt": [], "Cash balance": [],
            }
            cols = []
            for y in lbo.schedule:
                cols.append(f"Year {y.year}")
                rows["EBITDA"].append(fmt_money(y.ebitda))
                rows["D&A"].append(fmt_money(y.depreciation_amortization))
                rows["Interest"].append(fmt_money(y.interest))
                rows["Taxable income  (EBITDA−D&A−Int)"].append(fmt_money(y.taxable_income))
                rows["Cash taxes"].append(fmt_money(y.cash_taxes))
                rows["Capex"].append(fmt_money(y.capex))
                rows["FCF available"].append(fmt_money(y.fcf_available))
                rows["Debt paydown"].append(fmt_money(y.debt_paydown))
                rows["Ending debt"].append(fmt_money(y.ending_debt))
                rows["Cash balance"].append(fmt_money(y.cash_balance))
            st.table(pd.DataFrame(rows, index=cols).T)

            st.markdown(
                f"**Step 3 — Exit & returns.**  \n"
                f"Exit EV = exit multiple × exit EBITDA = {lbo_assumptions.exit_ev_ebitda:.1f}× × "
                f"{fmt_money(lbo.exit_ebitda)} = **{fmt_money(lbo.exit_enterprise_value)} {cur}**.  \n"
                f"Exit equity = Exit EV − exit net debt ({fmt_money(lbo.exit_net_debt)}) = "
                f"**{fmt_money(lbo.exit_equity_value)} {cur}**.  \n"
                f"MOIC = exit equity ÷ sponsor equity = "
                f"{fmt_money(lbo.exit_equity_value)} ÷ {fmt_money(lbo.sponsor_equity)} = "
                f"**{lbo.moic:.2f}×**.  \n"
                f"IRR = MOIC^(1/{lbo.hold_years}) − 1 = **{lbo.irr:.1%}**."
            )
            ui.term_row(
                ["sources_uses", "ev_ebitda", "cash_sweep"],
                label="More terms from these steps:",
            )


# ======================================================================================
# Tabs: Risk · AI Insights · Peers — placeholders (clear home for future features)
# ======================================================================================
def render_coming_soon(title: str, blurb: str, planned: list[str]) -> None:
    st.subheader(title)
    st.caption(blurb)
    st.info(f"**{title} — coming soon.** This panel is wired into the layout and awaits its engine.")
    st.markdown("**Planned:**")
    for item in planned:
        st.markdown(f"- {item}")


def render_risk_tab(api_key: str, fin: CompanyFinancials) -> None:
    """Render the Risk tab: a Monte Carlo (GBM) market-price-risk simulation.

    Fails soft at every step — a rate limit, missing data, or any unexpected error shows a
    clean in-tab message instead of crashing the app (same pattern as the Peers tab). This
    is market-price risk from historical volatility, SEPARATE from the DCF valuation."""
    profile = getattr(fin, "profile", None)
    sym = getattr(profile, "symbol", "") or "this company"
    currency = getattr(profile, "currency", "") or ""

    st.subheader("Risk")
    st.caption(
        "Monte Carlo **price risk** — 10,000 simulated 1-year price paths via Geometric "
        "Brownian Motion, with drift and volatility estimated from this stock's own daily "
        "history. This is **market-price risk**, separate from the DCF fundamental value."
    )

    try:
        with st.spinner(f"Loading price history for {sym}…"):
            prices = load_price_history(api_key, sym)
    except FMPRateLimitError:
        st.info("Price data unavailable (provider rate limit) — try again later.")
        return
    except (FMPAuthError, FMPPlanError, FMPNotFound, FMPError):
        st.warning("Price data unavailable for this ticker.")
        return
    except Exception:  # noqa: BLE001 — last-resort guard; the load can never crash the app
        st.warning("Price data unavailable right now.")
        return

    if not prices or len(prices) < 30:
        st.warning(
            "Not enough price history to estimate volatility for a meaningful simulation "
            "(need at least ~30 daily closes)."
        )
        return

    try:
        _render_price_risk(sym, currency, prices)
    except Exception:  # noqa: BLE001 — contain any rendering/sim error to the Risk tab
        st.warning("Couldn't run the price-risk simulation for this ticker.")


def _render_price_risk(sym: str, currency: str, prices: list[float]) -> None:
    res = run_price_risk(prices)  # current price defaults to the last close in the series

    # Snapshot the already-computed risk result for the Export feature (Stage 6).
    st.session_state["_report_risk"] = {
        "var_pct": res.var_pct,
        "es_pct": res.es_pct,
        "var_price": res.var_price,
        "es_price": res.es_price,
        "current_price": res.current_price,
        "sigma": res.params.sigma,
        "n_paths": res.n_paths,
        "horizon_days": res.horizon_days,
        "times": [float(t) for t in res.times_years],
        "bands": {k: [float(x) for x in v] for k, v in res.bands.items()},
    }

    cur_lbl = f" {currency}" if currency and currency != "—" else ""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Current price", f"{res.current_price:,.2f}{cur_lbl}")
    with c2:
        st.metric(
            "95% VaR · 1-year",
            f"−{res.var_pct:.1%}",
            delta=f"to {res.var_price:,.2f}{cur_lbl}",
            delta_color="off",
        )
    with c3:
        st.metric(
            "95% Expected Shortfall · 1-year",
            f"−{res.es_pct:.1%}",
            delta=f"avg {res.es_price:,.2f}{cur_lbl} in worst 5%",
            delta_color="off",
        )

    st.plotly_chart(
        ui.risk_cone(
            res.times_years, res.bands, res.current_price, currency or "",
            var_price=res.var_price,
        ),
        use_container_width=True,
    )

    # Plain-language reading of the two headline numbers.
    st.markdown(
        f"Over the next year, there's a **5% chance {sym} falls to "
        f"{res.var_price:,.2f}{cur_lbl} or below** (a **{res.var_pct:.1%}** loss — the 95% "
        f"VaR). *If* it lands in that worst-5% tail, the **average** outcome is "
        f"{res.es_price:,.2f}{cur_lbl}, a **{res.es_pct:.1%}** loss (the Expected "
        f"Shortfall, which by definition sits deeper in the tail than VaR)."
    )

    ann_vol = res.params.sigma
    st.caption(
        f"Estimated annualized volatility **{ann_vol:.1%}** (from {res.params.n_returns:,} "
        f"daily log returns); {res.n_paths:,} GBM paths, 252 trading days, 95% confidence. "
        "**Honest labelling:** this is market-price risk simulated from historical "
        "volatility (Geometric Brownian Motion) — it is *separate* from the DCF fundamental "
        "valuation and answers a different question (how the share *price* might move, not "
        "what the business is worth). GBM assumes **lognormal returns and constant "
        "volatility**, so it has no fat tails or volatility clustering and will understate "
        "real-world extreme moves. Educational use only; not investment advice."
    )


# Cap generations per session so a stuck reload loop can't burn the free Gemini quota.
_AI_MAX_GENERATIONS = 10


def _compute_dcf_result(fin: CompanyFinancials, include_lt_inv: bool, wacc_result):
    """Recompute the DCF from the current sidebar slider state, or None if unavailable.

    Mirrors the assumption-building in `_render_dcf` so the AI thesis is grounded in the
    SAME numbers the user sees on the Valuation tab — without re-rendering anything. Returns
    None (never raises) if WACC/sliders/data aren't ready for a DCF."""
    if wacc_result is None:
        return None
    keys = ("dcf_wacc", "dcf_tg", "dcf_growth", "dcf_margin")
    if not all(k in st.session_state for k in keys):
        return None
    try:
        base = default_dcf_assumptions(
            fin, wacc=st.session_state["dcf_wacc"],
            include_long_term_investments=include_lt_inv,
            terminal_growth=st.session_state["dcf_tg"],
        )
        assumptions = replace(
            base,
            revenue_growth=st.session_state["dcf_growth"],
            ebit_margin=st.session_state["dcf_margin"],
        )
        return run_dcf(assumptions)
    except Exception:  # noqa: BLE001 — a DCF that won't compute just means no DCF context
        return None


def _market_multiples(fin: CompanyFinancials) -> dict[str, float]:
    """Trailing market multiples derived from data already in hand (NO extra FMP calls).

    Computed from the profile (market cap, price) and the latest fiscal year, so a missing
    input simply omits that multiple rather than fabricating it."""
    multiples: dict[str, float] = {}
    profile = getattr(fin, "profile", None)
    latest = fin.latest
    if profile is None or latest is None:
        return multiples

    mcap = profile.market_cap
    # Net income = pre-tax income − tax expense (both as reported).
    net_income = None
    if latest.income_before_tax is not None and latest.income_tax_expense is not None:
        net_income = latest.income_before_tax - latest.income_tax_expense

    if mcap and net_income and net_income > 0:
        multiples["Trailing P/E"] = mcap / net_income

    net_debt = latest.derived_net_debt
    if mcap and net_debt is not None:
        ev = mcap + net_debt
        if latest.ebitda and latest.ebitda > 0:
            multiples["EV/EBITDA"] = ev / latest.ebitda
        if latest.revenue and latest.revenue > 0:
            multiples["EV/Sales"] = ev / latest.revenue
    return multiples


def _build_thesis_context(
    api_key: str, fin: CompanyFinancials, wacc_result, include_lt_inv: bool
) -> tuple[ThesisContext, bool]:
    """Assemble the grounded context for the AI thesis. Returns (context, news_attempted).

    News is best-effort: a provider error yields no headlines and the thesis is generated
    from the numbers alone (the prompt notes news wasn't included)."""
    profile = fin.profile
    dcf = _compute_dcf_result(fin, include_lt_inv, wacc_result)

    value_per_share = enterprise_value = equity_value = None
    wacc = terminal_growth = revenue_growth = ebit_margin = gap = None
    if dcf is not None:
        value_per_share = dcf.value_per_share
        enterprise_value = dcf.enterprise_value
        equity_value = dcf.equity_value
        wacc = dcf.assumptions.wacc
        terminal_growth = dcf.assumptions.terminal_growth
        revenue_growth = dcf.assumptions.revenue_growth
        ebit_margin = dcf.assumptions.ebit_margin
        if profile.price and profile.price > 0:
            gap = value_per_share / profile.price - 1.0

    # Best-effort headlines (fail-soft; [] if FMP is unavailable).
    headlines: list[str] = []
    try:
        headlines = load_recent_headlines(api_key, profile.symbol)
    except Exception:  # noqa: BLE001 — news is optional and must never break the thesis
        headlines = []

    ctx = ThesisContext(
        company_name=profile.name,
        symbol=profile.symbol,
        currency=profile.currency or "",
        sector=profile.sector,
        industry=profile.industry,
        value_per_share=value_per_share,
        market_price=profile.price,
        gap_vs_market=gap,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        wacc=wacc,
        terminal_growth=terminal_growth,
        revenue_growth=revenue_growth,
        ebit_margin=ebit_margin,
        multiples=_market_multiples(fin),
        headlines=headlines,
        news_included=bool(headlines),
    )
    return ctx, True


def render_ai_insights_tab(
    api_key: str, fin: CompanyFinancials, wacc_result, include_lt_inv: bool
) -> None:
    """AI Insights tab: a Gemini-generated Bull / Bear / Risk thesis grounded in the DCF
    numbers and multiples. Fails soft — a missing key, rate limit, or any error shows a
    clean message instead of crashing. Does NOT touch the engine or valuation math."""
    sym = getattr(getattr(fin, "profile", None), "symbol", "") or "this company"

    st.subheader("AI Insights")
    st.caption(
        "An AI-generated investment thesis — **Bull Case · Bear Case · Risk Factors** — "
        "grounded in this company's DCF value, its gap versus the market price, and trading "
        "multiples. Generated by Google Gemini."
    )

    gemini_key = resolve_gemini_key()
    if not gemini_key:
        st.info(
            "**Add a Gemini API key to enable this.** Put `GEMINI_API_KEY = \"…\"` in "
            "`.streamlit/secrets.toml` (gitignored) or set the `GEMINI_API_KEY` environment "
            "variable. Get a free key at https://aistudio.google.com/apikey."
        )
        return

    used = st.session_state.get("_ai_gen_count", 0)
    remaining = _AI_MAX_GENERATIONS - used
    store_key = f"_ai_thesis_{sym}"

    btn_label = "Regenerate thesis" if store_key in st.session_state else "Generate AI thesis"
    clicked = st.button(
        btn_label, type="primary", key="gen_ai_thesis", disabled=remaining <= 0
    )
    if remaining <= 0:
        st.warning(
            f"Generation limit for this session reached ({_AI_MAX_GENERATIONS}). "
            "Reload the app to start a new session."
        )

    if clicked:
        ctx, _ = _build_thesis_context(api_key, fin, wacc_result, include_lt_inv)
        try:
            with st.spinner("Generating thesis with Gemini…"):
                thesis = generate_ai_thesis(ctx, gemini_key)
            st.session_state[store_key] = thesis
            st.session_state["_ai_news_included"] = ctx.news_included
            st.session_state["_ai_gen_count"] = used + 1
        except AIKeyError:
            st.info("Add a Gemini API key to enable this.")
            return
        except AIRateLimitError:
            st.warning("AI temporarily unavailable, try again. (Gemini rate limit hit.)")
            return
        except AIError as exc:
            st.error(f"Couldn't generate the thesis: {exc}")
            return
        except Exception:  # noqa: BLE001 — last-resort guard; never crash the app
            st.warning("AI temporarily unavailable, try again.")
            return

    thesis = st.session_state.get(store_key)
    if not thesis:
        st.caption("Click **Generate AI thesis** to produce a grounded Bull / Bear / Risk report.")
        return

    _render_ai_thesis(thesis, st.session_state.get("_ai_news_included", False))


def _render_ai_thesis(thesis: str, news_included: bool) -> None:
    """Render the thesis as a 'premium report' — three separated sections, dark/amber."""
    # Split the model's markdown on its level-2 headings so each section is its own panel.
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in thesis.splitlines():
        if line.strip().startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.strip()[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))

    if not sections:
        # Model didn't use headings as asked — show the raw text rather than nothing.
        st.markdown(thesis)
    else:
        for title, body in sections:
            st.markdown(f"#### {title}")
            st.markdown(body or "_(no content)_")
            st.divider()

    note = (
        "Generated by Google Gemini, grounded in the DCF valuation and multiples shown in "
        "this app. "
    )
    note += (
        "Recent news headlines were included." if news_included
        else "News headlines were not available, so this thesis is based on the valuation "
             "numbers alone."
    )
    st.caption(
        f"⚠️ **AI-generated; educational use only — not investment advice.** {note} "
        "AI output can be wrong or out of date; verify independently."
    )


# P/E bounds that exclude loss-makers (≤0) and obvious garbage/outliers (huge multiples).
_PE_MIN, _PE_MAX = 0.0, 250.0
# Revenue-growth bounds that exclude impossible/garbage YoY figures.
_GROWTH_MIN, _GROWTH_MAX = -0.95, 5.0


def _peer_plottable(p) -> bool:
    """A point is plottable only if P/E, revenue growth and market cap are all present and
    within sane ranges — otherwise it's skipped (never fabricated or clamped onto the chart).
    Every field is read with a safe default so a malformed peer record can never raise."""
    pe = getattr(p, "pe", None)
    growth = getattr(p, "revenue_growth", None)
    cap = getattr(p, "market_cap", None)
    return (
        pe is not None and _PE_MIN < pe < _PE_MAX
        and growth is not None and _GROWTH_MIN <= growth <= _GROWTH_MAX
        and cap is not None and cap > 0
    )


def render_peers_tab(api_key: str, fin: CompanyFinancials) -> None:
    """Render the Peers tab, failing soft at every step. A provider error, rate limit,
    missing peer set, missing field, or any unexpected error shows a clean in-tab message —
    it must NEVER raise and crash the rest of the app."""
    sym = getattr(getattr(fin, "profile", None), "symbol", "") or "this company"

    st.subheader("Peers")
    st.caption(
        "Relative valuation — each bubble is a company: **X = trailing P/E (TTM)**, "
        "**Y = revenue growth (YoY)**, **bubble size = market cap**. "
        f"The amber bubble is **{sym}**; peers are grey."
    )

    try:
        with st.spinner(f"Finding peers for {sym} and pulling their metrics…"):
            comp = load_peer_comparison(api_key, sym)
    except FMPRateLimitError:
        st.info("Peer data temporarily unavailable (provider rate limit) — try again later.")
        return
    except (FMPAuthError, FMPPlanError, FMPNotFound, FMPError) as exc:
        st.error(f"Couldn't load peers: {exc}")
        return
    except Exception:  # noqa: BLE001 — last-resort guard so the load can never crash the app
        st.warning("Peer data unavailable right now.")
        return

    # Rendering is isolated so a surprise in the data shape stays contained to this tab.
    try:
        _render_peer_comparison(sym, comp)
    except Exception:  # noqa: BLE001 — contain any rendering error to the Peers tab
        st.warning("Peer data unavailable right now.")


def _render_peer_comparison(sym: str, comp: PeerComparison) -> None:
    # Read everything off `comp` defensively: a pickle-roundtripped or partial object must
    # not be able to throw an AttributeError here (this tab is fail-soft end to end).
    points = list(getattr(comp, "points", None) or [])
    source = getattr(comp, "source", "none")
    pe_label = getattr(comp, "pe_label", None) or PE_LABEL

    plottable = [p for p in points if _peer_plottable(p)]
    target = next((p for p in plottable if getattr(p, "is_target", False)), None)
    peers = [p for p in plottable if not getattr(p, "is_target", False)]
    skipped = len(points) - len(plottable)

    if source == "none" or len(points) <= 1:
        st.warning(
            f"FMP returned no peer set for **{sym}** on this plan. The relative-valuation "
            "chart needs peers; try a large-cap US ticker (e.g. AAPL, MSFT)."
        )
        return

    if not plottable:
        st.warning(
            "None of the companies returned a usable P/E + revenue growth + market cap, so "
            "there's nothing to plot. (Loss-makers and missing data are skipped, not faked.)"
        )
        return

    # Snapshot a short peer summary for the Export feature (Stage 6).
    _peer_pes = sorted(
        getattr(pp, "pe", None) for pp in peers if getattr(pp, "pe", None)
    )
    _median_pe = _peer_pes[len(_peer_pes) // 2] if _peer_pes else None
    st.session_state["_report_peers"] = {
        "source": source,
        "peer_count": len(peers),
        "target_pe": getattr(target, "pe", None) if target else None,
        "median_peer_pe": _median_pe,
    }

    # Plot — convert to display-ready dicts (decimals stay decimals; ui scales for the axis).
    # Fields are read with safe defaults so a missing attribute can't raise.
    chart_points = [
        {
            "symbol": getattr(p, "symbol", "—"),
            "pe": getattr(p, "pe", None),
            "growth": getattr(p, "revenue_growth", None),
            "market_cap": getattr(p, "market_cap", None),
            "cap_label": fmt_compact(getattr(p, "market_cap", None)),
            "is_target": bool(getattr(p, "is_target", False)),
        }
        for p in plottable
    ]
    try:
        st.plotly_chart(ui.peer_bubble(chart_points, pe_label), use_container_width=True)
    except Exception:  # noqa: BLE001 — a chart failure must not hide the data table below
        st.warning("Couldn't draw the peer bubble chart; the data table below still applies.")

    # Graceful notes: sparse peers, the target itself missing, and how peers were sourced.
    if target is None:
        st.warning(
            f"**{sym}** itself is missing a usable P/E or revenue growth, so it isn't on the "
            "chart — only its peers are shown."
        )
    if len(peers) < 3:
        st.info(
            f"Only **{len(peers)}** peer(s) returned usable data — too few for a confident "
            "comparison. Read the positioning as indicative, not definitive."
        )

    src_label = {"stock-peers": "FMP stock-peers", "screener": "sector/industry screener"}.get(
        source, source
    )
    note = f"Peers via **{src_label}**. P/E is **trailing (TTM)** — the free tier exposes no forward estimate."
    if skipped:
        note += f" {skipped} compan{'y' if skipped == 1 else 'ies'} skipped for missing/garbage data."
    st.caption(note)

    # Compact data table (terminal-style), including rows skipped from the chart.
    rows = {"Trailing P/E": [], "Rev growth YoY": [], "Market cap": []}
    idx = []
    for p in points:
        psym = getattr(p, "symbol", "—")
        pe = getattr(p, "pe", None)
        growth = getattr(p, "revenue_growth", None)
        idx.append(f"▸ {psym}" if getattr(p, "is_target", False) else psym)
        rows["Trailing P/E"].append("—" if pe is None else f"{pe:,.1f}")
        rows["Rev growth YoY"].append("—" if growth is None else f"{growth:+.1%}")
        rows["Market cap"].append(fmt_compact(getattr(p, "market_cap", None)))
    with st.expander("Peer data table"):
        st.table(pd.DataFrame(rows, index=idx))


# ======================================================================================
# Stage 6 — Export Investment Report (packages already-computed session results only)
# ======================================================================================
def _collect_report_data(fin: CompanyFinancials) -> ReportData:
    """Build a ReportData purely from session-state snapshots + the loaded financials.

    No FMP/Gemini calls: valuation/risk/peers come from snapshots the tabs already wrote,
    multiples are derived from the in-hand financials, and the AI thesis (if any) is read
    from session state. Missing sections are simply left as None and skipped downstream."""
    profile = fin.profile
    sym = profile.symbol
    thesis = st.session_state.get(f"_ai_thesis_{sym}")

    # ReportData enforces a single source of truth for the company's trailing P/E across the
    # Key Multiples and Peer Comparison sections (see ReportData.__post_init__), so the same
    # company never shows two different P/E values in the report.
    return ReportData(
        company_name=profile.name,
        symbol=sym,
        report_date=date.today().isoformat(),
        currency=profile.currency or "",
        current_price=profile.price,
        valuation=st.session_state.get("_report_valuation"),
        multiples=_market_multiples(fin),
        peers=st.session_state.get("_report_peers"),
        risk=st.session_state.get("_report_risk"),
        ai_thesis=thesis,
        ai_news_included=bool(st.session_state.get("_ai_news_included", False)),
    )


def _render_export_section(fin: CompanyFinancials) -> None:
    """Render the 'Export Investment Report' download buttons (Markdown + PDF).

    Markdown is the bulletproof primary; PDF is best-effort and, if it can't be built in
    this environment, degrades to a disabled button rather than crashing the app."""
    st.divider()
    st.subheader("Export Investment Report")
    st.caption(
        "Package this session's computed results — DCF, multiples, peers, risk, and the AI "
        "thesis (if generated) — into a downloadable report. No new data is fetched; only "
        "sections you've already computed are included."
    )

    data = _collect_report_data(fin)
    base = (fin.profile.symbol or "report").lower()

    try:
        md_bytes = build_markdown(data).encode("utf-8")
    except Exception:  # noqa: BLE001 — markdown is meant to be bulletproof, but never crash
        st.warning("Couldn't assemble the report from this session.")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇ Download report (Markdown)",
            data=md_bytes,
            file_name=f"{base}_investment_report.md",
            mime="text/markdown",
            type="primary",
            use_container_width=True,
            key="dl_report_md",
        )
    with c2:
        try:
            pdf_bytes = build_pdf(data)
        except Exception:  # noqa: BLE001 — PDF is secondary; fall back to Markdown only
            st.button(
                "PDF unavailable", disabled=True, use_container_width=True,
                key="dl_report_pdf_disabled",
            )
            st.caption("PDF export isn't available in this environment — use Markdown.")
        else:
            st.download_button(
                "⬇ Download report (PDF)",
                data=pdf_bytes,
                file_name=f"{base}_investment_report.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="dl_report_pdf",
            )


# ======================================================================================
# Main flow
# ======================================================================================
def main() -> None:
    st.title("Valuation Explainer")
    st.caption(
        "Institutional valuation terminal — learn **DCF** and **LBO** on a real company, "
        "every term explained in plain language. _Educational use only; not investment advice._"
    )

    api_key = resolve_api_key()
    symbol, years_to_load, include_lt_inv, _go = render_sidebar_setup(api_key)

    # Gating — render the sidebar footer before any early return so it always shows.
    if not api_key:
        render_sidebar_footer()
        st.info("Add your FMP API key to get started (see the sidebar).")
        return
    if not symbol:
        render_sidebar_footer()
        st.warning("Please enter a ticker in the sidebar (e.g. AAPL).")
        return
    if not TICKER_RE.match(symbol):
        render_sidebar_footer()
        st.warning(
            "That doesn't look like a ticker. Use letters, digits, '.' or '-' "
            "(e.g. `AAPL`, `BRK.B`, `SAP.DE`)."
        )
        return

    try:
        with st.spinner(f"Fetching {symbol} from Financial Modeling Prep…"):
            fin = load_financials(api_key, symbol, years_to_load)
    except (FMPAuthError, FMPPlanError, FMPRateLimitError, FMPError) as exc:
        render_sidebar_footer()
        st.error(str(exc))
        return
    except FMPNotFound as exc:
        render_sidebar_footer()
        st.error(f"{exc} — is the ticker correct?")
        return

    if not fin.years:
        render_sidebar_footer()
        st.warning("No financial-statement history was returned for this ticker.")
        return

    # Reset interactive slider state when the loaded company changes.
    if st.session_state.get("_loaded_symbol") != symbol:
        for k in SLIDER_KEYS:
            st.session_state.pop(k, None)
        # Drop stale export snapshots so a new company never exports the old one's results.
        for k in ("_report_valuation", "_report_risk", "_report_peers"):
            st.session_state.pop(k, None)
        st.session_state["_loaded_symbol"] = symbol

    # WACC underpins the DCF sliders + DCF tab (may be None for ticker w/o market cap).
    wacc_result = default_wacc(fin)
    dcf_ready = render_sidebar_dcf_controls(fin, wacc_result, include_lt_inv)
    render_sidebar_footer()

    tab_overview, tab_valuation, tab_risk, tab_ai, tab_peers = st.tabs(
        ["Overview", "Valuation", "Risk", "AI Insights", "Peers"]
    )
    with tab_overview:
        render_overview_tab(fin, years_to_load)
    with tab_valuation:
        render_valuation_tab(fin, include_lt_inv, wacc_result, dcf_ready)
    with tab_risk:
        render_risk_tab(api_key, fin)
    with tab_ai:
        render_ai_insights_tab(api_key, fin, wacc_result, include_lt_inv)
    with tab_peers:
        render_peers_tab(api_key, fin)

    # Export packages whatever the tabs above computed THIS run (read from session state).
    # It is rendered last so every snapshot is fresh, and makes no new FMP/Gemini calls.
    _render_export_section(fin)


main()
