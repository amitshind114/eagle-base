"""Options pricing, Greeks, and covered-call strategy.

Provides:
    BlackScholes         — BS price + all 5 Greeks (delta, gamma, theta, vega, rho)
    OptionChainLoader    — loads NSE option chain from Angel One / NSE API
    CoveredCallStrategy  — sell ATM call when IV rank > 70; wires into strategy framework

Black-Scholes assumptions:
    European options, continuous dividend yield q (default 0).
    Uses scipy.stats.norm for N(d1), N(d2).

Usage:
    bs = BlackScholes(S=22500, K=22500, T=0.0833, r=0.065, sigma=0.18)
    print(bs.price("CE"))      # → call price
    print(bs.delta("CE"))      # → delta
    print(bs.greeks("CE"))     # → dict of all greeks

    loader = OptionChainLoader()
    chain  = loader.get_chain("NIFTY")  # → list[OptionContract]

    strat  = CoveredCallStrategy(iv_rank_threshold=70)
    signal = strat.generate_signals(df)  # → pd.Series compatible with BacktestEngine
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

__all__ = [
    "BlackScholes",
    "OptionContract",
    "OptionChainLoader",
    "CoveredCallStrategy",
]


# ════════════════════════════════════════════════════════════════════════════
# Black-Scholes pricer + Greeks
# ════════════════════════════════════════════════════════════════════════════

class BlackScholes:
    """European option price and Greeks via Black-Scholes-Merton.

    Args:
        S     : underlying spot price
        K     : strike price
        T     : time to expiry in years (e.g. 30 days → 30/365)
        r     : risk-free rate (annualised, e.g. 0.065 for 6.5%)
        sigma : implied / historical volatility (annualised, e.g. 0.18)
        q     : continuous dividend yield (default 0.0)
    """

    def __init__(
        self,
        S: float,
        K: float,
        T: float,
        r: float = 0.065,
        sigma: float = 0.18,
        q: float = 0.0,
    ) -> None:
        self.S     = float(S)
        self.K     = float(K)
        self.T     = float(T)
        self.r     = float(r)
        self.sigma = float(sigma)
        self.q     = float(q)
        # Pre-compute d1, d2
        self._d1: float | None = None
        self._d2: float | None = None

    # ── Precompute ────────────────────────────────────────────────────────

    def _compute_d(self) -> tuple[float, float]:
        if self._d1 is None:
            if self.T <= 0 or self.sigma <= 0 or self.S <= 0 or self.K <= 0:
                self._d1 = 0.0
                self._d2 = 0.0
            else:
                self._d1 = (
                    math.log(self.S / self.K)
                    + (self.r - self.q + 0.5 * self.sigma ** 2) * self.T
                ) / (self.sigma * math.sqrt(self.T))
                self._d2 = self._d1 - self.sigma * math.sqrt(self.T)
        return self._d1, self._d2  # type: ignore[return-value]

    @staticmethod
    def _N(x: float) -> float:
        """Standard normal CDF."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

    @staticmethod
    def _n(x: float) -> float:
        """Standard normal PDF."""
        return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

    # ── Price ─────────────────────────────────────────────────────────────

    def price(self, option_type: str = "CE") -> float:
        """BS fair value for a call (CE) or put (PE)."""
        d1, d2 = self._compute_d()
        S, K, T, r, q = self.S, self.K, self.T, self.r, self.q
        discount = math.exp(-r * T)
        fwd      = S * math.exp(-q * T)
        if option_type.upper() in ("CE", "CALL", "C"):
            return fwd * self._N(d1) - K * discount * self._N(d2)
        else:  # PE / PUT
            return K * discount * self._N(-d2) - fwd * self._N(-d1)

    # ── Greeks ────────────────────────────────────────────────────────────

    def delta(self, option_type: str = "CE") -> float:
        """Delta: dP/dS."""
        d1, _ = self._compute_d()
        e_qt  = math.exp(-self.q * self.T)
        if option_type.upper() in ("CE", "CALL", "C"):
            return e_qt * self._N(d1)
        return e_qt * (self._N(d1) - 1)

    def gamma(self) -> float:
        """Gamma: d²P/dS² (same for calls and puts)."""
        d1, _ = self._compute_d()
        if self.T <= 0 or self.S <= 0 or self.sigma <= 0:
            return 0.0
        return (
            math.exp(-self.q * self.T)
            * self._n(d1)
            / (self.S * self.sigma * math.sqrt(self.T))
        )

    def theta(self, option_type: str = "CE") -> float:
        """Theta: dP/dt (per calendar day, not per year)."""
        d1, d2 = self._compute_d()
        S, K, T, r, sigma, q = self.S, self.K, self.T, self.r, self.sigma, self.q
        if T <= 0:
            return 0.0
        term1 = -(
            S * math.exp(-q * T) * self._n(d1) * sigma
            / (2 * math.sqrt(T))
        )
        if option_type.upper() in ("CE", "CALL", "C"):
            term2 = -r * K * math.exp(-r * T) * self._N(d2)
            term3 =  q * S * math.exp(-q * T) * self._N(d1)
        else:
            term2 =  r * K * math.exp(-r * T) * self._N(-d2)
            term3 = -q * S * math.exp(-q * T) * self._N(-d1)
        return (term1 + term2 + term3) / 365.0   # per calendar day

    def vega(self) -> float:
        """Vega: dP/d(sigma) (per 1% change in vol)."""
        d1, _ = self._compute_d()
        if self.T <= 0:
            return 0.0
        return (
            self.S
            * math.exp(-self.q * self.T)
            * self._n(d1)
            * math.sqrt(self.T)
            / 100.0  # express as per 1% vol move
        )

    def rho(self, option_type: str = "CE") -> float:
        """Rho: dP/dr (per 1% change in rate)."""
        _, d2 = self._compute_d()
        K, T, r = self.K, self.T, self.r
        if T <= 0:
            return 0.0
        if option_type.upper() in ("CE", "CALL", "C"):
            return K * T * math.exp(-r * T) * self._N(d2)  / 100.0
        return -K * T * math.exp(-r * T) * self._N(-d2) / 100.0

    def greeks(self, option_type: str = "CE") -> dict[str, float]:
        """All Greeks in one dict."""
        return {
            "price":  round(self.price(option_type), 4),
            "delta":  round(self.delta(option_type), 4),
            "gamma":  round(self.gamma(), 6),
            "theta":  round(self.theta(option_type), 4),
            "vega":   round(self.vega(), 4),
            "rho":    round(self.rho(option_type), 4),
        }

    def __repr__(self) -> str:
        return (
            f"<BlackScholes S={self.S} K={self.K} T={self.T:.4f} "
            f"r={self.r} sigma={self.sigma}>"
        )


