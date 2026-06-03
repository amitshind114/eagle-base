"""Black-Scholes options pricing with Greeks."""

from __future__ import annotations

from math import exp, log, sqrt

import numpy as np
from scipy.stats import norm

from core.logger import get_logger
from .models import OptionContract

log = get_logger("derivatives.options")


class OptionsChain:
    """Generate full options chain using Black-Scholes model."""

    def __init__(self, risk_free_rate: float = 0.065, iv: float = 0.18) -> None:
        self.r = risk_free_rate
        self.iv = iv

    def price(
        self,
        spot: float,
        strike: float,
        expiry_days: int,
        option_type: str = "call",
    ) -> OptionContract:
        """Price a single option and return Greeks."""
        T = max(expiry_days, 1) / 365
        S, K, r, sigma = spot, strike, self.r, self.iv

        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        d2 = d1 - sigma * sqrt(T)

        if option_type == "call":
            price = S * norm.cdf(d1) - K * exp(-r * T) * norm.cdf(d2)
            delta = norm.cdf(d1)
            theta = (-(S * norm.pdf(d1) * sigma) / (2 * sqrt(T)) - r * K * exp(-r * T) * norm.cdf(d2)) / 365
        else:
            price = K * exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            delta = norm.cdf(d1) - 1
            theta = (-(S * norm.pdf(d1) * sigma) / (2 * sqrt(T)) + r * K * exp(-r * T) * norm.cdf(-d2)) / 365

        gamma = norm.pdf(d1) / (S * sigma * sqrt(T))
        vega = S * norm.pdf(d1) * sqrt(T) / 100

        atm = round(spot / 50) * 50
        moneyness = "ATM" if strike == atm else ("ITM" if (option_type == "call" and strike < spot) or (option_type == "put" and strike > spot) else "OTM")

        return OptionContract(
            strike=strike,
            option_type=option_type,
            spot=spot,
            expiry_days=expiry_days,
            iv=round(sigma * 100, 1),
            ltp=round(price, 2),
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta, 2),
            vega=round(vega, 4),
            moneyness=moneyness,
        )

    def chain(
        self,
        spot: float,
        expiry_days: int,
        strikes: list[float] | None = None,
        step: float = 50,
        num_strikes: int = 11,
    ) -> list[dict]:
        """Generate full options chain for given spot and expiry."""
        if strikes is None:
            atm = round(spot / step) * step
            strikes = [atm + (i - num_strikes // 2) * step for i in range(num_strikes)]

        rows = []
        for K in strikes:
            call = self.price(spot, K, expiry_days, "call")
            put = self.price(spot, K, expiry_days, "put")
            rows.append({
                "CALL LTP": call.ltp,
                "CALL Δ": call.delta,
                "CALL Θ": call.theta,
                "CALL Vega": call.vega,
                "Strike": K,
                "Moneyness": call.moneyness,
                "PUT Vega": put.vega,
                "PUT Θ": put.theta,
                "PUT Δ": put.delta,
                "PUT LTP": put.ltp,
            })
        log.info(f"Generated options chain: spot={spot} expiry={expiry_days}d strikes={len(strikes)}")
        return rows
