"""NSE/BSE instrument registry."""

from __future__ import annotations

from .models import Instrument
from core.exceptions import InstrumentNotFoundError

NSE_INSTRUMENTS: dict[str, dict] = {
    "RELIANCE.NS": {"name": "Reliance Industries", "sector": "Energy", "lot_size": 250},
    "TCS.NS": {"name": "Tata Consultancy Services", "sector": "IT", "lot_size": 150},
    "HDFCBANK.NS": {"name": "HDFC Bank", "sector": "Banking", "lot_size": 550},
    "INFY.NS": {"name": "Infosys", "sector": "IT", "lot_size": 300},
    "ICICIBANK.NS": {"name": "ICICI Bank", "sector": "Banking", "lot_size": 700},
    "ITC.NS": {"name": "ITC Ltd", "sector": "FMCG", "lot_size": 3200},
    "SBIN.NS": {"name": "State Bank of India", "sector": "Banking", "lot_size": 1500},
    "HINDUNILVR.NS": {"name": "Hindustan Unilever", "sector": "FMCG", "lot_size": 300},
    "BHARTIARTL.NS": {"name": "Bharti Airtel", "sector": "Telecom", "lot_size": 950},
    "KOTAKBANK.NS": {"name": "Kotak Mahindra Bank", "sector": "Banking", "lot_size": 400},
    "LT.NS": {"name": "Larsen & Toubro", "sector": "Infrastructure", "lot_size": 175},
    "WIPRO.NS": {"name": "Wipro", "sector": "IT", "lot_size": 1500},
    "AXISBANK.NS": {"name": "Axis Bank", "sector": "Banking", "lot_size": 1200},
    "MARUTI.NS": {"name": "Maruti Suzuki", "sector": "Auto", "lot_size": 100},
    "TATAMOTORS.NS": {"name": "Tata Motors", "sector": "Auto", "lot_size": 1425},
    "ONGC.NS": {"name": "ONGC", "sector": "Energy", "lot_size": 1925},
    "SUNPHARMA.NS": {"name": "Sun Pharma", "sector": "Pharma", "lot_size": 700},
    "TITAN.NS": {"name": "Titan Company", "sector": "Consumer", "lot_size": 375},
    "ULTRACEMCO.NS": {"name": "UltraTech Cement", "sector": "Cement", "lot_size": 100},
    "BAJFINANCE.NS": {"name": "Bajaj Finance", "sector": "NBFC", "lot_size": 125},
    "NIFTY50=NSE": {"name": "Nifty 50 Index", "sector": "Index", "lot_size": 50, "asset_type": "IDX"},
    "^NSEI": {"name": "Nifty 50", "sector": "Index", "lot_size": 50, "asset_type": "IDX"},
    "^NSEBANK": {"name": "Bank Nifty", "sector": "Index", "lot_size": 15, "asset_type": "IDX"},
}


class InstrumentRegistry:
    """Lookup and search instruments."""

    def get(self, symbol: str) -> Instrument:
        sym = symbol.upper()
        if sym not in NSE_INSTRUMENTS:
            raise InstrumentNotFoundError(f"Symbol '{sym}' not found in registry")
        data = NSE_INSTRUMENTS[sym]
        return Instrument(
            symbol=sym,
            name=data["name"],
            sector=data["sector"],
            market="NSE",
            asset_type=data.get("asset_type", "EQ"),
            lot_size=data.get("lot_size", 1),
        )

    def search(self, query: str) -> list[Instrument]:
        q = query.lower()
        results = []
        for sym, data in NSE_INSTRUMENTS.items():
            if q in sym.lower() or q in data["name"].lower() or q in data["sector"].lower():
                results.append(
                    Instrument(
                        symbol=sym,
                        name=data["name"],
                        sector=data["sector"],
                        market="NSE",
                        asset_type=data.get("asset_type", "EQ"),
                        lot_size=data.get("lot_size", 1),
                    )
                )
        return results

    def all(self) -> list[Instrument]:
        return self.search("")

    def by_sector(self, sector: str) -> list[Instrument]:
        return [i for i in self.all() if i.sector.lower() == sector.lower()]
