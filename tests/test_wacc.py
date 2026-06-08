"""Golden-number tests for the WACC (CAPM) engine.

Every expected value is hand-computed in the comments so the finance can be checked
independently of the implementation.
"""

import math

from engine.wacc import compute_wacc, cost_of_equity_capm


def test_cost_of_equity_capm():
    # Ke = rf + β·ERP = 0.04 + 1.2·0.05 = 0.04 + 0.06 = 0.10
    ke = cost_of_equity_capm(risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05)
    assert math.isclose(ke, 0.10, abs_tol=1e-12)


def test_compute_wacc_golden():
    # Inputs
    #   E = 800, D = 200  -> total = 1000, wE = 0.8, wD = 0.2
    #   rf = 0.04, β = 1.2, ERP = 0.05  -> Ke = 0.10
    #   pretax Kd = 0.05, tax = 0.25    -> Kd_after_tax = 0.05·0.75 = 0.0375
    #   WACC = 0.8·0.10 + 0.2·0.0375 = 0.08 + 0.0075 = 0.0875  (8.75%)
    r = compute_wacc(
        equity_value=800.0,
        debt_value=200.0,
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        pretax_cost_of_debt=0.05,
        tax_rate=0.25,
    )
    assert math.isclose(r.cost_of_equity, 0.10, abs_tol=1e-12)
    assert math.isclose(r.after_tax_cost_of_debt, 0.0375, abs_tol=1e-12)
    assert math.isclose(r.equity_weight, 0.8, abs_tol=1e-12)
    assert math.isclose(r.debt_weight, 0.2, abs_tol=1e-12)
    assert math.isclose(r.wacc, 0.0875, abs_tol=1e-12)


def test_zero_debt_wacc_equals_cost_of_equity():
    # With no debt, WACC must collapse to the cost of equity.
    r = compute_wacc(
        equity_value=1000.0,
        debt_value=0.0,
        risk_free_rate=0.03,
        beta=1.0,
        equity_risk_premium=0.05,
        pretax_cost_of_debt=0.06,
        tax_rate=0.21,
    )
    # Ke = 0.03 + 1.0·0.05 = 0.08; debt weight 0 -> WACC = 0.08
    assert math.isclose(r.wacc, 0.08, abs_tol=1e-12)
