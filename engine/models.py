"""Data models shared across the valuation engine and the data layer.

These are plain dataclasses with no behaviour beyond a couple of safe derived helpers.
They are the *only* thing the `data/` package is allowed to import from `engine/`, and
they are the contract the Streamlit UI renders. Keeping them dumb keeps the engine pure
and the frontend swappable.

All monetary values are stored in the company's *reporting currency*, in the same units
the API returns (i.e. absolute units, not millions). Per-share values are in that same
currency. We never rescale or invent numbers here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CompanyProfile:
    """Descriptive, non-financial-statement facts about a company.

    Sourced from the FMP `profile` endpoint. `market_cap` and `price` are point-in-time
    market values (not statement figures) and are shown as-is.
    """

    symbol: str
    name: str
    description: str
    sector: str
    industry: str
    currency: str
    market_cap: Optional[float]
    price: Optional[float]
    beta: Optional[float]
    website: Optional[str] = None
    exchange: Optional[str] = None


@dataclass(frozen=True)
class FinancialYear:
    """One fiscal year of the line items this app cares about.

    Every field is exactly what the API reported for that year (after we map field names),
    with two documented sign conventions preserved as-reported by FMP:

      * `capex` is NEGATIVE (a cash outflow on the cash-flow statement).
      * `change_in_working_capital` uses the cash-flow-statement sign convention, where a
        POSITIVE value means working capital *released* cash that year (a source of cash)
        and a NEGATIVE value means cash was *absorbed* into working capital.

    These conventions matter for the DCF in Stage 2, so they are surfaced in the UI for the
    user to confirm against the real numbers before any math depends on them. `None` means
    the API did not return that field for that year (e.g. on a limited plan).
    """

    fiscal_year: str          # e.g. "2024" — the calendar/fiscal label FMP returns
    period: str               # e.g. "FY"
    reported_currency: str

    revenue: Optional[float]
    ebit: Optional[float]                       # operating income
    ebitda: Optional[float]
    depreciation_amortization: Optional[float]
    capex: Optional[float]                      # negative (cash outflow), as reported
    change_in_working_capital: Optional[float]  # cash-flow-statement sign convention

    income_before_tax: Optional[float]
    income_tax_expense: Optional[float]

    total_debt: Optional[float]
    cash_and_st_investments: Optional[float]
    net_debt: Optional[float]                   # API field if present; else derived below

    shares_outstanding: Optional[float]         # diluted weighted-average shares

    # Long-term marketable securities. Declared LAST with a default so it is a real
    # class-level attribute: dataclass ordering forbids a defaulted field before the
    # non-defaulted ones above, and the default also means attribute access resolves to
    # None even for objects deserialized from an older cache that lacks the field.
    long_term_investments: Optional[float] = None

    @property
    def effective_tax_rate(self) -> Optional[float]:
        """Effective tax rate = tax expense / pre-tax income.

        Returns None when it cannot be computed safely (missing data, or non-positive
        pre-tax income which makes the ratio meaningless). The engine will fall back to a
        user/assumption tax rate in those cases — we do not fabricate one here.
        """
        if self.income_tax_expense is None or self.income_before_tax is None:
            return None
        if self.income_before_tax <= 0:
            return None
        return self.income_tax_expense / self.income_before_tax

    @property
    def derived_net_debt(self) -> Optional[float]:
        """Net debt, preferring the API's own field, else total debt − cash.

        Used for the Stage 1 display. For the valuation equity bridge use
        :meth:`net_debt_for_bridge`, which is explicit about long-term investments.
        Returns None if neither path has the data it needs.
        """
        if self.net_debt is not None:
            return self.net_debt
        if self.total_debt is not None and self.cash_and_st_investments is not None:
            return self.total_debt - self.cash_and_st_investments
        return None

    def net_debt_for_bridge(
        self, include_long_term_investments: bool = False
    ) -> Optional[float]:
        """Net debt used to bridge enterprise value → equity value.

        Computed explicitly from balance-sheet components (NOT the API's ``netDebt``
        field, whose cash definition varies), so the treatment of marketable securities
        is unambiguous:

            net debt = total debt − cash & short-term investments
                       [− long-term investments, if included]

        The default (``include_long_term_investments=False``) matches the conventional
        definition and the Stage 1 display. The toggle exists because that conventional
        definition **excludes long-term marketable securities**, which is material for
        cash-rich companies (e.g. Apple historically held tens of billions in long-term
        securities). Including them lowers net debt and therefore *raises* equity value.

        Returns None if total debt or cash is missing. If long-term investments are
        requested but unavailable, they are treated as 0 (i.e. excluded) — we never
        invent the figure.
        """
        if self.total_debt is None or self.cash_and_st_investments is None:
            return None
        nd = self.total_debt - self.cash_and_st_investments
        if include_long_term_investments and self.long_term_investments is not None:
            nd -= self.long_term_investments
        return nd


@dataclass(frozen=True)
class CompanyFinancials:
    """A company's profile plus a history of fiscal years, newest first.

    `years[0]` is the most recent fiscal year. The Stage 2 DCF seeds its driver defaults
    (revenue growth, margins, capex/D&A/NWC ratios) from this history.
    """

    profile: CompanyProfile
    years: list[FinancialYear] = field(default_factory=list)

    @property
    def latest(self) -> Optional[FinancialYear]:
        return self.years[0] if self.years else None


# ======================================================================================
# WACC (CAPM) models
# ======================================================================================
@dataclass(frozen=True)
class WACCResult:
    """Every component behind a weighted-average cost of capital, for transparency.

    Weights are market-value based: equity weight from market cap, debt weight from total
    debt. All rates are decimals (0.0875 == 8.75%).
    """

    risk_free_rate: float
    beta: float
    equity_risk_premium: float
    cost_of_equity: float            # CAPM: rf + beta * ERP

    pretax_cost_of_debt: float
    tax_rate: float
    after_tax_cost_of_debt: float    # pretax_kd * (1 - tax)

    equity_value: float              # E (market cap)
    debt_value: float                # D (total debt)
    equity_weight: float             # E / (E + D)
    debt_weight: float               # D / (E + D)

    wacc: float                      # wE*Ke + wD*Kd_aftertax


# ======================================================================================
# DCF models
# ======================================================================================
@dataclass(frozen=True)
class DCFAssumptions:
    """Inputs to the driver-based, two-stage unlevered-FCFF DCF.

    Ratios are decimals. `capex_pct_revenue` is a POSITIVE magnitude (capex is treated as
    a cash outflow and subtracted by the engine). `nwc_pct_incremental_revenue` is the
    increase in net working capital per dollar of *incremental* revenue (a use of cash,
    subtracted). `revenue_growth` is applied each forecast year unless `revenue_growth_path`
    (one rate per year) is supplied.
    """

    base_revenue: float
    forecast_years: int
    ebit_margin: float
    da_pct_revenue: float
    capex_pct_revenue: float
    nwc_pct_incremental_revenue: float
    tax_rate: float
    wacc: float
    terminal_growth: float
    net_debt: float
    shares_outstanding: float
    revenue_growth: float = 0.0
    revenue_growth_path: Optional[list[float]] = None


@dataclass(frozen=True)
class DCFYear:
    """One explicit forecast year of the DCF, with every intermediate number exposed."""

    year: int                  # 1..N
    revenue: float
    ebit: float
    nopat: float               # EBIT * (1 - tax)
    depreciation_amortization: float
    capex: float               # positive magnitude (outflow)
    change_in_nwc: float       # positive = cash used
    fcff: float                # NOPAT + D&A - capex - ΔNWC
    discount_factor: float     # 1 / (1+WACC)^year
    pv_fcff: float


@dataclass(frozen=True)
class DCFResult:
    years: list[DCFYear]
    sum_pv_fcff: float
    terminal_value: float          # undiscounted, at year N (Gordon growth)
    pv_terminal_value: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    shares_outstanding: float
    value_per_share: float
    assumptions: DCFAssumptions
    notes: list[str] = field(default_factory=list)


# ======================================================================================
# LBO models
# ======================================================================================
@dataclass(frozen=True)
class LBOAssumptions:
    """Inputs to the simple, 100%-cash-sweep LBO.

    Multiples are EV/EBITDA. `entry_leverage` is opening debt as a multiple of entry
    EBITDA (Debt0 = entry_leverage * entry_ebitda). D&A, capex and ΔNWC are expressed as
    fractions of that year's EBITDA. Rates/fractions are decimals.
    """

    entry_ebitda: float
    entry_ev_ebitda: float
    exit_ev_ebitda: float
    entry_leverage: float
    interest_rate: float
    hold_years: int
    ebitda_growth: float
    da_pct_ebitda: float
    capex_pct_ebitda: float
    nwc_pct_ebitda: float
    tax_rate: float
    transaction_fees_pct: float = 0.0   # as a fraction of entry EV
    min_cash: float = 0.0


@dataclass(frozen=True)
class LBOYear:
    """One year of the LBO debt schedule. All cash items are for that year."""

    year: int                  # 1..H
    ebitda: float
    depreciation_amortization: float
    interest: float            # on opening debt balance
    taxable_income: float      # EBITDA - D&A - interest  (the tax shield lives here)
    cash_taxes: float          # max(0, taxable_income) * tax
    capex: float               # positive magnitude
    change_in_nwc: float       # positive = cash used
    fcf_available: float       # EBITDA - interest - taxes - capex - ΔNWC
    debt_paydown: float
    ending_debt: float
    cash_balance: float        # accumulated excess cash after debt is repaid


@dataclass(frozen=True)
class LBOResult:
    # Entry / sources & uses
    entry_enterprise_value: float
    transaction_fees: float
    entry_debt: float
    sponsor_equity: float
    sources_and_uses: dict

    # Schedule
    schedule: list[LBOYear]

    # Exit / returns
    hold_years: int
    exit_ebitda: float
    exit_enterprise_value: float
    exit_net_debt: float
    exit_equity_value: float
    moic: float
    irr: float

    assumptions: LBOAssumptions
    notes: list[str] = field(default_factory=list)
