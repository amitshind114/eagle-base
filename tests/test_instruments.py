"""Tests — Instruments Module (Priority 2)."""

from __future__ import annotations

import pytest

from instruments.resolver import InstrumentResolver, Instrument


class TestInstrumentResolver:
    def test_init_loads_builtin(self):
        resolver = InstrumentResolver()
        assert resolver.count() > 0

    def test_resolve_known_symbol(self):
        resolver = InstrumentResolver()
        inst = resolver.resolve("RELIANCE")
        assert inst is not None
        assert inst.symbol == "RELIANCE"
        assert inst.exchange == "NSE"
        assert inst.token == "2885"

    def test_resolve_nifty_lot_size(self):
        resolver = InstrumentResolver()
        inst = resolver.resolve("NIFTY")
        assert inst is not None
        assert inst.lot_size == 75

    def test_resolve_unknown_returns_none(self):
        resolver = InstrumentResolver()
        assert resolver.resolve("UNKNOWNSYMBOL999") is None

    def test_search_partial_match(self):
        resolver = InstrumentResolver()
        results = resolver.search("TATA")
        assert len(results) > 0
        assert any("TATA" in r.symbol for r in results)

    def test_register_custom_instrument(self):
        resolver = InstrumentResolver()
        custom = Instrument(
            symbol="CUSTOM", token="99999",
            exchange="NSE", instrument_type="EQ", name="Custom Stock"
        )
        resolver.register(custom)
        assert resolver.resolve("CUSTOM") is not None

    def test_list_all(self):
        resolver = InstrumentResolver()
        all_instruments = resolver.list_all()
        assert len(all_instruments) == resolver.count()

    def test_list_by_exchange(self):
        resolver = InstrumentResolver()
        nse = resolver.list_all(exchange="NSE")
        assert all(i.exchange == "NSE" for i in nse)

    def test_instrument_is_equity(self):
        resolver = InstrumentResolver()
        eq = resolver.resolve("RELIANCE")
        assert eq.is_equity is True
        assert eq.is_derivative is False

    def test_instrument_is_index(self):
        resolver = InstrumentResolver()
        idx = resolver.resolve("NIFTY")
        assert idx.is_equity is False
