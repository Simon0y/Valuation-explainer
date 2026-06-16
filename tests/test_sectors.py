"""Tests for the financial-sector classifier used to gate the FCFF DCF / EV multiples."""

import pytest

from engine.sectors import is_financial


@pytest.mark.parametrize(
    "sector,industry",
    [
        ("Financial Services", "Banks - Diversified"),       # JPM, BAC
        ("Financial Services", "Insurance - Life"),
        ("Financial Services", "Capital Markets"),
        ("Financial Services", "Asset Management"),
        ("financial services", "banks"),                      # case-insensitive
    ],
)
def test_financials_detected(sector, industry):
    assert is_financial(sector, industry) is True


@pytest.mark.parametrize(
    "sector,industry",
    [
        ("Technology", "Consumer Electronics"),               # AAPL
        ("Communication Services", "Entertainment"),          # DIS
        ("Consumer Cyclical", "Auto - Manufacturers"),        # F, RIVN
        ("Consumer Defensive", "Beverages - Non-Alcoholic"),  # KO
        ("Healthcare", "Drug Manufacturers"),
    ],
)
def test_non_financials_pass_through(sector, industry):
    assert is_financial(sector, industry) is False


def test_missing_sector_industry_is_not_financial():
    assert is_financial(None, None) is False
    assert is_financial("", "") is False
