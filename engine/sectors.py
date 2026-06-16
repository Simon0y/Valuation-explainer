"""Sector classification helpers — pure, string-based, no I/O.

Used to decide when a standard unlevered-FCFF DCF and an EV/EBITDA multiple are
inappropriate for a company, so the UI can show an honest note instead of printing a
misleading fair value.

The canonical case is **financials** (banks, insurers, capital markets). For these:
  * debt is raw material, not financing — "net debt" is meaningless, so the EV→equity
    bridge and EV/EBITDA break down, and
  * free cash flow to the firm isn't defined the conventional way,
so a textbook FCFF DCF produces a number that looks precise but is not economically
meaningful. We detect the sector from the profile and flag it rather than hide the math.
"""

from __future__ import annotations

from typing import Optional

# Sector/industry substrings (lower-cased) that mark a financial business. FMP labels
# banks, insurers and capital-markets firms under the "Financial Services" sector, but we
# also match the common industry words so the check is robust across data sources/tiers.
_FINANCIAL_MARKERS = (
    "financial services",
    "bank",
    "insurance",
    "insurer",
    "capital markets",
    "asset management",
    "mortgage",
    "credit services",
)


def is_financial(sector: Optional[str], industry: Optional[str]) -> bool:
    """True when the company looks like a bank/insurer/financial, where a standard FCFF
    DCF and EV/EBITDA do not apply well. Matches on sector OR industry text, case-insensitively."""
    text = f"{sector or ''} | {industry or ''}".lower()
    return any(marker in text for marker in _FINANCIAL_MARKERS)
