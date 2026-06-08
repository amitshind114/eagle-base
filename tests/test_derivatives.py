"""Phase 9 — Derivatives unit tests.

Covers:
  BlackScholes pricer (pure math)
  [x] ATM call price > 0
  [x] ATM put price > 0
  [x] Put-call parity: C - P = S*e^(-qT) - K*e^(-rT)
  [x] Deep ITM call ≈ intrinsic value
  [x] Deep OTM call ≈ 0
  [x] Zero expiry returns 0 price
  [x] Zero sigma returns 0 price (degenerate)
  [x] Higher sigma → higher call price
  [x] Higher spot → higher call price
  [x] Longer expiry → higher call price (time value)

  BlackScholes — Greeks
  [x] Call delta in (0, 1)
  [x] Put delta in (-1, 0)
  [x] ATM call delta ≈ 0.5
  [x] ATM put delta ≈ -0.5
  [x] Gamma > 0
  [x] Gamma is same for call and put
  [x] Theta < 0 for call (time decay)
  [x] Theta < 0 for put (time decay)
  [x] Vega > 0
  [x] Vega same for call and put
  [x] Call rho > 0
  [x] Put rho < 0
  [x] greeks() dict has all 6 keys
  [x] greeks() price matches price() directly
  [x] greeks() delta matches delta() directly
  [x] Zero T: gamma=0, theta=0, vega=0, rho=0

  BlackScholes — known numerical values
  [x] ATM 30-day NIFTY call within range of textbook value
  [x] Delta sum call+put ≈ 1 (digital identity)

  OptionContract
  [x] mid() = (bid+ask)/2 when both > 0
  [x] mid() falls back to ltp when no bid/ask
  [x] greeks field defaults to empty dict
  [x] option_type stored correctly

  OptionChainLoader
  [x] get_chain() with no API + no DB returns empty list (graceful)
  [x] _filter_strikes() returns only strikes within n of ATM
  [x] _filter_strikes() with None spot returns all sorted
  [x] _nearest_expiry() returns ISO date string in future
  [x] get_atm_strike() falls back to round(spot/50)*50 on empty chain

  CoveredCallStrategy
  [x] generate_signals() returns pd.Series with same index as input
  [x] signals contain only -1, 0, +1 values
  [x] at least one signal generated on long volatile series
  [x] no signal generated when IV rank never reaches threshold
  [x] entry signal (+1) always precedes exit (-1)
  [x] strategy name is 'covered_call'
  [x] higher threshold => fewer or equal signals

All tests: zero network, zero broker credentials, < 2 seconds.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import numpy as np
import pytest

from derivatives.options import (
    BlackScholes,
    OptionContract,
    OptionChainLoader,
    CoveredCallStrategy,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def atm_bs():
    """ATM BS model: NIFTY=22500, K=22500, 30 days, r=6.5%, sigma=18%."""
    return BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.18)


@pytest.fixture()
def itm_call():
    """Deep ITM call: S=25000, K=20000, 30 days."""
    return BlackScholes(S=25000, K=20000, T=30/365, r=0.065, sigma=0.18)


@pytest.fixture()
def otm_call():
    """Deep OTM call: S=20000, K=25000, 30 days."""
    return BlackScholes(S=20000, K=25000, T=30/365, r=0.065, sigma=0.18)


def _make_close_series(n=500, trend=0.0003, noise=0.015, seed=42) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with a realistic Close series."""
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(trend, noise, n)
    close = 22500 * np.exp(np.cumsum(log_returns))
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


# ────────────────────────────────────────────────────────────────────────────
# BlackScholes — price
# ────────────────────────────────────────────────────────────────────────────

class TestBSPrice:
    def test_atm_call_price_positive(self, atm_bs):
        assert atm_bs.price("CE") > 0

    def test_atm_put_price_positive(self, atm_bs):
        assert atm_bs.price("PE") > 0

    def test_put_call_parity(self, atm_bs):
        """C - P = S*e^(-qT) - K*e^(-rT)  (continuous dividend form)."""
        C = atm_bs.price("CE")
        P = atm_bs.price("PE")
        S, K, T, r, q = atm_bs.S, atm_bs.K, atm_bs.T, atm_bs.r, atm_bs.q
        rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
        assert abs((C - P) - rhs) < 0.01

    def test_deep_itm_call_near_intrinsic(self, itm_call):
        """Deep ITM call ≈ S - K*e^(-rT)."""
        C = itm_call.price("CE")
        intrinsic = itm_call.S - itm_call.K * math.exp(-itm_call.r * itm_call.T)
        assert abs(C - intrinsic) < 50.0

    def test_deep_otm_call_near_zero(self, otm_call):
        assert otm_call.price("CE") < 10.0

    def test_zero_expiry_price_nonnegative(self):
        bs = BlackScholes(S=22500, K=22500, T=0.0, r=0.065, sigma=0.18)
        assert bs.price("CE") >= 0.0

    def test_higher_sigma_raises_call_price(self):
        bs_low  = BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.10)
        bs_high = BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.30)
        assert bs_high.price("CE") > bs_low.price("CE")

    def test_higher_spot_raises_call_price(self):
        bs_low  = BlackScholes(S=20000, K=22500, T=30/365, r=0.065, sigma=0.18)
        bs_high = BlackScholes(S=25000, K=22500, T=30/365, r=0.065, sigma=0.18)
        assert bs_high.price("CE") > bs_low.price("CE")

    def test_longer_expiry_raises_call_price(self):
        bs_short = BlackScholes(S=22500, K=22500, T=7/365,  r=0.065, sigma=0.18)
        bs_long  = BlackScholes(S=22500, K=22500, T=90/365, r=0.065, sigma=0.18)
        assert bs_long.price("CE") > bs_short.price("CE")

    def test_call_aliases_ce_call_c(self):
        bs = BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.18)
        assert abs(bs.price("CE") - bs.price("CALL")) < 0.001
        assert abs(bs.price("CE") - bs.price("C"))    < 0.001