# ════════════════════════════════════════════════════════════════════════════
# Option contract data model
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class OptionContract:
    symbol:      str
    underlying:  str
    expiry:      str          # ISO date string e.g. "2026-07-31"
    strike:      float
    option_type: str          # "CE" | "PE"
    ltp:         float = 0.0
    iv:          float = 0.0  # implied volatility (annualised fraction)
    oi:          int   = 0    # open interest
    volume:      int   = 0
    bid:         float = 0.0
    ask:         float = 0.0
    greeks:      dict  = field(default_factory=dict)

    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.ltp


# ════════════════════════════════════════════════════════════════════════════
# Option chain loader
# ════════════════════════════════════════════════════════════════════════════

class OptionChainLoader:
    """Loads NSE option chain from Angel One instruments API.

    get_chain(underlying, expiry=None) → list[OptionContract]
    get_atm_strike(underlying, spot, expiry=None) → float

    Falls back to instruments DB if live API is unavailable.
    """

    def __init__(self, api_client=None) -> None:
        self._api  = api_client   # AngelOneAPI instance or None

    def get_chain(
        self,
        underlying: str,
        expiry: str | None = None,
        spot: float | None = None,
        strikes_around: int = 10,
    ) -> list[OptionContract]:
        """Return option contracts for an underlying.

        Args:
            underlying     : e.g. "NIFTY", "BANKNIFTY", "RELIANCE"
            expiry         : ISO date string; if None, use nearest expiry
            spot           : current price; if None, skip ATM centering
            strikes_around : number of strikes on each side of ATM to return

        Returns list[OptionContract] sorted by strike.
        """
        from core.logger import get_logger
        log = get_logger("derivatives.options")

        # Try live API first
        if self._api is not None:
            try:
                return self._load_from_api(underlying, expiry, spot, strikes_around)
            except Exception as exc:
                log.warning(f"[options] API chain load failed: {exc} — falling back to DB")

        # Fall back to instruments DB
        return self._load_from_db(underlying, expiry, spot, strikes_around)

    def _load_from_api(
        self, underlying: str, expiry: str | None,
        spot: float | None, strikes_around: int,
    ) -> list[OptionContract]:
        """Load option chain from Angel One SmartAPI."""
        # Angel One option chain endpoint (smartapi docs)
        data = self._api.optionChain(
            name=underlying.upper(),
            expirydate=expiry or self._nearest_expiry(underlying),
        )
        contracts: list[OptionContract] = []
        for row in data.get("data", []):
            contracts.append(OptionContract(
                symbol      = row.get("symbol", ""),
                underlying  = underlying,
                expiry      = row.get("expiry", ""),
                strike      = float(row.get("strikePrice", 0)),
                option_type = row.get("optionType", "CE"),
                ltp         = float(row.get("ltp", 0)),
                iv          = float(row.get("impliedVolatility", 0)) / 100,
                oi          = int(row.get("openInterest", 0)),
                volume      = int(row.get("tradeVolume", 0)),
            ))
        return self._filter_strikes(contracts, spot, strikes_around)

    def _load_from_db(
        self, underlying: str, expiry: str | None,
        spot: float | None, strikes_around: int,
    ) -> list[OptionContract]:
        """Load option chain from instruments SQLite DB."""
        try:
            from instruments.storage import InstrumentStore
            store = InstrumentStore()
            insts = store.list_by_segment("CE") + store.list_by_segment("PE")
            contracts = [
                OptionContract(
                    symbol      = getattr(i, "symbol", ""),
                    underlying  = getattr(i, "underlying", underlying),
                    expiry      = getattr(i, "expiry", "") or "",
                    strike      = float(getattr(i, "strike", 0) or 0),
                    option_type = getattr(i, "option_type", "CE"),
                )
                for i in insts
                if (getattr(i, "underlying", "") or "").upper() == underlying.upper()
                and (expiry is None or getattr(i, "expiry", "") == expiry)
            ]
            return self._filter_strikes(contracts, spot, strikes_around)
        except Exception:
            return []

    def _filter_strikes(
        self,
        contracts: list[OptionContract],
        spot: float | None,
        n: int,
    ) -> list[OptionContract]:
        if spot is None or not contracts:
            return sorted(contracts, key=lambda c: c.strike)
        strikes = sorted({c.strike for c in contracts})
        if not strikes:
            return contracts
        atm = min(strikes, key=lambda k: abs(k - spot))
        idx = strikes.index(atm)
        lo  = strikes[max(0, idx - n)]
        hi  = strikes[min(len(strikes) - 1, idx + n)]
        return sorted(
            [c for c in contracts if lo <= c.strike <= hi],
            key=lambda c: c.strike,
        )

    def get_atm_strike(self, underlying: str, spot: float,
                       expiry: str | None = None) -> float:
        """Return the ATM strike for an underlying given spot."""
        chain = self.get_chain(underlying, expiry, spot, strikes_around=1)
        if not chain:
            return round(spot / 50) * 50   # fallback: round to nearest 50
        return min(chain, key=lambda c: abs(c.strike - spot)).strike

    @staticmethod
    def _nearest_expiry(underlying: str) -> str:
        """Guess nearest weekly expiry (Thursday for NIFTY/BANKNIFTY)."""
        today = date.today()
        # Find next Thursday
        days_ahead = (3 - today.weekday()) % 7  # Thursday = weekday 3
        if days_ahead == 0:
            days_ahead = 7
        nxt = today.replace(day=today.day + days_ahead)
        # crude date addition
        from datetime import timedelta
        nxt = today + timedelta(days=days_ahead)
        return nxt.isoformat()


