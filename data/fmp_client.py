"""Thin HTTP client for the Financial Modeling Prep (FMP) API.

The user's FMP plan tier is unknown, so this client is deliberately defensive:

  * It tries the modern ``/stable`` endpoint first, then falls back to the legacy
    ``/api/v3`` endpoint. The two use different URL shapes (query param vs path segment)
    but largely share JSON field names, which is why the `fundamentals` layer can map
    either response the same way.
  * HTTP status codes are mapped to typed exceptions so the UI can show a precise,
    friendly banner instead of a stack trace.

This module does no parsing of *meaning* — it returns raw decoded JSON. Mapping JSON into
engine models is `fundamentals.py`'s job.
"""

from __future__ import annotations

import requests

STABLE_BASE = "https://financialmodelingprep.com/stable"
LEGACY_BASE = "https://financialmodelingprep.com/api/v3"

DEFAULT_TIMEOUT = 15  # seconds


class FMPError(Exception):
    """Base class for all FMP client errors."""


class FMPAuthError(FMPError):
    """Invalid or missing API key (HTTP 401)."""


class FMPPlanError(FMPError):
    """Endpoint or data not available on the current plan (HTTP 403)."""


class FMPRateLimitError(FMPError):
    """Rate / quota limit hit (HTTP 429)."""


class FMPNotFound(FMPError):
    """Ticker or resource not found, or the API returned an empty result."""


def _raise_for_status(resp: requests.Response, symbol: str) -> None:
    """Translate an HTTP error status into a typed FMPError with a clear message."""
    status = resp.status_code
    if status == 200:
        return
    if status == 401:
        raise FMPAuthError(
            "FMP rejected the API key (401). Check that FMP_API_KEY is set correctly."
        )
    if status == 403:
        raise FMPPlanError(
            "FMP returned 403 — this endpoint or history depth is not available on your "
            "current plan. Try a different ticker or a smaller request."
        )
    if status == 402:
        # Payment Required — a plan limitation (e.g. the free tier caps the `limit`
        # query parameter). Include the body so callers can parse the allowed maximum
        # and retry at a smaller limit.
        raise FMPPlanError(f"FMP plan limit (402): {resp.text[:200]}")
    if status == 429:
        raise FMPRateLimitError(
            "FMP rate limit hit (429). You've exceeded the calls allowed for your plan; "
            "wait a bit and try again."
        )
    if status == 404:
        raise FMPNotFound(f"FMP returned 404 for '{symbol}'.")
    # Anything else: surface the status and a snippet of the body.
    raise FMPError(f"FMP request failed ({status}): {resp.text[:200]}")


class FMPClient:
    """Fetches raw JSON from FMP, transparently handling stable vs legacy endpoints.

    Parameters
    ----------
    api_key:
        The FMP API key. Passed in explicitly (never read from global state) so the
        client stays testable and the key handling lives entirely in the UI layer.
    session:
        Optional pre-built ``requests.Session`` (useful for tests / connection reuse).
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise FMPAuthError("No FMP API key provided.")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._timeout = timeout

    def _request(self, url: str, params: dict) -> list | dict:
        """Issue one GET and decode JSON, mapping transport errors to FMPError."""
        try:
            resp = self._session.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:  # network down, DNS, timeout, etc.
            raise FMPError(f"Network error contacting FMP: {exc}") from exc
        _raise_for_status(resp, params.get("symbol", ""))
        try:
            return resp.json()
        except ValueError as exc:
            raise FMPError("FMP returned a non-JSON response.") from exc

    def get(self, endpoint: str, symbol: str, **extra_params) -> list:
        """Fetch ``endpoint`` for ``symbol``, trying stable then legacy.

        FMP also sometimes returns a 200 with an ``{"Error Message": ...}`` body for an
        unknown ticker or a plan restriction; we detect that shape and raise too.

        Returns the decoded JSON list (statement endpoints return a list of period rows;
        `profile` returns a single-element list).
        """
        symbol = symbol.strip().upper()

        # 1) Modern /stable: ?symbol=AAPL&apikey=...
        stable_url = f"{STABLE_BASE}/{endpoint}"
        stable_params = {"symbol": symbol, "apikey": self._api_key, **extra_params}
        try:
            data = self._request(stable_url, stable_params)
            return self._unwrap(data, symbol)
        except (FMPNotFound, FMPPlanError):
            # Fall through to legacy — stable may not expose this endpoint on this plan.
            pass

        # 2) Legacy /api/v3: /endpoint/AAPL?apikey=...
        legacy_url = f"{LEGACY_BASE}/{endpoint}/{symbol}"
        legacy_params = {"apikey": self._api_key, **extra_params}
        data = self._request(legacy_url, legacy_params)
        return self._unwrap(data, symbol)

    @staticmethod
    def _unwrap(data: list | dict, symbol: str) -> list:
        """Normalize FMP's response into a list, raising on error/empty shapes."""
        # Error shape: {"Error Message": "..."} or {"message": "..."}
        if isinstance(data, dict):
            msg = data.get("Error Message") or data.get("message")
            if msg:
                lowered = msg.lower()
                if "limit" in lowered or "upgrade" in lowered or "plan" in lowered:
                    raise FMPPlanError(f"FMP: {msg}")
                if "api key" in lowered or "apikey" in lowered:
                    raise FMPAuthError(f"FMP: {msg}")
                raise FMPNotFound(f"FMP: {msg}")
            # Some endpoints return a bare object — wrap it.
            data = [data]
        if not isinstance(data, list) or len(data) == 0:
            raise FMPNotFound(f"FMP returned no data for '{symbol}'.")
        return data
