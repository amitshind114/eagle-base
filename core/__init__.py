"""Eagle-Base Core — shared config, logger, base classes."""

from .config import Settings
from .logger import get_logger

__all__ = ["Settings", "get_logger"]