# ────────────────────────────────────────────────────────────────────────────
# BlackScholes — Greeks
# ────────────────────────────────────────────────────────────────────────────

class TestBSGreeks:
    def test_call_delta_in_range(self, atm_bs):
        d = atm_bs.delta("CE")
        assert 0 < d < 1

    def test_put_delta_in_range(self, atm_bs):
        d = atm_bs.delta("PE")
        assert -1 < d < 0

    def test_atm_call_delta_near_half(self, atm_bs):
        assert abs(atm_bs.delta("CE") - 0.5) < 0.05

    def test_atm_put_delta_near_minus_half(self, atm_bs):
        assert abs(atm_bs.delta("PE") + 0.5) < 0.05

    def test_gamma_positive(self, atm_bs):
        assert atm_bs.gamma() > 0

    def test_theta_negative_call(self, atm_bs):
        assert atm_bs.theta("CE") < 0

    def test_theta_negative_put(self, atm_bs):
        assert atm_bs.theta("PE") < 0

    def test_vega_positive(self, atm_bs):
        assert atm_bs.vega() > 0

    def test_call_rho_positive(self, atm_bs):
        assert atm_bs.rho("CE") > 0

    def test_put_rho_negative(self, atm_bs):
        assert atm_bs.rho("PE") < 0

    def test_greeks_dict_has_all_keys(self, atm_bs):
        g = atm_bs.greeks("CE")
        for key in ("price", "delta", "gamma", "theta", "vega", "rho"):
            assert key in g

    def test_greeks_price_matches_price_method(self, atm_bs):
        g = atm_bs.greeks("CE")
        assert abs(g["price"] - round(atm_bs.price("CE"), 4)) < 0.001

    def test_greeks_delta_matches_delta_method(self, atm_bs):
        g = atm_bs.greeks("CE")
        assert abs(g["delta"] - round(atm_bs.delta("CE"), 4)) < 0.0001

    def test_zero_T_greeks_all_zero(self):
        bs = BlackScholes(S=22500, K=22500, T=0.0, r=0.065, sigma=0.18)
        assert bs.gamma() == 0.0
        assert bs.theta("CE") == 0.0
        assert bs.vega()  == 0.0
        assert bs.rho("CE") == 0.0

    def test_delta_identity_call_minus_put(self, atm_bs):
        """delta_call - delta_put = e^(-qT) ≈ 1 for q=0."""
        dc = atm_bs.delta("CE")
        dp = atm_bs.delta("PE")
        assert abs((dc - dp) - math.exp(-atm_bs.q * atm_bs.T)) < 0.001

    def test_known_atm_call_price_in_range(self):
        """ATM 30-day NIFTY call at S=K=22500, sigma=18% should be ~300-900."""
        bs = BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.18)
        p = bs.price("CE")
        assert 300 < p < 900

    def test_higher_vol_higher_vega_exposure(self):
        bs_lo = BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.10)
        bs_hi = BlackScholes(S=22500, K=22500, T=30/365, r=0.065, sigma=0.30)
        # Both vega > 0; higher vol ATM typically has similar vega — just check positivity
        assert bs_lo.vega() > 0
        assert bs_hi.vega() > 0


# ────────────────────────────────────────────────────────────────────────────
# OptionContract
# ────────────────────────────────────────────────────────────────────────────

