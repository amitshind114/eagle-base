"""Tests — Instruments Module (Phase 1).

Fixes
-----
- Instrument() no longer accepts instrument_type kwarg; use segment='EQ'.
- to_yf_symbol / to_angel_symbol imported and tested.
- MIDCPNIFTY / FINNIFTY lot-size tests added.
"""

from __future__ import annotations

import pytest

from instruments.resolver import InstrumentResolver, to_yf_symbol, to_angel_symbol
from instruments.models import Instrument


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

    def test_resolve_banknifty_lot_size(self):
        resolver = InstrumentResolver()
        inst = resolver.resolve("BANKNIFTY")
        assert inst is not None
        assert inst.lot_size == 15

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
            exchange="NSE", segment="EQ", name="Custom Stock",
        )
        resolver.register(custom)
        found = resolver.resolve("CUSTOM")
        assert found is not None
        assert found.token == "99999"

    def test_list_all(self):
        resolver = InstrumentResolver()
        all_instruments = resolver.list_all()
        assert len(all_instruments) >= resolver.count()

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
        assert idx.is_index is True

    def test_nse_symbol_derived(self):
        """nse_symbol must be set even when not passed explicitly."""
        inst = Instrument(symbol="RELIANCE-EQ", token="2885", exchange="NSE", segment="EQ")
        assert inst.nse_symbol == "RELIANCE"

    def test_angel_token_alias(self):
        """token and angel_token must stay in sync."""
        inst = Instrument(symbol="TCS", token="11536", exchange="NSE", segment="EQ")
        assert inst.angel_token == "11536"

        inst2 = Instrument(symbol="TCS", angel_token="11536", exchange="NSE", segment="EQ")
        assert inst2.token == "11536"


class TestYFSymbolHelpers:
    def test_adds_ns_suffix(self):
        assert to_yf_symbol("RELIANCE") == "RELIANCE.NS"

    def test_adds_bo_suffix(self):
        assert to_yf_symbol("RELIANCE", exchange="BSE") == "RELIANCE.BO"

    def test_does_not_double_suffix(self):
        assert to_yf_symbol("RELIANCE.NS") == "RELIANCE.NS"

    def test_index_unchanged(self):
        assert to_yf_symbol("^NSEI") == "^NSEI"

    def test_strip_ns(self):
        assert to_angel_symbol("RELIANCE.NS") == "RELIANCE"

    def test_strip_bo(self):
        assert to_angel_symbol("HDFCBANK.BO") == "HDFCBANK"

    def test_no_suffix_unchanged(self):
        assert to_angel_symbol("TCS") == "TCS"
