"""Tests for the FMP price-history parser — fully offline via a stub client (no network).

Verifies it handles both FMP response shapes (stable bare list, legacy ``historical``
wrapper), sorts oldest → newest, drops bad rows, and caps the point count.
"""

import pytest

from data.fmp_client import FMPNotFound
from data.prices import fetch_price_history


class _StubClient:
    """Stands in for FMPClient.get, returning canned payloads keyed by endpoint name."""

    def __init__(self, payloads: dict):
        self._payloads = payloads

    def get(self, endpoint: str, symbol: str, **_):
        if endpoint not in self._payloads:
            raise FMPNotFound(f"no endpoint {endpoint}")
        return self._payloads[endpoint]


def test_parses_stable_bare_list_and_sorts_oldest_first():
    payload = [
        {"date": "2024-01-03", "close": 102.0},
        {"date": "2024-01-01", "close": 100.0},
        {"date": "2024-01-02", "close": 101.0},
    ]
    client = _StubClient({"historical-price-eod/full": payload})
    prices = fetch_price_history(client, "TEST")
    assert prices == [100.0, 101.0, 102.0]


def test_parses_legacy_historical_wrapper():
    payload = [{"symbol": "TEST", "historical": [
        {"date": "2024-01-02", "close": 50.0},
        {"date": "2024-01-01", "close": 49.0},
    ]}]
    # Only the legacy endpoint name has data; the stable one is absent → falls back.
    client = _StubClient({"historical-price-full": payload})
    prices = fetch_price_history(client, "TEST")
    assert prices == [49.0, 50.0]


def test_drops_nonpositive_and_missing_closes():
    payload = [
        {"date": "2024-01-01", "close": 100.0},
        {"date": "2024-01-02", "close": 0.0},      # dropped
        {"date": "2024-01-03", "close": None},     # dropped
        {"date": "2024-01-04", "close": 103.0},
    ]
    client = _StubClient({"historical-price-eod/full": payload})
    assert fetch_price_history(client, "TEST") == [100.0, 103.0]


def test_caps_to_max_points():
    payload = [{"date": f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", "close": float(i + 1)}
               for i in range(300)]
    client = _StubClient({"historical-price-eod/full": payload})
    prices = fetch_price_history(client, "TEST", max_points=50)
    assert len(prices) == 50
    assert prices[-1] == 300.0  # kept the most recent


def test_raises_when_no_usable_data():
    client = _StubClient({"historical-price-eod/full": [{"date": "2024-01-01", "close": None}]})
    with pytest.raises(FMPNotFound):
        fetch_price_history(client, "TEST")
