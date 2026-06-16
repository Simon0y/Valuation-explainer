"""Driver-based, two-stage unlevered-FCFF discounted cash flow (DCF).

Pure functions, no I/O. All rates/ratios are decimals.

METHOD
------
Stage 1 — explicit forecast for years t = 1..N. Each year is built from drivers:

    Revenue_t = Revenue_{t-1} · (1 + g_t)
    EBIT_t    = Revenue_t · ebit_margin
    NOPAT_t   = EBIT_t · (1 − tax)                      # net operating profit after tax
    D&A_t     = Revenue_t · da_pct_revenue
    Capex_t   = Revenue_t · capex_pct_revenue           # positive magnitude (outflow)
    ΔNWC_t    = (Revenue_t − Revenue_{t-1}) · nwc_pct_incremental_revenue

    FCFF_t    = NOPAT_t + D&A_t − Capex_t − ΔNWC_t      # unlevered free cash flow to firm

Each FCFF is discounted at the WACC:

    PV(FCFF_t) = FCFF_t / (1 + WACC)^t

Stage 2 — Gordon-growth terminal value capturing all cash flows beyond year N:

    TV_N      = FCFF_N · (1 + g∞) / (WACC − g∞)
    PV(TV)    = TV_N / (1 + WACC)^N

Bridge to equity:

    Enterprise value = Σ PV(FCFF_t) + PV(TV)
    Equity value     = Enterprise value − Net debt
    Value per share  = Equity value / Shares outstanding

ASSUMPTIONS (flagged):
  * End-of-year discounting (no mid-year convention). Mid-year would raise PVs slightly.
  * Constant margin and constant capex/D&A/NWC ratios across the forecast.
  * Requires WACC > terminal growth, else the Gordon formula diverges (we raise).
  * FCFF is *unlevered* (pre-financing); net debt is removed only at the equity bridge.
  * Net debt definition (incl./excl. long-term investments) is decided by the caller when
    it builds `DCFAssumptions.net_debt` — see FinancialYear.net_debt_for_bridge.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional

from engine.models import DCFAssumptions, DCFResult, DCFYear


def run_dcf(a: DCFAssumptions) -> DCFResult:
    """Run the DCF and return the full result with every intermediate number."""
    if a.forecast_years < 1:
        raise ValueError("forecast_years must be >= 1.")
    if a.wacc <= a.terminal_growth:
        raise ValueError(
            f"WACC ({a.wacc:.4f}) must exceed terminal growth ({a.terminal_growth:.4f}) "
            "for the Gordon terminal value to be valid."
        )
    if a.shares_outstanding <= 0:
        raise ValueError("shares_outstanding must be positive.")

    # Per-year growth path: explicit path if given, else the single rate repeated.
    if a.revenue_growth_path is not None:
        if len(a.revenue_growth_path) != a.forecast_years:
            raise ValueError("revenue_growth_path length must equal forecast_years.")
        growth = list(a.revenue_growth_path)
    else:
        growth = [a.revenue_growth] * a.forecast_years

    years: list[DCFYear] = []
    prev_revenue = a.base_revenue
    sum_pv = 0.0
    last_fcff = 0.0

    for t in range(1, a.forecast_years + 1):
        revenue = prev_revenue * (1.0 + growth[t - 1])
        ebit = revenue * a.ebit_margin
        nopat = ebit * (1.0 - a.tax_rate)
        da = revenue * a.da_pct_revenue
        capex = revenue * a.capex_pct_revenue                 # positive magnitude
        delta_nwc = (revenue - prev_revenue) * a.nwc_pct_incremental_revenue

        fcff = nopat + da - capex - delta_nwc

        discount_factor = 1.0 / (1.0 + a.wacc) ** t
        pv_fcff = fcff * discount_factor

        years.append(
            DCFYear(
                year=t,
                revenue=revenue,
                ebit=ebit,
                nopat=nopat,
                depreciation_amortization=da,
                capex=capex,
                change_in_nwc=delta_nwc,
                fcff=fcff,
                discount_factor=discount_factor,
                pv_fcff=pv_fcff,
            )
        )

        sum_pv += pv_fcff
        prev_revenue = revenue
        last_fcff = fcff

    # Gordon-growth terminal value on the final-year FCFF, discounted back N years.
    terminal_value = last_fcff * (1.0 + a.terminal_growth) / (a.wacc - a.terminal_growth)
    pv_terminal = terminal_value / (1.0 + a.wacc) ** a.forecast_years

    enterprise_value = sum_pv + pv_terminal
    equity_value = enterprise_value - a.net_debt
    value_per_share = equity_value / a.shares_outstanding

    notes = [
        "Unlevered FCFF discounted at WACC; end-of-year convention.",
        "Constant margin and constant capex/D&A/NWC ratios across the forecast.",
        f"Terminal value via Gordon growth at g∞={a.terminal_growth:.2%}.",
        "Equity = EV − net debt; net-debt definition set by the caller.",
    ]

    return DCFResult(
        years=years,
        sum_pv_fcff=sum_pv,
        terminal_value=terminal_value,
        pv_terminal_value=pv_terminal,
        enterprise_value=enterprise_value,
        net_debt=a.net_debt,
        equity_value=equity_value,
        shares_outstanding=a.shares_outstanding,
        value_per_share=value_per_share,
        assumptions=a,
        notes=notes,
    )


# ======================================================================================
# Reverse DCF — what does today's market price imply?
# ======================================================================================
# These solvers wrap the SAME `run_dcf` above (the forward DCF math is never touched). They
# answer: holding every other base-case assumption fixed, what single input makes the DCF
# fair value equal the current market price? Solved numerically by bisection, fail-soft.


def _solve_assumption(
    base: DCFAssumptions,
    target_price: float,
    apply: Callable[[float], DCFAssumptions],
    lo: float,
    hi: float,
    *,
    increasing: bool,
    tol: float = 1e-4,
    max_iter: int = 200,
) -> Optional[float]:
    """Bisect for the scalar input x that makes ``run_dcf`` value/share == ``target_price``.

    ``apply(x)`` returns a ``DCFAssumptions`` with the swept input set to x and everything
    else held at ``base``. ``increasing`` says whether value/share rises with x (True for
    revenue growth, False for WACC). Returns None — never raises — when the target isn't
    bracketed by ``[lo, hi]`` or any evaluation is invalid, so the caller can say "no
    solution in a sane range" instead of showing a bogus number.
    """
    def value_at(x: float) -> Optional[float]:
        try:
            return run_dcf(apply(x)).value_per_share
        except (ValueError, ZeroDivisionError):
            return None

    f_lo = value_at(lo)
    f_hi = value_at(hi)
    if f_lo is None or f_hi is None:
        return None
    # The root must be bracketed for bisection to be valid.
    if not (min(f_lo, f_hi) <= target_price <= max(f_lo, f_hi)):
        return None

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = value_at(mid)
        if f_mid is None:
            return None
        if abs(f_mid - target_price) <= tol or (hi - lo) < 1e-9:
            return mid
        # Keep the half-interval that still brackets the target, honoring monotonicity.
        if (f_mid > target_price) == increasing:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def implied_growth_for_price(
    base: DCFAssumptions,
    target_price: float,
    lo: float = -0.50,
    hi: float = 1.00,
) -> Optional[float]:
    """Annual revenue growth (one rate, all forecast years) that makes the DCF fair value
    equal ``target_price``, holding every other base-case assumption fixed. Searches a sane
    band of [-50%, +100%]; returns None if no solution lies within it. Value/share rises
    monotonically with growth, so bisection is well-posed."""
    def apply(g: float) -> DCFAssumptions:
        return replace(base, revenue_growth=g, revenue_growth_path=None)

    return _solve_assumption(base, target_price, apply, lo, hi, increasing=True)


def implied_wacc_for_price(
    base: DCFAssumptions,
    target_price: float,
    hi: float = 0.60,
) -> Optional[float]:
    """WACC that makes the DCF fair value equal ``target_price``, holding everything else
    fixed. Searches (terminal_growth, hi]; value/share falls monotonically as WACC rises.
    Returns None if no solution lies in range (e.g. price unreachable even at 60% WACC)."""
    lo = base.terminal_growth + 1e-4
    if hi <= lo:
        return None

    def apply(w: float) -> DCFAssumptions:
        return replace(base, wacc=w)

    return _solve_assumption(base, target_price, apply, lo, hi, increasing=False)
