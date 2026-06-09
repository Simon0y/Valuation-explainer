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

import pandas as pd
import streamlit as st

import ui
import ui_theme
from data.fmp_client import (
    FMPAuthError,
    FMPClient,
    FMPError,
    FMPNotFound,
    FMPPlanError,
    FMPRateLimitError,
)
from data.fundamentals import fetch_financials
from engine.defaults import (
    default_dcf_assumptions,
    default_lbo_assumptions,
    default_wacc,
)
from engine.dcf import run_dcf
from engine.lbo import run_lbo
from engine.models import CompanyFinancials

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


@st.cache_data(show_spinner=False)
def load_financials(api_key: str, symbol: str, limit: int) -> CompanyFinancials:
    client = FMPClient(api_key)
    return fetch_financials(client, symbol, limit=limit)


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


def render_risk_tab() -> None:
    render_coming_soon(
        "Risk",
        "Quantify the sensitivity and downside around the valuation you built.",
        [
            "WACC × terminal-growth sensitivity grid for the DCF value/share.",
            "Tornado chart of which assumptions move the valuation most.",
            "Leverage / interest-coverage and break-even stress on the LBO.",
        ],
    )


def render_ai_insights_tab() -> None:
    render_coming_soon(
        "AI Insights",
        "Plain-language commentary on what the numbers imply — grounded in the data shown.",
        [
            "Narrative summary of the valuation and its key drivers.",
            "Flags where assumptions diverge sharply from the company's history.",
            "Suggested questions to pressure-test the thesis.",
        ],
    )


def render_peers_tab() -> None:
    render_coming_soon(
        "Peers",
        "Put the company in context against comparable firms.",
        [
            "Comparable-company multiples table (EV/EBITDA, P/E, growth, margins).",
            "Relative-valuation implied value/share vs the DCF.",
            "Sector/industry positioning on growth and profitability.",
        ],
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
        render_risk_tab()
    with tab_ai:
        render_ai_insights_tab()
    with tab_peers:
        render_peers_tab()


main()