# ════════════════════════════════════════════════════════════════════════════
# Covered Call Strategy
# ════════════════════════════════════════════════════════════════════════════

class CoveredCallStrategy:
    """Sell ATM call when IV rank > threshold.

    Compatible with BacktestEngine — generates a signal Series.

    IV rank = (current IV - 52w low IV) / (52w high IV - 52w low IV) * 100

    Signal convention:
        +1 = sell ATM call (enter covered call)
        -1 = close covered call (IV rank dropped below threshold)
         0 = hold
    """

    name = "covered_call"

    def __init__(
        self,
        iv_rank_threshold: float = 70.0,
        iv_window: int = 252,
        r: float = 0.065,
    ) -> None:
        self.iv_rank_threshold = iv_rank_threshold
        self.iv_window         = iv_window
        self.r                 = r

    def generate_signals(self, df) -> "pd.Series":
        """Generate covered-call entry/exit signals.

        Expects df to have at minimum a 'Close' column.
        IV is estimated from realised volatility (20-day rolling std of log returns).
        """
        import pandas as pd
        import numpy as np

        log_ret   = np.log(df["Close"] / df["Close"].shift(1))
        realised  = log_ret.rolling(20).std() * np.sqrt(252)    # annualised
        roll_min  = realised.rolling(self.iv_window, min_periods=20).min()
        roll_max  = realised.rolling(self.iv_window, min_periods=20).max()
        iv_rank   = (realised - roll_min) / (roll_max - roll_min + 1e-9) * 100

        signals = pd.Series(0, index=df.index, dtype=float)
        in_trade = False
        for i, (ts, rank) in enumerate(iv_rank.items()):
            if pd.isna(rank):
                continue
            if not in_trade and rank >= self.iv_rank_threshold:
                signals.iloc[i] = 1
                in_trade = True
            elif in_trade and rank < self.iv_rank_threshold * 0.7:
                signals.iloc[i] = -1
                in_trade = False
        return signals
