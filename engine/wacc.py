"""Weighted-average cost of capital (WACC) via CAPM.

Pure functions, no I/O. All rates are decimals (0.08 == 8%).

The WACC is the discount rate for unlevered free cash flow in the DCF. It blends the
cost of equity and the after-tax cost of debt by their market-value weights:

    Cost of equity (CAPM):   Ke = rf + β · ERP
    After-tax cost of debt:  Kd_at = Kd_pretax · (1 − tax)
    WACC = (E / (E+D)) · Ke + (D / (E+D)) · Kd_at

where E is the market value of equity (market cap) and D is total debt.

ASSUMPTIONS (flagged):
  * Only two capital components (equity + debt); no preferred stock / minority interest.
  * Debt is valued at book (total debt) as a proxy for market value of debt.
  * The interest tax shield is captured via the after-tax cost of debt (standard WACC).
"""

from __future__ import annotations

from engine.models import WACCResult


def cost_of_equity_capm(
    risk_free_rate: float, beta: float, equity_risk_premium: float
) -> float:
    """CAPM cost of equity: Ke = rf + β · ERP."""
    return risk_free_rate + beta * equity_risk_premium


def compute_wacc(
    equity_value: float,
    debt_value: float,
    risk_free_rate: float,
    beta: float,
    equity_risk_premium: float,
    pretax_cost_of_debt: float,
    tax_rate: float,
) -> WACCResult:
    """Compute WACC and return every intermediate component.

    Parameters
    ----------
    equity_value : market value of equity (market cap), > 0
    debt_value   : total debt, >= 0
    risk_free_rate, beta, equity_risk_premium : CAPM inputs
    pretax_cost_of_debt : pre-tax cost of debt (Kd)
    tax_rate : marginal/effective tax rate used for the debt shield
    """
    if equity_value <= 0:
        raise ValueError("equity_value (market cap) must be positive.")
    if debt_value < 0:
        raise ValueError("debt_value must be non-negative.")

    total_capital = equity_value + debt_value
    equity_weight = equity_value / total_capital
    debt_weight = debt_value / total_capital

    ke = cost_of_equity_capm(risk_free_rate, beta, equity_risk_premium)
    kd_after_tax = pretax_cost_of_debt * (1.0 - tax_rate)

    wacc = equity_weight * ke + debt_weight * kd_after_tax

    return WACCResult(
        risk_free_rate=risk_free_rate,
        beta=beta,
        equity_risk_premium=equity_risk_premium,
        cost_of_equity=ke,
        pretax_cost_of_debt=pretax_cost_of_debt,
        tax_rate=tax_rate,
        after_tax_cost_of_debt=kd_after_tax,
        equity_value=equity_value,
        debt_value=debt_value,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
        wacc=wacc,
    )
