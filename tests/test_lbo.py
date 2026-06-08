"""Golden-number tests for the LBO engine.

The headline case is hand-computed year by year below, with particular attention to the
tax base (EBITDA − D&A − interest) so the interest tax shield is verifiably captured.
"""

import math

from engine.lbo import run_lbo
from engine.models import LBOAssumptions


def base_assumptions() -> LBOAssumptions:
    return LBOAssumptions(
        entry_ebitda=100.0,
        entry_ev_ebitda=10.0,    # entry EV = 1000
        exit_ev_ebitda=10.0,     # flat multiple -> returns come from growth + deleveraging
        entry_leverage=5.0,      # entry debt = 500
        interest_rate=0.08,
        hold_years=3,
        ebitda_growth=0.10,
        da_pct_ebitda=0.20,
        capex_pct_ebitda=0.15,
        nwc_pct_ebitda=0.0,      # zero for a clean hand-calc
        tax_rate=0.25,
        transaction_fees_pct=0.0,
        min_cash=0.0,
    )


def test_lbo_sources_and_uses_golden():
    r = run_lbo(base_assumptions())
    # Entry EV = 10·100 = 1000 ; fees = 0 ; entry debt = 5·100 = 500
    # Sponsor equity = (1000 + 0) − 500 = 500
    assert math.isclose(r.entry_enterprise_value, 1000.0, abs_tol=1e-9)
    assert math.isclose(r.entry_debt, 500.0, abs_tol=1e-9)
    assert math.isclose(r.sponsor_equity, 500.0, abs_tol=1e-9)
    assert math.isclose(r.sources_and_uses["uses"]["total"], 1000.0, abs_tol=1e-9)
    assert math.isclose(r.sources_and_uses["sources"]["total"], 1000.0, abs_tol=1e-9)


def test_lbo_debt_schedule_golden():
    r = run_lbo(base_assumptions())

    # --- Year 1 ---  EBITDA = 110, D&A = 22, Interest = 0.08·500 = 40
    #   Taxable income = 110 − 22 − 40 = 48  ; tax = 48·0.25 = 12
    #   Capex = 16.5 ; FCF avail = 110 − 40 − 12 − 16.5 = 41.5
    #   Debt paydown = 41.5 ; ending debt = 500 − 41.5 = 458.5
    y1 = r.schedule[0]
    assert math.isclose(y1.ebitda, 110.0, abs_tol=1e-9)
    assert math.isclose(y1.interest, 40.0, abs_tol=1e-9)
    assert math.isclose(y1.taxable_income, 48.0, abs_tol=1e-9)
    assert math.isclose(y1.cash_taxes, 12.0, abs_tol=1e-9)
    assert math.isclose(y1.fcf_available, 41.5, abs_tol=1e-9)
    assert math.isclose(y1.ending_debt, 458.5, abs_tol=1e-9)

    # --- Year 2 ---  EBITDA = 121, D&A = 24.2, Interest = 0.08·458.5 = 36.68
    #   Taxable = 121 − 24.2 − 36.68 = 60.12 ; tax = 15.03
    #   Capex = 18.15 ; FCF avail = 121 − 36.68 − 15.03 − 18.15 = 51.14
    #   ending debt = 458.5 − 51.14 = 407.36
    y2 = r.schedule[1]
    assert math.isclose(y2.interest, 36.68, abs_tol=1e-9)
    assert math.isclose(y2.cash_taxes, 15.03, abs_tol=1e-9)
    assert math.isclose(y2.fcf_available, 51.14, abs_tol=1e-9)
    assert math.isclose(y2.ending_debt, 407.36, abs_tol=1e-9)

    # --- Year 3 ---  EBITDA = 133.1, D&A = 26.62, Interest = 0.08·407.36 = 32.5888
    #   Taxable = 133.1 − 26.62 − 32.5888 = 73.8912 ; tax = 18.4728
    #   Capex = 19.965 ; FCF avail = 133.1 − 32.5888 − 18.4728 − 19.965 = 62.0734
    #   ending debt = 407.36 − 62.0734 = 345.2866
    y3 = r.schedule[2]
    assert math.isclose(y3.interest, 32.5888, abs_tol=1e-9)
    assert math.isclose(y3.cash_taxes, 18.4728, abs_tol=1e-9)
    assert math.isclose(y3.fcf_available, 62.0734, abs_tol=1e-9)
    assert math.isclose(y3.ending_debt, 345.2866, abs_tol=1e-9)


def test_lbo_exit_returns_golden():
    r = run_lbo(base_assumptions())
    # Exit EBITDA = 133.1 ; Exit EV = 10·133.1 = 1331 ; cash = 0 ; net debt = 345.2866
    # Exit equity = 1331 − 345.2866 = 985.7134
    # MOIC = 985.7134 / 500 = 1.9714268
    # IRR = 1.9714268^(1/3) − 1 = 0.253889…  (≈ 25.39%)
    assert math.isclose(r.exit_enterprise_value, 1331.0, abs_tol=1e-9)
    assert math.isclose(r.exit_net_debt, 345.2866, abs_tol=1e-9)
    assert math.isclose(r.exit_equity_value, 985.7134, abs_tol=1e-9)
    assert math.isclose(r.moic, 1.9714268, abs_tol=1e-6)
    assert math.isclose(r.irr, 0.253889, abs_tol=1e-5)


def test_lbo_interest_tax_shield_lowers_taxes():
    # Sanity: with leverage, year-1 cash taxes (12.0) must be LESS than an all-equity deal
    # taxed on EBIT (EBITDA − D&A) = 110 − 22 = 88 -> 88·0.25 = 22.0. The 10.0 difference
    # is the year-1 interest tax shield (interest 40 · tax 0.25 = 10).
    r = run_lbo(base_assumptions())
    levered_y1_tax = r.schedule[0].cash_taxes
    all_equity_y1_tax = (110.0 - 22.0) * 0.25
    assert math.isclose(all_equity_y1_tax, 22.0, abs_tol=1e-9)
    assert math.isclose(all_equity_y1_tax - levered_y1_tax, 40.0 * 0.25, abs_tol=1e-9)
