"""Domain exceptions for Eagle-Base."""


class EagleBaseError(Exception):
    """Root exception."""


class DataFetchError(EagleBaseError):
    """Raised when market data fetch fails."""


class InsufficientDataError(EagleBaseError):
    """Raised when not enough bars for indicator computation."""


class InstrumentNotFoundError(EagleBaseError):
    """Raised when symbol is not resolvable to a known instrument."""


class InsufficientFundsError(EagleBaseError):
    """Raised when paper/live order exceeds available cash."""


class RiskBreachError(EagleBaseError):
    """Raised when a risk limit is breached."""


class StrategyError(EagleBaseError):
    """Raised on strategy configuration or execution error."""


class BacktestError(EagleBaseError):
    """Raised during backtesting failures."""


class BrokerAuthError(EagleBaseError):
    """Raised when broker login or token refresh fails."""


class OrderError(EagleBaseError):
    """Raised when an order placement or cancellation fails."""
