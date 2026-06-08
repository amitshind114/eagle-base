"""Phase 10c — InstrumentResolver + helper function unit tests.

Covers:
  to_yf_symbol()  (pure function, no I/O)
  [x] NSE symbol without suffix gets .NS appended
  [x] BSE symbol gets .BO appended
  [x] already-.NS symbol unchanged
  [x] already-.BO symbol unchanged
  [x] index symbol (^NSEI) unchanged
  [x] mixed-case input normalised to uppercase

  to_angel_symbol()  (pure function)
  [x] strips .NS suffix
  [x] strips .BO suffix
  [x] symbol without suffix unchanged
  [x] mixed-case normalised

  _BUILTIN_INSTRUMENTS
  [x] NIFTY is present
  [x] BANKNIFTY is present
  [x] RELIANCE has token '2885'
  [x] all builtins have non-empty symbol
  [x] all builtins have non-empty exchange

  InstrumentResolver (pure / in-memory tests only — no live DB)
  [x] resolve() returns None for empty string
  [x] resolve() finds RELIANCE from builtins
  [x] resolve() finds NIFTY from builtins
  [x] resolve() strips .NS suffix and resolves
  [x] resolve() returns None for unknown symbol
  [x] search() returns list
  [x] search() finds RELIANCE by partial match
  [x] resolve_yf_symbol() returns .NS suffix for equity instruments
  [x] resolve_yf_symbol() returns ^NSEI for NIFTY index
  [x] _last_thursday_of_month() returns a Thursday
  [x] _last_thursday_of_month() returns last Thursday in given month

All tests: zero network, zero broker credentials, < 1 second.
"""

from __future__ import annotations

from datetime import date

import pytest

from instruments.resolver import (
    to_yf_symbol,
    to_angel_symbol,
    _BUILTIN_INSTRUMENTS,
    InstrumentResolver,
)
from instruments.models import Instrument


# ────────────────────────────────────────────────────────────────────────────
to_yf_symbol() — pure function
# ────────────────────────────────────────────────────────────────────────────

class TestToYfSymbol:
    def test_nse_symbol_gets_ns_suffix(self):
        assert to_yf_symbol("RELIANCE", "NSE") == "RELIANCE.NS"

    def test_bse_symbol_gets_bo_suffix(self):
        assert to_yf_symbol("RELIANCE", "BSE") == "RELIANCE.BO"

    def test_already_ns_unchanged(self):
        assert to_yf_symbol("RELIANCE.NS") == "RELIANCE.NS"

    def test_already_bo_unchanged(self):
        assert to_yf_symbol("RELIANCE.BO", "BSE") == "RELIANCE.BO"

    def test_index_symbol_unchanged(self):
        assert to_yf_symbol("^NSEI") == "^NSEI"

    def test_lowercase_normalised(self):
        result = to_yf_symbol("reliance", "NSE")
        assert result == "RELIANCE.NS"


# ────────────────────────────────────────────────────────────────────────────
to_angel_symbol() — pure function
# ────────────────────────────────────────────────────────────────────────────

class TestToAngelSymbol:
    def test_strips_ns_suffix(self):
        assert to_angel_symbol("RELIANCE.NS") == "RELIANCE"

    def test_strips_bo_suffix(self):
        assert to_angel_symbol("RELIANCE.BO") == "RELIANCE"

    def test_no_suffix_unchanged(self):
        assert to_angel_symbol("RELIANCE") == "RELIANCE"

    def test_lowercase_normalised(self):
        assert to_angel_symbol("reliance.ns") == "RELIANCE"


# ────────────────────────────────────────────────────────────────────────────
_BUILTIN_INSTRUMENTS
# ────────────────────────────────────────────────────────────────────────────

class TestBuiltins:
    def test_nifty_present(self):
        syms = {i.symbol for i in _BUILTIN_INSTRUMENTS}
        assert "NIFTY" in syms

    def test_banknifty_present(self):
        syms = {i.symbol for i in _BUILTIN_INSTRUMENTS}
        assert "BANKNIFTY" in syms

    def test_reliance_token(self):
        rel = next(i for i in _BUILTIN_INSTRUMENTS if i.symbol == "RELIANCE")
        assert rel.token == "2885"

    def test_all_have_nonempty_symbol(self):
        assert all(i.symbol for i in _BUILTIN_INSTRUMENTS)

    def test_all_have_nonempty_exchange(self):
        assert all(i.exchange for i in _BUILTIN_INSTRUMENTS)


# ────────────────────────────────────────────────────────────────────────────
InstrumentResolver
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def resolver():
    """Single InstrumentResolver per test module — uses in-memory SQLite."""
    return InstrumentResolver()


class TestInstrumentResolver:
    def test_resolve_empty_string_returns_none(self, resolver):
        assert resolver.resolve("") is None

    def test_resolve_reliance(self, resolver):
        inst = resolver.resolve("RELIANCE")
        assert inst is not None
        assert inst.symbol == "RELIANCE"

    def test_resolve_nifty(self, resolver):
        inst = resolver.resolve("NIFTY")
        assert inst is not None

    def test_resolve_strips_ns_suffix(self, resolver):
        inst = resolver.resolve("RELIANCE.NS")
        assert inst is not None
        assert "RELIANCE" in inst.symbol

    def test_resolve_unknown_returns_none(self, resolver):
        assert resolver.resolve("XXXXXXXXXUNKNOWN") is None

    def test_search_returns_list(self, resolver):
        result = resolver.search("RELIANCE")
        assert isinstance(result, list)

    def test_search_finds_reliance(self, resolver):
        result = resolver.search("RELIANCE")
        symbols = [i.symbol for i in result]
        assert any("RELIANCE" in s for s in symbols)

    def test_resolve_yf_symbol_equity(self, resolver):
        inst = resolver.resolve("RELIANCE")
        assert inst is not None
        yf = resolver.resolve_yf_symbol(inst)
        assert yf.endswith(".NS")

    def test_resolve_yf_symbol_nifty_index(self, resolver):
        inst = resolver.resolve("NIFTY")
        assert inst is not None
        yf = resolver.resolve_yf_symbol(inst)
        assert yf.startswith("^")  # index symbols start with ^

    def test_last_thursday_is_thursday(self):
        d = InstrumentResolver._last_thursday_of_month(date(2026, 6, 1))
        assert d.weekday() == 3  # 3 = Thursday

    def test_last_thursday_june_2026(self):
        d = InstrumentResolver._last_thursday_of_month(date(2026, 6, 1))
        assert d == date(2026, 6, 25)
