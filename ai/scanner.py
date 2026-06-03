"""AI signal scanner — multi-indicator analysis across watchlist."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.logger import get_logger
from data.fetcher import DataFetcher
from .models import SignalResult

log = get_logger("ai.scanner")
fetcher = DataFetcher()


class SignalScanner:
    """Scan a list of symbols and generate AI signal scores."""

    def scan(self, symbols: list[str], period: str = "3mo") -> list[SignalResult]:
        """
        Scan symbols and return scored signal results.

        Args:
            symbols: List of Yahoo Finance tickers.
            period: Data period for indicator calculation.

        Returns:
            List of SignalResult sorted by score descending.
        """
        results = []
        for sym in symbols:
            try:
                df = fetcher.fetch(sym, period=period, min_bars=30)
                result = self._analyse(sym, df)
                results.append(result)
            except Exception as e:
                log.warning(f"Scan failed for {sym}: {e}")
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _analyse(self, symbol: str, df: pd.DataFrame) -> SignalResult:
        close = df["Close"]
        volume = df["Volume"]
        score = 0
        signals = []

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = float((100 - 100 / (1 + gain / loss.replace(0, np.nan))).iloc[-1])
        if rsi < 35:
            signals.append("RSI Oversold")
            score += 2
        elif rsi > 65:
            signals.append("RSI Overbought")
            score -= 2

        # EMA cross
        ema20 = close.ewm(span=20).mean()
        ema50 = close.ewm(span=50).mean()
        ema_cross = "none"
        if ema20.iloc[-1] > ema50.iloc[-1] and ema20.iloc[-2] <= ema50.iloc[-2]:
            ema_cross = "bullish"
            signals.append("EMA Bullish Cross")
            score += 3
        elif ema20.iloc[-1] < ema50.iloc[-1] and ema20.iloc[-2] >= ema50.iloc[-2]:
            ema_cross = "bearish"
            signals.append("EMA Bearish Cross")
            score -= 3

        # MACD
        macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
        sig = macd.ewm(span=9).mean()
        macd_bullish = bool(macd.iloc[-1] > sig.iloc[-1])
        signals.append("MACD Bullish" if macd_bullish else "MACD Bearish")
        score += 1 if macd_bullish else -1

        # Bollinger
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_pos = "inside"
        if close.iloc[-1] < (bb_mid - 2 * bb_std).iloc[-1]:
            bb_pos = "below"
            signals.append("Below BB Lower")
            score += 2
        elif close.iloc[-1] > (bb_mid + 2 * bb_std).iloc[-1]:
            bb_pos = "above"
            signals.append("Above BB Upper")
            score -= 2

        # Volume spike
        avg_vol = volume.rolling(20).mean().iloc[-1]
        vol_spike = bool(volume.iloc[-1] > avg_vol * 1.5)
        if vol_spike:
            signals.append("Volume Spike")
            score += 1

        reco = (
            "🟢 STRONG BUY" if score >= 4
            else "🟩 BUY" if score >= 2
            else "🔴 STRONG SELL" if score <= -4
            else "🟥 SELL" if score <= -2
            else "⚪ NEUTRAL"
        )

        return SignalResult(
            symbol=symbol.replace(".NS", ""),
            ltp=round(float(close.iloc[-1]), 2),
            rsi=round(rsi, 1),
            macd_bullish=macd_bullish,
            ema_cross=ema_cross,
            bb_position=bb_pos,
            volume_spike=vol_spike,
            score=score,
            signals=signals,
            recommendation=reco,
        )
