"""Golden-number tests for the driver-based DCF engine.

The headline case is chosen so the arithmetic is checkable by hand. Notably the FCFF grows
at exactly the WACC (10%), so each year's present value is identical — a clean invariant.
"""

import math

import pytest

from engine.dcf import run_dcf
from engine.models import DCFAssumptions


def base_assumptions() -> DCFAssumptions:
    return DCFAssumptions(
        base_revenue=1000.0,
        forecast_years=3,
        ebit_margin=0.20,
        da_pct_revenue=0.05,
        capex_pct_revenue=0.07,
        nwc_pct_incremental_revenue=0.10,
        tax_rate=0.25,
        wacc=0.10,
        terminal_growth=0.02,
        net_debt=200.0,
        shares_outstanding=100.0,
        revenue_growth=0.10,
    )


def test_dcf_year_by_year_golden():
    r = run_dcf(base_assumptions())

    # --- Year 1: Rev = 1000·1.1 = 1100 ---
    #   EBIT = 1100·0.20 = 220 ; NOPAT = 220·0.75 = 165
    #   D&A = 1100·0.05 = 55 ; Capex = 1100·0.07 = 77
    #   ΔRev = 100 ; ΔNWC = 100·0.10 = 10
    #   FCFF = 165 + 55 − 77 − 10 = 133
    y1 = r.years[0]
    assert math.isclose(y1.revenue, 1100.0, abs_tol=1e-9)
    assert math.isclose(y1.nopat, 165.0, abs_tol=1e-9)
    assert math.isclose(y1.fcff, 133.0, abs_tol=1e-9)

    # --- Year 2: Rev = 1210 ---  FCFF = 181.5 + 60.5 − 84.7 − 11 = 146.3
    y2 = r.years[1]
    assert math.isclose(y2.revenue, 1210.0, abs_tol=1e-9)
    assert math.isclose(y2.fcff, 146.3, abs_tol=1e-9)

    # --- Year 3: Rev = 1331 ---  FCFF = 199.65 + 66.55 − 93.17 − 12.1 = 160.93
    y3 = r.years[2]
    assert math.isclose(y3.revenue, 1331.0, abs_tol=1e-9)
    assert math.isclose(y3.fcff, 160.93, abs_tol=1e-9)


def test_dcf_present_values_and_bridge_golden():
    r = run_dcf(base_assumptions())

    # FCFF grows at exactly the 10% WACC, so every PV equals 133 / 1.1 = 120.909090…
    expected_pv = 133.0 / 1.1
    for y in r.years:
        assert math.isclose(y.pv_fcff, expected_pv, abs_tol=1e-6)

    # Σ PV(FCFF) = 3 · 120.909090… = 362.7272727…
    assert math.isclose(r.sum_pv_fcff, 3 * expected_pv, abs_tol=1e-6)

    # Terminal value: TV_3 = FCFF_3·(1+g)/(WACC−g) = 160.93·1.02/0.08 = 2051.8575
    assert math.isclose(r.terminal_value, 160.93 * 1.02 / 0.08, abs_tol=1e-6)
    assert math.isclose(r.terminal_value, 2051.8575, abs_tol=1e-4)

    # PV(TV) = 2051.8575 / 1.1^3 = 2051.8575 / 1.331 = 1541.59090…
    expected_pv_tv = 2051.8575 / (1.1 ** 3)
    assert math.isclose(r.pv_terminal_value, expected_pv_tv, abs_tol=1e-6)

    # EV = 362.72727 + 1541.59090 = 1904.31818
    expected_ev = 3 * expected_pv + expected_pv_tv
    assert math.isclose(r.enterprise_value, expected_ev, abs_tol=1e-6)
    assert math.isclose(r.enterprise_value, 1904.31818, abs_tol=1e-3)

    # Equity = EV − net debt = 1904.31818 − 200 = 1704.31818
    assert math.isclose(r.equity_value, expected_ev - 200.0, abs_tol=1e-6)

    # Per share = 1704.31818 / 100 = 17.0432
    assert math.isclose(r.value_per_share, (expected_ev - 200.0) / 100.0, abs_tol=1e-6)
    assert math.isclose(r.value_per_share, 17.0432, abs_tol=1e-3)


def test_dcf_requires_wacc_above_terminal_growth():
    bad = base_assumptions()
    bad = DCFAssumptions(**{**bad.__dict__, "wacc": 0.02, "terminal_growth": 0.03})
    with pytest.raises(ValueError):
        run_dcf(bad)
