"""Monte Carlo price-risk engine — Geometric Brownian Motion (GBM).

Pure, deterministic, numpy-only finance: NO network calls and NO Streamlit imports, so it
unit-tests in isolation exactly like the DCF/LBO/WACC engines. It is deliberately kept
*separate* from the DCF fundamental valuation — this module simulates **market-price risk**
from the stock's own historical volatility, which is a different question from "what is the
business worth" that the DCF answers.

Method & conventions (stated explicitly so the numbers are auditable):

  * From a daily close series we take log returns r_t = ln(P_t / P_{t-1}).
  * We annualize with ``TRADING_DAYS`` (252) days/year:
        σ (sigma) = stdev(r) · √252                     — annualized volatility
        μ (mu)    = mean(r)·252 + ½σ²                    — annualized GBM drift
    (The ½σ² term converts the mean *log* return into the GBM drift μ in
     dS = μ·S·dt + σ·S·dW, so the simulated daily log-step mean equals the sample mean.)
  * We simulate ``N_PATHS`` (10,000) GBM paths over ``HORIZON_DAYS`` (252 ≈ 1 year) forward
    from the current price, using the exact log-Euler update
        ln S_{t+1} = ln S_t + (μ − ½σ²)·dt + σ·√dt·Z,  Z ~ N(0,1),  dt = 1/252.
  * From the terminal-price distribution we compute, at ``CONFIDENCE`` = 95% over a
    **1-year horizon**, expressed as a positive % loss from the current price:
        VaR  = (P0 − Q)·/P0           where Q = 5th percentile of terminal price
        ES   = mean over the worst 5% of terminal prices of (P0 − P_T)/P0
    By construction ES ≥ VaR (Expected Shortfall sits deeper in the left tail).

GBM is a teaching-grade model: it assumes lognormal returns and *constant* volatility, so
it understates real tail risk (no fat tails, no vol clustering). The UI says so plainly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# --------------------------------------------------------------------------------------
# Conventions — the single source of truth for the risk numbers (1-year horizon, 95%).
# --------------------------------------------------------------------------------------
TRADING_DAYS = 252        # trading days per year (annualization factor)
HORIZON_DAYS = 252        # simulate 1 year forward
N_PATHS = 10_000          # number of Monte Carlo paths
CONFIDENCE = 0.95         # VaR / ES confidence level
_TAIL = 1.0 - CONFIDENCE  # 0.05 — the left-tail mass used for VaR/ES
DEFAULT_SEED = 12345      # fixed by default so the UI cone is stable across reruns


@dataclass(frozen=True)
class GBMParams:
    """Annualized GBM parameters estimated from a historical daily close series."""

    mu: float            # annualized drift (GBM convention; see module docstring)
    sigma: float         # annualized volatility
    mean_daily_log_return: float
    n_returns: int       # number of log returns the estimate is built from


@dataclass(frozen=True)
class PriceRiskResult:
    """Outcome of the Monte Carlo price-risk simulation.

    Losses are positive numbers meaning a fall from the current price (e.g. ``var_pct =
    0.34`` is a 34% loss). All conventions (horizon, confidence) are attached so the UI can
    label honestly without hard-coding them.
    """

    current_price: float
    params: GBMParams
    horizon_days: int
    n_paths: int
    confidence: float

    var_pct: float       # 95% Value at Risk, as a % loss from current price
    es_pct: float        # 95% Expected Shortfall (CVaR), as a % loss from current price
    var_price: float     # terminal price at the VaR threshold (the 5th percentile)
    es_price: float      # mean terminal price within the worst 5% tail

    times_years: np.ndarray            # (HORIZON_DAYS+1,) — 0 … 1.0 in steps of 1/252
    bands: dict[str, np.ndarray]       # percentile path bands: keys p5,p25,p50,p75,p95
    terminal_prices: np.ndarray        # (n_paths,) — the terminal-price distribution


def estimate_gbm_params(
    prices: np.ndarray | list[float], trading_days: int = TRADING_DAYS
) -> GBMParams:
    """Estimate annualized drift μ and volatility σ from a daily close series.

    ``prices`` is chronological (oldest → newest). Needs at least two positive prices.
    """
    arr = np.asarray(prices, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        raise ValueError("Need at least two prices to estimate returns.")
    if np.any(arr <= 0):
        raise ValueError("Prices must be strictly positive to take log returns.")

    log_returns = np.diff(np.log(arr))
    if log_returns.size < 1:
        raise ValueError("Not enough returns to estimate parameters.")

    mean_daily = float(np.mean(log_returns))
    # Sample standard deviation (ddof=1); guard the single-return edge case.
    std_daily = float(np.std(log_returns, ddof=1)) if log_returns.size > 1 else 0.0

    sigma = std_daily * np.sqrt(trading_days)
    mu = mean_daily * trading_days + 0.5 * sigma**2  # mean log return → GBM drift
    return GBMParams(
        mu=mu,
        sigma=sigma,
        mean_daily_log_return=mean_daily,
        n_returns=int(log_returns.size),
    )


def simulate_gbm_paths(
    current_price: float,
    params: GBMParams,
    horizon_days: int = HORIZON_DAYS,
    n_paths: int = N_PATHS,
    trading_days: int = TRADING_DAYS,
    seed: int | None = DEFAULT_SEED,
) -> np.ndarray:
    """Simulate ``n_paths`` GBM price paths, returning shape ``(n_paths, horizon_days+1)``.

    Column 0 is ``current_price`` for every path; column t is the simulated price after t
    trading days. Uses the exact log-Euler update so the discretization is unbiased.
    """
    if current_price <= 0:
        raise ValueError("current_price must be positive.")
    if horizon_days < 1 or n_paths < 1:
        raise ValueError("horizon_days and n_paths must be >= 1.")

    rng = np.random.default_rng(seed)
    dt = 1.0 / trading_days
    drift = (params.mu - 0.5 * params.sigma**2) * dt
    diffusion = params.sigma * np.sqrt(dt)

    shocks = rng.standard_normal(size=(n_paths, horizon_days))
    log_steps = drift + diffusion * shocks
    log_paths = np.cumsum(log_steps, axis=1)
    prices = current_price * np.exp(log_paths)

    # Prepend the starting price as column 0.
    start = np.full((n_paths, 1), current_price, dtype=float)
    return np.hstack([start, prices])


def _percentile_bands(paths: np.ndarray) -> dict[str, np.ndarray]:
    """Per-time-step percentile bands across all paths (for the probability cone)."""
    pcts = {"p5": 5, "p25": 25, "p50": 50, "p75": 75, "p95": 95}
    return {key: np.percentile(paths, q, axis=0) for key, q in pcts.items()}


def run_price_risk(
    prices: np.ndarray | list[float],
    current_price: float | None = None,
    horizon_days: int = HORIZON_DAYS,
    n_paths: int = N_PATHS,
    confidence: float = CONFIDENCE,
    trading_days: int = TRADING_DAYS,
    seed: int | None = DEFAULT_SEED,
) -> PriceRiskResult:
    """Run the full price-risk simulation from a historical daily close series.

    ``prices`` is chronological (oldest → newest). ``current_price`` defaults to the last
    price in the series. Returns a :class:`PriceRiskResult` with VaR, ES, percentile bands
    and the terminal-price distribution. See the module docstring for every convention.
    """
    arr = np.asarray(prices, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        raise ValueError("Need at least two prices to run the simulation.")

    p0 = float(arr[-1]) if current_price is None else float(current_price)
    if p0 <= 0:
        raise ValueError("current_price must be positive.")

    params = estimate_gbm_params(arr, trading_days=trading_days)
    paths = simulate_gbm_paths(
        p0, params, horizon_days=horizon_days, n_paths=n_paths,
        trading_days=trading_days, seed=seed,
    )

    terminal = paths[:, -1]
    tail = 1.0 - confidence

    # VaR: loss at the (1-confidence) percentile of terminal price.
    var_price = float(np.percentile(terminal, tail * 100.0))
    var_pct = (p0 - var_price) / p0

    # ES / CVaR: mean loss within the worst (1-confidence) tail. Use <= the VaR threshold;
    # fall back to the single worst path if the tail rounds to empty (tiny n_paths).
    tail_mask = terminal <= var_price
    tail_prices = terminal[tail_mask] if np.any(tail_mask) else np.array([terminal.min()])
    es_price = float(np.mean(tail_prices))
    es_pct = (p0 - es_price) / p0

    times_years = np.arange(horizon_days + 1, dtype=float) / trading_days

    return PriceRiskResult(
        current_price=p0,
        params=params,
        horizon_days=horizon_days,
        n_paths=n_paths,
        confidence=confidence,
        var_pct=var_pct,
        es_pct=es_pct,
        var_price=var_price,
        es_price=es_price,
        times_years=times_years,
        bands=_percentile_bands(paths),
        terminal_prices=terminal,
    )
