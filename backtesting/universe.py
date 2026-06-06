"""Predefined symbol universes for multi-stock backtesting — Phase 4.

All symbols use the Yahoo Finance .NS suffix format (NSE equities).
Load once at startup — no network calls, purely in-memory.

Usage:
    from backtesting.universe import load_universe, custom_universe

    symbols = load_universe("NIFTY50")          # list of 50 .NS symbols
    symbols = load_universe("NIFTYBANK")        # 12 bank stocks
    symbols = custom_universe(["RELIANCE", "TCS"])   # auto-appends .NS
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical universe definitions
# ---------------------------------------------------------------------------

_NIFTY50: list[str] = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "BHARTIARTL.NS", "ICICIBANK.NS",
    "INFOSYS.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "ASIANPAINT.NS", "MARUTI.NS",
    "SUNPHARMA.NS", "TITAN.NS", "HCLTECH.NS", "NTPC.NS", "POWERGRID.NS",
    "ULTRACEMCO.NS", "NESTLEIND.NS", "ONGC.NS", "WIPRO.NS", "M&M.NS",
    "TATASTEEL.NS", "JSWSTEEL.NS", "TECHM.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "BAJAJFINSV.NS", "BAJAJ-AUTO.NS", "HDFCLIFE.NS", "SBILIFE.NS", "DRREDDY.NS",
    "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "GRASIM.NS", "INDUSINDBK.NS",
    "COALINDIA.NS", "BPCL.NS", "HINDALCO.NS", "TATACONSUM.NS", "EICHERMOT.NS",
    "BRITANNIA.NS", "SHRIRAMFIN.NS", "TATAMOTORS.NS", "HEROMOTOCO.NS", "BEL.NS",
]

_NIFTYBANK: list[str] = [
    "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS", "SBIN.NS",
    "INDUSINDBK.NS", "BANDHANBNK.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS",
    "AUBANK.NS", "PNB.NS", "BANKBARODA.NS",
]

_NIFTYIT: list[str] = [
    "TCS.NS", "INFOSYS.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS",
    "LTIM.NS", "MPHASIS.NS", "COFORGE.NS", "PERSISTENT.NS", "OFSS.NS",
]

_NIFTY100: list[str] = _NIFTY50 + [
    "ADANIGREEN.NS", "ADANITRANS.NS", "AMBUJACEM.NS", "AUROPHARMA.NS",
    "BALKRISIND.NS", "BERGEPAINT.NS", "BOSCHLTD.NS", "CHOLAFIN.NS",
    "CUMMINSIND.NS", "DLF.NS", "GAIL.NS", "GODREJCP.NS", "HAVELLS.NS",
    "HINDPETRO.NS", "ICICIGI.NS", "ICICIPRULI.NS", "IDEA.NS", "INDUSTOWER.NS",
    "IRCTC.NS", "JINDALSTEL.NS", "LUPIN.NS", "MARICO.NS", "MCDOWELL-N.NS",
    "MOTHERSON.NS", "MUTHOOTFIN.NS", "NAUKRI.NS", "PAGEIND.NS", "PIDILITIND.NS",
    "POLYCAB.NS", "PGHH.NS", "RECLTD.NS", "SIEMENS.NS", "SRF.NS",
    "TORNTPHARM.NS", "TRENT.NS", "UBL.NS", "UNITED SPIRITS.NS", "VEDL.NS",
    "VOLTAS.NS", "WHIRLPOOL.NS", "ZOMATO.NS", "PAYTM.NS", "NYKAA.NS",
    "POLICYBZR.NS", "DELHIVERY.NS", "CARTRADE.NS", "MAPMYINDIA.NS",
    "STARHEALTH.NS", "MEDANTA.NS", "UTIAMC.NS",
]

_NIFTYMIDCAP: list[str] = [
    "ABFRL.NS", "ABCAPITAL.NS", "AEGISCHEM.NS", "APLLTD.NS", "ASTRAL.NS",
    "ATGL.NS", "APLAPOLLO.NS", "BATAINDIA.NS", "BIOCON.NS", "BLUEDART.NS",
    "CANBK.NS", "CANFINHOME.NS", "CASTROLIND.NS", "CDSL.NS", "CENTURYTEX.NS",
    "CHOLAHLDNG.NS", "CONCOR.NS", "CROMPTON.NS", "CRISIL.NS", "DABUR.NS",
    "DEEPAKNTR.NS", "DIXON.NS", "EMAMILTD.NS", "ENDURANCE.NS", "ESCORT.NS",
    "EXIDEIND.NS", "FLUOROCHEM.NS", "FORTIS.NS", "GLENMARK.NS", "GNFC.NS",
    "HFCL.NS", "HONAUT.NS", "IDBI.NS", "IEX.NS", "IPCALAB.NS",
    "JKCEMENT.NS", "JSWENERGY.NS", "JUBLFOOD.NS", "KANSAINER.NS", "KARURVYSYA.NS",
]

_FO_ELIGIBLE: list[str] = _NIFTY50 + [
    "ABB.NS", "ADANIPOWER.NS", "AIAENG.NS", "ALKEM.NS", "AMARAJABAT.NS",
    "ATUL.NS", "AUBANK.NS", "AUROPHARMA.NS", "BANDHANBNK.NS", "BANKBARODA.NS",
    "BHARATFORG.NS", "BIOCON.NS", "CANBK.NS", "CANFINHOME.NS", "CHOLAFIN.NS",
    "CONCOR.NS", "CUMMINSIND.NS", "DEEPAKNTR.NS", "DIXON.NS", "ESCORTS.NS",
    "FEDERALBNK.NS", "GAIL.NS", "GLENMARK.NS", "GMRINFRA.NS", "GODREJPROP.NS",
    "GRANULES.NS", "HINDPETRO.NS", "IDFCFIRSTB.NS", "IEX.NS", "IRCTC.NS",
    "JUBLFOOD.NS", "LALPATHLAB.NS", "LTTS.NS", "MANAPPURAM.NS", "MCDOWELL-N.NS",
    "MFSL.NS", "MOTHERSON.NS", "MUTHOOTFIN.NS", "NAUKRI.NS", "NAVINFLUOR.NS",
    "PEL.NS", "PFC.NS", "PIDILITIND.NS", "PIIND.NS", "PNB.NS",
    "POLYCAB.NS", "RECLTD.NS", "SIEMENS.NS", "SUNTV.NS", "TORNTPHARM.NS",
]

_NIFTY200: list[str] = list(dict.fromkeys(_NIFTY100 + _NIFTYMIDCAP))
_NIFTY500: list[str] = list(dict.fromkeys(_NIFTY200 + _FO_ELIGIBLE))

# ---------------------------------------------------------------------------
# Registry map
# ---------------------------------------------------------------------------

_UNIVERSES: dict[str, list[str]] = {
    "NIFTY50":       _NIFTY50,
    "NIFTY100":      _NIFTY100,
    "NIFTY200":      _NIFTY200,
    "NIFTY500":      _NIFTY500,
    "NIFTYBANK":     _NIFTYBANK,
    "NIFTYIT":       _NIFTYIT,
    "NIFTYMIDCAP":   _NIFTYMIDCAP,
    "FO_ELIGIBLE":   _FO_ELIGIBLE,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_universe(name: str) -> list[str]:
    """Return a predefined symbol list by universe name.

    Args:
        name: One of NIFTY50, NIFTY100, NIFTY200, NIFTY500,
              NIFTYBANK, NIFTYIT, NIFTYMIDCAP, FO_ELIGIBLE.

    Returns:
        List of Yahoo Finance .NS symbols.

    Raises:
        ValueError: If the universe name is not recognised.
    """
    key = name.upper().replace(" ", "")
    if key not in _UNIVERSES:
        raise ValueError(
            f"Unknown universe '{name}'. "
            f"Available: {sorted(_UNIVERSES.keys())}"
        )
    return list(_UNIVERSES[key])  # return a copy


def custom_universe(symbols: list[str]) -> list[str]:
    """Build a universe from a raw symbol list.

    Automatically appends '.NS' if the symbol has no exchange suffix.

    Args:
        symbols: e.g. ["RELIANCE", "TCS", "HDFCBANK.NS"]

    Returns:
        Normalised list with .NS suffix.
    """
    result = []
    for s in symbols:
        s = s.strip().upper()
        if "." not in s:
            s = s + ".NS"
        result.append(s)
    return result


def list_universes() -> list[str]:
    """Return all available universe names."""
    return sorted(_UNIVERSES.keys())


def universe_size(name: str) -> int:
    """Return the number of symbols in a universe without loading them."""
    return len(load_universe(name))
