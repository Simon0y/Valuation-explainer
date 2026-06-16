"""Simple leveraged-buyout (LBO) model with 100% cash-sweep debt paydown.

Pure functions, no I/O. All rates/fractions are decimals; multiples are EV/EBITDA.

ENTRY (sources & uses)
----------------------
    Entry EV       = entry_ev_ebitda · EBITDA_0
    Transaction fees = transaction_fees_pct · Entry EV
    Entry debt     = entry_leverage · EBITDA_0
    Sponsor equity = (Entry EV + fees) − Entry debt      # the equity the sponsor puts in

    Uses   = Entry EV + fees
    Sources = Entry debt + Sponsor equity                # Sources == Uses by construction

ANNUAL SCHEDULE (year t = 1..H), with EBITDA growing at `ebitda_growth`:
    EBITDA_t        = EBITDA_{t-1} · (1 + ebitda_growth)
    D&A_t           = EBITDA_t · da_pct_ebitda
    Interest_t      = interest_rate · Debt_{t-1}          # on OPENING balance (flagged)

    Taxable income_t = EBITDA_t − D&A_t − Interest_t      # <-- interest is deductible
    Cash taxes_t     = max(0, Taxable income_t) · tax     # the debt tax shield lives here

    Capex_t          = EBITDA_t · capex_pct_ebitda        # positive magnitude
    ΔNWC_t           = EBITDA_t · nwc_pct_ebitda          # positive = cash used

    FCF available_t  = EBITDA_t − Interest_t − Cash taxes_t − Capex_t − ΔNWC_t
                       (D&A is non-cash, so it is NOT subtracted here — only used for tax.)

    100% cash sweep:
        Debt paydown_t = min( max(FCF available_t, 0), Debt_{t-1} )
        Debt_t         = Debt_{t-1} − Debt paydown_t
        Excess cash    = FCF available_t − Debt paydown_t   (accumulates once debt is gone)
        Cash_t         = Cash_{t-1} + Excess cash

EXIT (year H):
    Exit EV       = exit_ev_ebitda · EBITDA_H
    Exit net debt = Debt_H − Cash_H
    Exit equity   = Exit EV − Exit net debt
    MOIC          = Exit equity / Sponsor equity
    IRR           = MOIC^(1/H) − 1            # single equity outflow at t0, inflow at exit

WHY TAXES ON EBITDA − D&A − INTEREST (not EBITDA or EBIT)
--------------------------------------------------------
Interest is tax-deductible, so leverage shields income from tax. Taxing EBIT (EBITDA − D&A)
would ignore that shield; taxing EBITDA would also ignore depreciation. Using
EBITDA − D&A − Interest as the tax base captures the **interest tax shield**, a core driver
of LBO returns. The shield is implicitly the difference in cash taxes vs an all-equity deal.

ASSUMPTIONS (flagged):
  * Interest accrues on the opening debt balance (simple; ignores intra-year paydown).
  * Taxes are zero when taxable income is negative; no loss carryforwards modelled.
  * No revolver / minimum-cash draw: if FCF is ever negative, cash simply falls (can go
    negative as an IOU) rather than triggering new borrowing. `min_cash` is reserved for a
    future floor and currently informational only.
  * No dividend recaps; single equity outflow at entry, single inflow at exit.
  * IRR uses the closed-form MOIC^(1/H)−1 because there are no interim cash flows; if
    interim distributions are added later, switch to a numeric IRR solver.
"""

from __future__ import annotations

from engine.models import LBOAssumptions, LBOResult, LBOYear


def run_lbo(a: LBOAssumptions) -> LBOResult:
    """Run the LBO and return sources & uses, the debt schedule, and exit returns."""
    if a.hold_years < 1:
        raise ValueError("hold_years must be >= 1.")
    if a.entry_ebitda <= 0:
        raise ValueError("entry_ebitda must be positive.")

    entry_ev = a.entry_ev_ebitda * a.entry_ebitda
    fees = a.transaction_fees_pct * entry_ev
    entry_debt = a.entry_leverage * a.entry_ebitda
    sponsor_equity = (entry_ev + fees) - entry_debt

    if sponsor_equity <= 0:
        raise ValueError(
            "Sponsor equity is non-positive: entry leverage exceeds entry EV plus fees."
        )

    sources_and_uses = {
        "uses": {
            "purchase_enterprise_value": entry_ev,
            "transaction_fees": fees,
            "total": entry_ev + fees,
        },
        "sources": {
            "debt": entry_debt,
            "sponsor_equity": sponsor_equity,
            "total": entry_debt + sponsor_equity,
        },
    }

    schedule: list[LBOYear] = []
    debt = entry_debt
    cash = 0.0
    ebitda = a.entry_ebitda

    for t in range(1, a.hold_years + 1):
        ebitda = ebitda * (1.0 + a.ebitda_growth)
        da = ebitda * a.da_pct_ebitda
        interest = a.interest_rate * debt                       # opening balance

        taxable_income = ebitda - da - interest                 # interest deductible
        cash_taxes = max(0.0, taxable_income) * a.tax_rate       # shield captured here

        capex = ebitda * a.capex_pct_ebitda
        delta_nwc = ebitda * a.nwc_pct_ebitda

        fcf_available = ebitda - interest - cash_taxes - capex - delta_nwc

        paydown = min(max(fcf_available, 0.0), debt)            # 100% cash sweep
        debt = debt - paydown
        excess = fcf_available - paydown
        cash = cash + excess

        schedule.append(
            LBOYear(
                year=t,
                ebitda=ebitda,
                depreciation_amortization=da,
                interest=interest,
                taxable_income=taxable_income,
                cash_taxes=cash_taxes,
                capex=capex,
                change_in_nwc=delta_nwc,
                fcf_available=fcf_available,
                debt_paydown=paydown,
                ending_debt=debt,
                cash_balance=cash,
            )
        )

    exit_ebitda = schedule[-1].ebitda
    exit_ev = a.exit_ev_ebitda * exit_ebitda
    exit_net_debt = debt - cash
    exit_equity = exit_ev - exit_net_debt

    moic = exit_equity / sponsor_equity
    # IRR from a single in/out: solve sponsor_equity·(1+irr)^H = exit_equity.
    # Guard against a wiped-out (non-positive) exit equity, where IRR is undefined here.
    if exit_equity <= 0:
        irr = -1.0
    else:
        irr = moic ** (1.0 / a.hold_years) - 1.0

    notes = [
        "Cash taxes computed on EBITDA − D&A − interest (interest tax shield captured).",
        "Interest on opening debt balance; 100% cash sweep to debt paydown.",
        "No revolver/min-cash draw; no dividend recaps.",
        "IRR = MOIC^(1/H) − 1 (single equity in at entry, out at exit).",
    ]

    return LBOResult(
        entry_enterprise_value=entry_ev,
        transaction_fees=fees,
        entry_debt=entry_debt,
        sponsor_equity=sponsor_equity,
        sources_and_uses=sources_and_uses,
        schedule=schedule,
        hold_years=a.hold_years,
        exit_ebitda=exit_ebitda,
        exit_enterprise_value=exit_ev,
        exit_net_debt=exit_net_debt,
        exit_equity_value=exit_equity,
        moic=moic,
        irr=irr,
        assumptions=a,
        notes=notes,
    )
