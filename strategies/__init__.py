"""Eagle-Base Strategies — signal generators."""

from .base import BaseStrategy
from .sma_crossover import SmaCrossover
from .ema_crossover import EmaCrossover
from .rsi_mean_reversion import RsiMeanReversion
from .macd_signal import MacdSignal

__all__ = ["BaseStrategy", "SmaCrossover", "EmaCrossover", "RsiMeanReversion", "MacdSignal"]
