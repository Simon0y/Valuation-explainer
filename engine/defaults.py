"""Seed valuation assumptions from a company's historical financials.

Pure functions (operate only on `engine.models`; no I/O, no Streamlit). These produce
*starting points* a user will later override with sliders (Stage 3). Every heuristic is
documented; where data is missing we fall back to a clearly-stated default rather than
fabricating a company-specific number.

These are deliberately simple, transparent estimates — not a forecast the app endorses.
"""

from __future__ import annotations

from typing import Optional

from engine.models import (
    CompanyFinancials,
    DCFAssumptions,
    LBOAssumptions,
    WACCResult,
)
from engine.wacc import compute_wacc

# Fallback macro assumptions (decimals). Overridable by the user in later stages.
DEFAULT_RISK_FREE = 0.04
DEFAULT_EQUITY_RISK_PREMIUM = 0.05
DEFAULT_PRETAX_COST_OF_DEBT = 0.055
DEFAULT_TAX_RATE = 0.21
DEFAULT_TERMINAL_GROWTH = 0.025
DEFAULT_FORECAST_YEARS = 5
DEFAULT_BETA = 1.0


def _safe_ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def effective_tax_rate(fin: CompanyFinancials) -> float:
    """Latest effective tax rate if computable, else the default."""
    latest = fin.latest
    if latest is not None:
        etr = latest.effective_tax_rate
        if etr is not None:
            return _clamp(etr, 0.0, 0.5)
    return DEFAULT_TAX_RATE


def revenue_cagr(fin: CompanyFinancials) -> float:
    """Geometric revenue CAGR from the oldest to the latest available year.

    Falls back to 5% if there isn't enough clean data. Clamped to [-20%, 40%] so a single
    odd year can't produce an absurd default.
    """
    revs = [y.revenue for y in fin.years if y.revenue is not None and y.revenue > 0]
    # fin.years is newest-first, so revs[0] is latest, revs[-1] is oldest.
    if len(revs) >= 2:
        latest, oldest = revs[0], revs[-1]
        n = len(revs) - 1
        cagr = (latest / oldest) ** (1.0 / n) - 1.0
        return _clamp(cagr, -0.20, 0.40)
    return 0.05


def _avg_ratio_to_revenue(fin: CompanyFinancials, attr: str, use_abs: bool) -> Optional[float]:
    """Average of (line item / revenue) across years where both are present."""
    ratios: list[float] = []
    for y in fin.years:
        rev = y.revenue
        val = getattr(y, attr)
        if rev and rev > 0 and val is not None:
            v = abs(val) if use_abs else val
            ratios.append(v / rev)
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


def _nwc_pct_incremental_revenue(fin: CompanyFinancials) -> float:
    """Increase in net working capital per dollar of incremental revenue.

    The cash-flow `change_in_working_capital` uses the convention positive = cash released
    (NWC fell), so the *increase* in NWC for a year is its negative. We pair each year's
    NWC increase with that year's revenue change and average across years with rising
    revenue. Clamped to [0, 30%]; defaults to 10% when not computable.
    """
    pcts: list[float] = []
    years = fin.years  # newest-first
    for newer, older in zip(years, years[1:]):
        if (
            newer.revenue is None
            or older.revenue is None
            or newer.change_in_working_capital is None
        ):
            continue
        delta_rev = newer.revenue - older.revenue
        if delta_rev <= 0:
            continue
        increase_in_nwc = -newer.change_in_working_capital
        pcts.append(increase_in_nwc / delta_rev)
    if not pcts:
        return 0.10
    return _clamp(sum(pcts) / len(pcts), 0.0, 0.30)


