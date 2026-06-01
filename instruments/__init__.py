"""Eagle-Base Instruments Module — Priority 2.

Instrument resolution, symbol lookup, and metadata.
Maps human-readable symbols to exchange tokens and instrument info.
"""

from instruments.resolver import InstrumentResolver, Instrument
from instruments.master import InstrumentMaster

__all__ = ["InstrumentResolver", "Instrument", "InstrumentMaster"]
