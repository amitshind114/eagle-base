"""Data API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from data.fetcher import DataFetcher
from core.exceptions import DataFetchError, InsufficientDataError

router = APIRouter()
fetcher = DataFetcher()


@router.get("/ohlcv/{symbol}")
def get_ohlcv(symbol: str, period: str = "1y", interval: str = "1d"):
    try:
        df = fetcher.fetch(symbol, period=period, interval=interval)
        return {"symbol": symbol, "bars": len(df), "data": df.reset_index().to_dict(orient="records")}
    except (DataFetchError, InsufficientDataError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/price/{symbol}")
def get_price(symbol: str):
    try:
        price = fetcher.fetch_latest_price(symbol)
        return {"symbol": symbol, "price": price}
    except DataFetchError as e:
        raise HTTPException(status_code=404, detail=str(e))
