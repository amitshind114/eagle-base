"""Indicator computation layer — thin wrapper over pandas-ta.

All strategies call helpers from this module instead of computing indicators
inline.  This keeps strategy code focused on logic, not maths, and makes
it trivial to swap the underlying library without touching any strategy.

All functions accept an OHLCV DataFrame and return a pandas Series or
DataFrame.  Column names follow NSE convention: Open, High, Low, Close, Volume.

Requires: pandas-ta  (pure Python, no C build dependency)
    pip install pandas-ta

Usage:
    from ai.indicators import rsi, macd, ema, vwap, bbands

    rsi_series  = rsi(df, period=14)
    macd_result = macd(df)           # DataFrame with macd, signal, histogram cols
    ema_fast    = ema(df, period=9)
    vwap_series = vwap(df)           # intraday only — needs DatetimeIndex
    bb          = bbands(df)         # DataFrame with upper, mid, lower cols
"""

from __future__ import annotations

import pandas as pd

try:
    import pandas_ta as ta
    _HAS_PANDAS_TA = True
except ImportError:
    _HAS_PANDAS_TA = False


def _close(df: pd.DataFrame) -> pd.Series:
    return df["Close"]


def _require_ta() -> None:
    if not _HAS_PANDAS_TA:
        raise ImportError(
            "pandas-ta is required for indicator computation.  "
            "Install it with: pip install pandas-ta"
        )


# ── Momentum ────────────────────────────────────────────────────────────────

def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    _require_ta()
    result = ta.rsi(_close(df), length=period)
    return result if result is not None else pd.Series(dtype=float, index=df.index)


def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD — returns DataFrame with columns: macd, signal, histogram."""
    _require_ta()
    result = ta.macd(_close(df), fast=fast, slow=slow, signal=signal)
    if result is None or result.empty:
        return pd.DataFrame(
            {"macd": pd.NA, "signal": pd.NA, "histogram": pd.NA}, index=df.index
        )
    result.columns = ["macd", "histogram", "signal"]
    return result[["macd", "signal", "histogram"]]


def stoch(
    df: pd.DataFrame,
    k: int = 14,
    d: int = 3,
    smooth_k: int = 3,
) -> pd.DataFrame:
    """Stochastic Oscillator — returns DataFrame with columns: stoch_k, stoch_d."""
    _require_ta()
    result = ta.stoch(df["High"], df["Low"], _close(df), k=k, d=d, smooth_k=smooth_k)
    if result is None or result.empty:
        return pd.DataFrame({"stoch_k": pd.NA, "stoch_d": pd.NA}, index=df.index)
    result.columns = ["stoch_k", "stoch_d"]
    return result


# ── Trend ───────────────────────────────────────────────────────────────────

def ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    _require_ta()
    result = ta.ema(_close(df), length=period)
    return result if result is not None else pd.Series(dtype=float, index=df.index)


def sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Simple Moving Average."""
    _require_ta()
    result = ta.sma(_close(df), length=period)
    return result if result is not None else pd.Series(dtype=float, index=df.index)


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index — returns DataFrame with adx, dmp, dmn columns."""
    _require_ta()
    result = ta.adx(df["High"], df["Low"], _close(df), length=period)
    if result is None or result.empty:
        return pd.DataFrame({"adx": pd.NA, "dmp": pd.NA, "dmn": pd.NA}, index=df.index)
    result.columns = ["adx", "dmp", "dmn"]
    return result


def supertrend(
    df: pd.DataFrame,
    period: int = 7,
    multiplier: float = 3.0,
) -> pd.DataFrame:
    """SuperTrend — returns DataFrame with supertrend and direction columns."""
    _require_ta()
    result = ta.supertrend(
        df["High"], df["Low"], _close(df), length=period, multiplier=multiplier
    )
    if result is None or result.empty:
        return pd.DataFrame({"supertrend": pd.NA, "direction": pd.NA}, index=df.index)
    cols = result.columns.tolist()
    result = result.rename(columns={cols[0]: "supertrend", cols[1]: "direction"})
    return result[["supertrend", "direction"]]


# ── Volatility ──────────────────────────────────────────────────────────────

def bbands(
    df: pd.DataFrame,
    period: int = 20,
    std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands — returns DataFrame with upper, mid, lower, bandwidth, percent."""
    _require_ta()
    result = ta.bbands(_close(df), length=period, std=std)
    if result is None or result.empty:
        cols = ["upper", "mid", "lower", "bandwidth", "percent"]
        return pd.DataFrame({c: pd.NA for c in cols}, index=df.index)
    result.columns = ["lower", "mid", "upper", "bandwidth", "percent"]
    return result[["upper", "mid", "lower", "bandwidth", "percent"]]


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — useful for dynamic stop-loss sizing."""
    _require_ta()
    result = ta.atr(df["High"], df["Low"], _close(df), length=period)
    return result if result is not None else pd.Series(dtype=float, index=df.index)


# ── Volume ───────────────────────────────────────────────────────────────────

def vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP anchored to the trading session.

    Requires a DatetimeIndex in IST.  For accuracy, pass only today\'s bars.
    Falls back to pandas-ta VWAP; if unavailable, computes manually.
    """
    if _HAS_PANDAS_TA:
        result = ta.vwap(df["High"], df["Low"], _close(df), df["Volume"])
        if result is not None:
            return result
    # Manual fallback
    tp = (df["High"] + df["Low"] + _close(df)) / 3
    cum_vol = df["Volume"].cumsum()
    return (tp * df["Volume"]).cumsum() / cum_vol.replace(0, float("nan"))


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume."""
    _require_ta()
    result = ta.obv(_close(df), df["Volume"])
    return result if result is not None else pd.Series(dtype=float, index=df.index)