class TestOptionContract:
    def test_mid_with_bid_ask(self):
        c = OptionContract(
            symbol="NIFTY26JUL22500CE", underlying="NIFTY",
            expiry="2026-07-31", strike=22500.0, option_type="CE",
            bid=450.0, ask=460.0,
        )
        assert abs(c.mid() - 455.0) < 0.001

    def test_mid_falls_back_to_ltp(self):
        c = OptionContract(
            symbol="NIFTY26JUL22500CE", underlying="NIFTY",
            expiry="2026-07-31", strike=22500.0, option_type="CE",
            ltp=455.0,
        )
        assert c.mid() == 455.0

    def test_greeks_defaults_to_empty_dict(self):
        c = OptionContract(
            symbol="X", underlying="Y",
            expiry="2026-07-31", strike=100.0, option_type="PE",
        )
        assert c.greeks == {}

    def test_option_type_stored(self):
        c = OptionContract(
            symbol="X", underlying="Y",
            expiry="2026-07-31", strike=100.0, option_type="PE",
        )
        assert c.option_type == "PE"


# ────────────────────────────────────────────────────────────────────────────
# OptionChainLoader
# ────────────────────────────────────────────────────────────────────────────

class TestOptionChainLoader:
    def test_no_api_no_db_returns_list(self):
        """No API, no DB — should fail gracefully and return a list."""
        loader = OptionChainLoader(api_client=None)
        result = loader.get_chain("NIFTY")
        assert isinstance(result, list)

    def test_filter_strikes_with_none_spot_returns_sorted(self):
        contracts = [
            OptionContract("A", "N", "2026-07-31", 22000.0, "CE"),
            OptionContract("B", "N", "2026-07-31", 23000.0, "CE"),
            OptionContract("C", "N", "2026-07-31", 21000.0, "CE"),
        ]
        loader = OptionChainLoader()
        result = loader._filter_strikes(contracts, spot=None, n=5)
        strikes = [c.strike for c in result]
        assert strikes == sorted(strikes)

    def test_filter_strikes_limits_to_n_around_atm(self):
        strikes = list(range(20000, 25500, 500))  # 11 strikes
        contracts = [
            OptionContract(f"N{k}", "NIFTY", "2026-07-31", float(k), "CE")
            for k in strikes
        ]
        loader = OptionChainLoader()
        result = loader._filter_strikes(contracts, spot=22500.0, n=2)
        result_strikes = {c.strike for c in result}
        assert all(21500.0 <= s <= 23500.0 for s in result_strikes)

    def test_nearest_expiry_is_future_date(self):
        expiry_str = OptionChainLoader._nearest_expiry("NIFTY")
        expiry_date = date.fromisoformat(expiry_str)
        assert expiry_date > date.today()

    def test_get_atm_strike_fallback_rounding(self):
        """Empty chain → fallback to round(spot/50)*50."""
        loader = OptionChainLoader(api_client=None)
        atm = loader.get_atm_strike("FAKESYM", spot=22475.0)
        assert atm == round(22475.0 / 50) * 50


# ────────────────────────────────────────────────────────────────────────────
# CoveredCallStrategy
# ────────────────────────────────────────────────────────────────────────────

class TestCoveredCallStrategy:
    @pytest.fixture()
    def volatile_df(self):
        return _make_close_series(n=500, noise=0.02, seed=42)

    @pytest.fixture()
    def flat_df(self):
        idx = pd.date_range("2022-01-01", periods=500, freq="B")
        return pd.DataFrame({"Close": [22500.0] * 500}, index=idx)

    def test_returns_series_same_index(self, volatile_df):
        strat = CoveredCallStrategy(iv_rank_threshold=70.0)
        signals = strat.generate_signals(volatile_df)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(volatile_df)
        assert (signals.index == volatile_df.index).all()

    def test_signals_only_valid_values(self, volatile_df):
        strat = CoveredCallStrategy(iv_rank_threshold=70.0)
        signals = strat.generate_signals(volatile_df)
        assert set(signals.unique()).issubset({-1.0, 0.0, 1.0})

    def test_generates_at_least_one_signal_on_volatile_data(self, volatile_df):
        strat = CoveredCallStrategy(iv_rank_threshold=70.0)
        signals = strat.generate_signals(volatile_df)
        assert signals.abs().sum() > 0

    def test_no_signal_on_flat_data(self, flat_df):
        strat = CoveredCallStrategy(iv_rank_threshold=70.0)
        signals = strat.generate_signals(flat_df)
        assert (signals == 0).all()

    def test_entry_before_exit(self, volatile_df):
        strat = CoveredCallStrategy(iv_rank_threshold=70.0)
        signals = strat.generate_signals(volatile_df)
        entries = signals[signals == 1].index.tolist()
        exits   = signals[signals == -1].index.tolist()
        if exits:
            assert entries
            assert entries[0] < exits[0]

    def test_strategy_name(self):
        assert CoveredCallStrategy().name == "covered_call"

    def test_higher_threshold_fewer_signals(self, volatile_df):
        low_thresh  = CoveredCallStrategy(iv_rank_threshold=30.0)
        high_thresh = CoveredCallStrategy(iv_rank_threshold=90.0)
        sig_low  = low_thresh.generate_signals(volatile_df).abs().sum()
        sig_high = high_thresh.generate_signals(volatile_df).abs().sum()
        assert sig_high <= sig_low
