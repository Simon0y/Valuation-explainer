"""Map raw FMP JSON into `engine.models` dataclasses.

Field names differ slightly across FMP's stable and legacy endpoints (and across plan
tiers), so every lookup goes through `_first`, which tries a list of candidate keys and
returns the first one present. Missing fields become ``None`` rather than fabricated
values — the UI shows the gap honestly.

This module performs NO finance math. It only renames/relocates fields and applies the
documented sign conventions exactly as the API reports them (it does not flip signs).
"""

from __future__ import annotations

from typing import Any, Optional

from engine.models import CompanyFinancials, CompanyProfile, FinancialYear
from data.fmp_client import FMPClient

# Endpoint names are shared between stable and legacy; the client handles URL shape.
EP_PROFILE = "profile"
EP_INCOME = "income-statement"
EP_CASHFLOW = "cash-flow-statement"
EP_BALANCE = "balance-sheet-statement"


def _first(row: dict, *keys: str) -> Optional[Any]:
    """Return the first present, non-null value among ``keys`` in ``row``."""
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _num(value: Any) -> Optional[float]:
    """Coerce to float, returning None for missing/blank/non-numeric values."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_profile(client: FMPClient, symbol: str) -> CompanyProfile:
    """Fetch and map the company profile."""
    row = client.get(EP_PROFILE, symbol)[0]
    return CompanyProfile(
        symbol=str(_first(row, "symbol") or symbol).upper(),
        name=str(_first(row, "companyName", "name") or symbol),
        description=str(_first(row, "description") or ""),
        sector=str(_first(row, "sector") or "—"),
        industry=str(_first(row, "industry") or "—"),
        currency=str(_first(row, "currency", "reportedCurrency") or "—"),
        market_cap=_num(_first(row, "marketCap", "mktCap")),
        price=_num(_first(row, "price")),
        beta=_num(_first(row, "beta")),
        website=_first(row, "website"),
        exchange=_first(row, "exchangeShortName", "exchange"),
    )


def _index_by_year(rows: list[dict]) -> dict[str, dict]:
    """Index statement rows by their fiscal-year/date label for cross-statement joins.

    Different statements for the same company share the `calendarYear`/`date` label, so we
    use it to line up income, cash-flow and balance-sheet rows for the same period.
    """
    indexed: dict[str, dict] = {}
    for row in rows:
        label = (
            _first(row, "calendarYear")
            or _first(row, "fiscalYear")
            or _first(row, "date")
        )
        if label is not None:
            indexed[str(label)] = row
    return indexed


def fetch_financials(
    client: FMPClient, symbol: str, limit: int = 5
) -> CompanyFinancials:
    """Fetch profile + up to ``limit`` years of statements and assemble the history.

    Returns a `CompanyFinancials` with `years` newest-first. Years are built only from the
    fiscal labels present on the income statement; cash-flow and balance-sheet figures are
    joined in by matching label, and are left as ``None`` where unavailable.
    """
    profile = fetch_profile(client, symbol)

    income_rows = client.get(EP_INCOME, symbol, limit=limit, period="annual")
    # Cash-flow and balance-sheet are best-effort: a limited plan may reject them, and we
    # still want to show whatever the income statement gave us.
    try:
        cashflow_by_year = _index_by_year(
            client.get(EP_CASHFLOW, symbol, limit=limit, period="annual")
        )
    except Exception:
        cashflow_by_year = {}
    try:
        balance_by_year = _index_by_year(
            client.get(EP_BALANCE, symbol, limit=limit, period="annual")
        )
    except Exception:
        balance_by_year = {}

    years: list[FinancialYear] = []
    for inc in income_rows:
        label = str(
            _first(inc, "calendarYear") or _first(inc, "fiscalYear") or _first(inc, "date")
        )
        cf = cashflow_by_year.get(label, {})
        bs = balance_by_year.get(label, {})

        years.append(
            FinancialYear(
                fiscal_year=label,
                period=str(_first(inc, "period") or "FY"),
                reported_currency=str(
                    _first(inc, "reportedCurrency") or profile.currency
                ),
                revenue=_num(_first(inc, "revenue")),
                ebit=_num(_first(inc, "operatingIncome", "ebit")),
                ebitda=_num(_first(inc, "ebitda", "EBITDA")),
                # D&A: prefer the cash-flow figure (the true non-cash add-back); fall back
                # to the income-statement line if cash flow is unavailable.
                depreciation_amortization=_num(
                    _first(cf, "depreciationAndAmortization")
                    or _first(inc, "depreciationAndAmortization")
                ),
                capex=_num(_first(cf, "capitalExpenditure")),  # negative as reported
                change_in_working_capital=_num(
                    _first(cf, "changeInWorkingCapital")
                ),
                income_before_tax=_num(
                    _first(inc, "incomeBeforeTax", "preTaxIncome")
                ),
                income_tax_expense=_num(_first(inc, "incomeTaxExpense")),
                total_debt=_num(_first(bs, "totalDebt")),
                cash_and_st_investments=_num(
                    _first(bs, "cashAndShortTermInvestments", "cashAndCashEquivalents")
                ),
                long_term_investments=_num(_first(bs, "longTermInvestments")),
                net_debt=_num(_first(bs, "netDebt")),
                shares_outstanding=_num(
                    _first(
                        inc,
                        "weightedAverageShsOutDil",
                        "weightedAverageShsOut",
                    )
                ),
            )
        )

    return CompanyFinancials(profile=profile, years=years)
