"""Eagle-Base Logger.

Centralized logging using loguru. All modules should import
logger from here instead of using print() or standard logging.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Remove default handler
logger.remove()

# Console handler
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan> - {message}",
    level="DEBUG",
    colorize=True,
)

# File handler
logger.add(
    LOG_DIR / "eagle-base.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time} | {level} | {name} | {message}",
)

__all__ = ["logger"]
