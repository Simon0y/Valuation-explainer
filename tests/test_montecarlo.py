"""Tests for the Monte Carlo price-risk engine (GBM).

These run on SYNTHETIC price series only — no network. A fixed seed makes the simulation
deterministic so the assertions are stable. The core invariants checked are:

  * VaR and ES are finite, real numbers.
  * ES is a LARGER loss than VaR (Expected Shortfall sits deeper in the left tail).
  * The percentile bands are correctly ordered (p5 ≤ p25 ≤ p50 ≤ p75 ≤ p95) at every step.
  * Estimation recovers a known drift/volatility from a synthetic GBM series.
"""

import math

import numpy as np
import pytest

from engine.montecarlo import (
    CONFIDENCE,
    HORIZON_DAYS,
    TRADING_DAYS,
    estimate_gbm_params,
    run_price_risk,
    simulate_gbm_paths,
)


def _synthetic_gbm_series(
    s0: float = 100.0,
    mu: float = 0.08,
    sigma: float = 0.25,
    n_days: int = 756,  # ~3 years of trading days
    seed: int = 42,
) -> np.ndarray:
    """Generate a synthetic daily close series from a known GBM, oldest → newest."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / TRADING_DAYS
    steps = (mu - 0.5 * sigma**2) * dt + sigma * math.sqrt(dt) * rng.standard_normal(n_days)
    return s0 * np.exp(np.cumsum(np.concatenate([[0.0], steps])))


def test_estimate_recovers_known_params():
    # A long synthetic GBM series should recover its drift/vol within sampling error.
    series = _synthetic_gbm_series(mu=0.10, sigma=0.30, n_days=20_000, seed=7)
    p = estimate_gbm_params(series)
    assert math.isclose(p.sigma, 0.30, rel_tol=0.05)
    assert abs(p.mu - 0.10) < 0.05
    assert p.n_returns == 20_000


def test_var_es_finite_and_es_deeper_than_var():
    series = _synthetic_gbm_series()
    res = run_price_risk(series, seed=123)

    assert np.isfinite(res.var_pct)
    assert np.isfinite(res.es_pct)
    assert np.isfinite(res.var_price)
    assert np.isfinite(res.es_price)

    # ES (CVaR) must be a strictly larger loss than VaR — it averages the worst tail,
    # which lies beyond the VaR cutoff.
    assert res.es_pct > res.var_pct
    # Equivalently, the average tail price is below the VaR threshold price.
    assert res.es_price < res.var_price


def test_var_es_losses_are_positive_for_one_year_horizon():
    # A 95% one-year VaR on a 25%-vol stock should be a real (positive) loss.
    series = _synthetic_gbm_series(sigma=0.25)
    res = run_price_risk(series, seed=1)
    assert 0.0 < res.var_pct < 1.0
    assert 0.0 < res.es_pct < 1.0


def test_percentile_bands_ordered_at_every_step():
    series = _synthetic_gbm_series()
    res = run_price_risk(series, seed=99)
    b = res.bands
    # Each band has one point per day including t=0.
    assert all(b[k].shape == (HORIZON_DAYS + 1,) for k in ("p5", "p25", "p50", "p75", "p95"))
    assert np.all(b["p5"] <= b["p25"] + 1e-9)
    assert np.all(b["p25"] <= b["p50"] + 1e-9)
    assert np.all(b["p50"] <= b["p75"] + 1e-9)
    assert np.all(b["p75"] <= b["p95"] + 1e-9)


def test_bands_start_at_current_price():
    series = _synthetic_gbm_series(s0=250.0)
    res = run_price_risk(series, seed=5)
    # All paths start at the current price, so every band equals it at t=0.
    for k in ("p5", "p25", "p50", "p75", "p95"):
        assert math.isclose(res.bands[k][0], res.current_price, rel_tol=1e-9)
    assert math.isclose(res.current_price, float(series[-1]), rel_tol=1e-12)


def test_result_metadata_matches_conventions():
    series = _synthetic_gbm_series()
    res = run_price_risk(series, seed=3)
    assert res.horizon_days == HORIZON_DAYS
    assert res.n_paths == 10_000
    assert res.confidence == CONFIDENCE
    assert res.terminal_prices.shape == (10_000,)
    assert math.isclose(res.times_years[-1], 1.0, rel_tol=1e-9)


def test_seed_is_reproducible():
    series = _synthetic_gbm_series()
    a = run_price_risk(series, seed=2024)
    b = run_price_risk(series, seed=2024)
    assert a.var_pct == b.var_pct
    assert a.es_pct == b.es_pct
    assert np.array_equal(a.terminal_prices, b.terminal_prices)


def test_higher_volatility_means_larger_var():
    low = run_price_risk(_synthetic_gbm_series(sigma=0.15), seed=8)
    high = run_price_risk(_synthetic_gbm_series(sigma=0.45), seed=8)
    assert high.var_pct > low.var_pct
    assert high.es_pct > low.es_pct


def test_simulate_shape_and_start_column():
    p = estimate_gbm_params(_synthetic_gbm_series())
    paths = simulate_gbm_paths(100.0, p, horizon_days=50, n_paths=200, seed=0)
    assert paths.shape == (200, 51)
    assert np.allclose(paths[:, 0], 100.0)


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        estimate_gbm_params([100.0])  # need >= 2 prices
    with pytest.raises(ValueError):
        estimate_gbm_params([100.0, -5.0])  # non-positive price
    with pytest.raises(ValueError):
        run_price_risk([100.0])  # need >= 2 prices