def default_wacc(
    fin: CompanyFinancials,
    risk_free_rate: float = DEFAULT_RISK_FREE,
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM,
    pretax_cost_of_debt: float = DEFAULT_PRETAX_COST_OF_DEBT,
    tax_rate: Optional[float] = None,
) -> Optional[WACCResult]:
    """Build a CAPM WACC from market cap, total debt and beta. None if market cap missing."""
    profile = fin.profile
    latest = fin.latest
    if profile.market_cap is None or profile.market_cap <= 0 or latest is None:
        return None
    beta = profile.beta if profile.beta is not None else DEFAULT_BETA
    debt = latest.total_debt if latest.total_debt is not None else 0.0
    tax = tax_rate if tax_rate is not None else effective_tax_rate(fin)
    return compute_wacc(
        equity_value=profile.market_cap,
        debt_value=debt,
        risk_free_rate=risk_free_rate,
        beta=beta,
        equity_risk_premium=equity_risk_premium,
        pretax_cost_of_debt=pretax_cost_of_debt,
        tax_rate=tax,
    )


def default_dcf_assumptions(
    fin: CompanyFinancials,
    wacc: float,
    include_long_term_investments: bool = False,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
    forecast_years: int = DEFAULT_FORECAST_YEARS,
) -> Optional[DCFAssumptions]:
    """Seed DCF drivers from history. Returns None if the essential inputs are missing."""
    latest = fin.latest
    if latest is None or latest.revenue is None or not latest.shares_outstanding:
        return None

    ebit_margin = _safe_ratio(latest.ebit, latest.revenue)
    if ebit_margin is None:
        ebit_margin = _avg_ratio_to_revenue(fin, "ebit", use_abs=False)
    da_pct = _avg_ratio_to_revenue(fin, "depreciation_amortization", use_abs=False)
    capex_pct = _avg_ratio_to_revenue(fin, "capex", use_abs=True)  # capex stored negative

    if ebit_margin is None or da_pct is None or capex_pct is None:
        return None

    net_debt = latest.net_debt_for_bridge(include_long_term_investments)
    if net_debt is None:
        net_debt = 0.0  # bridge with zero net debt rather than refusing; flagged in UI

    return DCFAssumptions(
        base_revenue=latest.revenue,
        forecast_years=forecast_years,
        ebit_margin=ebit_margin,
        da_pct_revenue=da_pct,
        capex_pct_revenue=capex_pct,
        nwc_pct_incremental_revenue=_nwc_pct_incremental_revenue(fin),
        tax_rate=effective_tax_rate(fin),
        wacc=wacc,
        terminal_growth=terminal_growth,
        net_debt=net_debt,
        shares_outstanding=latest.shares_outstanding,
        revenue_growth=revenue_cagr(fin),
    )


def default_lbo_assumptions(
    fin: CompanyFinancials,
    entry_leverage: float = 5.0,
    interest_rate: float = 0.08,
    hold_years: int = 5,
    transaction_fees_pct: float = 0.02,
) -> Optional[LBOAssumptions]:
    """Seed an LBO from history. Entry/exit multiple default to the current EV/EBITDA."""
    latest = fin.latest
    profile = fin.profile
    if latest is None or not latest.ebitda or latest.ebitda <= 0:
        return None

    # Current EV/EBITDA as the entry & exit multiple (conventional net debt, excl. LT inv).
    net_debt = latest.net_debt_for_bridge(False) or 0.0
    if profile.market_cap is None:
        return None
    current_ev = profile.market_cap + net_debt
    ev_ebitda = _clamp(current_ev / latest.ebitda, 3.0, 30.0)

    da_pct = _safe_ratio(latest.depreciation_amortization, latest.ebitda) or 0.20
    capex_pct = _safe_ratio(
        abs(latest.capex) if latest.capex is not None else None, latest.ebitda
    ) or 0.15

    return LBOAssumptions(
        entry_ebitda=latest.ebitda,
        entry_ev_ebitda=ev_ebitda,
        exit_ev_ebitda=ev_ebitda,
        entry_leverage=entry_leverage,
        interest_rate=interest_rate,
        hold_years=hold_years,
        ebitda_growth=revenue_cagr(fin),  # proxy EBITDA growth by revenue CAGR
        da_pct_ebitda=_clamp(da_pct, 0.0, 1.0),
        capex_pct_ebitda=_clamp(capex_pct, 0.0, 1.0),
        nwc_pct_ebitda=0.0,
        tax_rate=effective_tax_rate(fin),
        transaction_fees_pct=transaction_fees_pct,
        min_cash=0.0,
    )
