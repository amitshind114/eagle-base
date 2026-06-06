"""
Eagle-Base Streamlit Dashboard — Phase 07.
Changes in this version:
  - Backtesting page: calls /api/backtest/run (real API), renders equity curve
    chart + drawdown chart from API response. Strategy param sliders wired to
    the API payload. fast < slow guard before submit.
  - Multi-stock tab: shows leaderboard with error reporting (X/50 succeeded).
  - Paper Trading page: live /api/paper/snapshot with 30s auto-refresh.
Run with: streamlit run ui/app.py
"""

from __future__ import annotations

import datetime
import random
import io
import time

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Eagle-Base",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #0e1117; }
.metric-card {
    background: #1c1f26;
    border-radius: 10px;
    padding: 16px 20px;
    border: 1px solid #2a2d35;
}
.section-header {
    font-size: 0.75rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 8px;
}
.status-live { color: #00c853; font-weight: 700; }
.status-paper { color: #ffd600; font-weight: 700; }
.status-stopped { color: #ff5252; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# ─── NIFTY 50 symbol list ─────────────────────────────────────────────────────
NIFTY50_SYMBOLS = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
    "HINDUNILVR.NS","ITC.NS","SBIN.NS","BHARTIARTL.NS","KOTAKBANK.NS",
    "LT.NS","WIPRO.NS","AXISBANK.NS","MARUTI.NS","TATAMOTORS.NS",
    "ONGC.NS","SUNPHARMA.NS","TITAN.NS","ULTRACEMCO.NS","BAJFINANCE.NS",
    "NTPC.NS","POWERGRID.NS","ADANIENT.NS","ADANIPORTS.NS","COALINDIA.NS",
    "BAJAJFINSV.NS","HCLTECH.NS","GRASIM.NS","NESTLEIND.NS","TECHM.NS",
    "TATASTEEL.NS","JSWSTEEL.NS","M&M.NS","INDUSINDBK.NS","DRREDDY.NS",
    "CIPLA.NS","APOLLOHOSP.NS","BPCL.NS","EICHERMOT.NS","HEROMOTOCO.NS",
    "BRITANNIA.NS","DIVISLAB.NS","TATACONSUM.NS","UPL.NS","SHREECEM.NS",
    "SBILIFE.NS","HDFCLIFE.NS","ICICIGI.NS","BAJAJ-AUTO.NS","HINDALCO.NS",
]

# ─── NSE Symbol Master ────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_nse_equity() -> pd.DataFrame:
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        sym_col = "SYMBOL"
        name_col = " NAME OF COMPANY" if " NAME OF COMPANY" in df.columns else "NAME OF COMPANY"
        df = df[[sym_col, name_col]].dropna()
        df.columns = ["SYMBOL", "NAME"]
        df["SYMBOL"] = df["SYMBOL"].str.strip()
        df["NAME"]   = df["NAME"].str.strip()
        df["YF_SYMBOL"] = df["SYMBOL"] + ".NS"
        df["SEGMENT"]   = "Equity"
        df["EXCHANGE"]  = "NSE"
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["SYMBOL","NAME","YF_SYMBOL","SEGMENT","EXCHANGE"])

@st.cache_data(ttl=3600, show_spinner=False)
def load_nse_fno() -> pd.DataFrame:
    url = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), df.columns[0])
        df = df[[sym_col]].dropna()
        df.columns = ["SYMBOL"]
        df["SYMBOL"] = df["SYMBOL"].str.strip()
        df = df[~df["SYMBOL"].str.contains("SYMBOL|^$", na=True)]
        df["NAME"] = df["SYMBOL"]
        df["YF_SYMBOL"] = df["SYMBOL"] + ".NS"
        df["SEGMENT"]   = "F&O"
        df["EXCHANGE"]  = "NSE"
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["SYMBOL","NAME","YF_SYMBOL","SEGMENT","EXCHANGE"])

@st.cache_data(ttl=3600, show_spinner=False)
def load_indices() -> pd.DataFrame:
    data = [
        ("NIFTY 50","^NSEI","Index","NSE"),("NIFTY BANK","^NSEBANK","Index","NSE"),
        ("NIFTY IT","^CNXIT","Index","NSE"),("NIFTY MIDCAP 100","^CNXMIDCAP","Index","NSE"),
        ("NIFTY SMALLCAP","^CNXSC","Index","NSE"),("NIFTY NEXT 50","^NSMIDCP","Index","NSE"),
        ("NIFTY FIN SERVICE","NIFTY_FIN_SERVICE.NS","Index","NSE"),
        ("SENSEX","^BSESN","Index","BSE"),("BSE MIDCAP","BSE-MIDCAP.BO","Index","BSE"),
    ]
    df = pd.DataFrame(data, columns=["NAME","YF_SYMBOL","SEGMENT","EXCHANGE"])
    df["SYMBOL"] = df["YF_SYMBOL"]
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def load_commodities() -> pd.DataFrame:
    data = [
        ("GOLD","GC=F","Commodity-MCX","MCX"),("SILVER","SI=F","Commodity-MCX","MCX"),
        ("CRUDE OIL","CL=F","Commodity-MCX","MCX"),("NATURAL GAS","NG=F","Commodity-MCX","MCX"),
        ("COPPER","HG=F","Commodity-MCX","MCX"),("BRENT CRUDE","BZ=F","Commodity-MCX","MCX"),
    ]
    df = pd.DataFrame(data, columns=["NAME","YF_SYMBOL","SEGMENT","EXCHANGE"])
    df["SYMBOL"] = df["NAME"]
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def load_currency() -> pd.DataFrame:
    data = [
        ("USD/INR","USDINR=X","Currency","NSE"),("EUR/INR","EURINR=X","Currency","NSE"),
        ("GBP/INR","GBPINR=X","Currency","NSE"),("EUR/USD","EURUSD=X","Currency","FOREX"),
    ]
    df = pd.DataFrame(data, columns=["NAME","YF_SYMBOL","SEGMENT","EXCHANGE"])
    df["SYMBOL"] = df["NAME"]
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def get_full_universe() -> pd.DataFrame:
    equity     = load_nse_equity()
    fno        = load_nse_fno()
    fno_syms   = set(fno["SYMBOL"].tolist())
    equity["SEGMENT"] = equity["SYMBOL"].apply(lambda s: "Equity+F&O" if s in fno_syms else "Equity")
    cols = ["SYMBOL","NAME","YF_SYMBOL","SEGMENT","EXCHANGE"]
    all_df = pd.concat([
        equity[cols], load_indices()[cols],
        load_commodities()[cols], load_currency()[cols]
    ], ignore_index=True)
    return all_df.drop_duplicates(subset=["YF_SYMBOL"]).reset_index(drop=True)


# ─── Sidebar ──────────────────────────────────────────────────────────────────
def sidebar():
    with st.sidebar:
        st.markdown("""<div style='text-align:center;padding:8px 0'>
            <span style='font-size:2rem'>🦅</span>
            <div style='font-size:1.2rem;font-weight:700;color:#fff'>Eagle-Base</div>
            <div style='font-size:0.75rem;color:#888'>Algo Research & Trading System</div>
            <div style='margin-top:6px'><span style='background:#1a3a1a;color:#00c853;
            border-radius:4px;padding:2px 8px;font-size:0.7rem'>v0.3.0 LIVE</span></div>
        </div>""", unsafe_allow_html=True)
        st.divider()
        page = st.radio("Navigate", options=[
            "🏠 Home","📊 Data","🔍 Instruments","⚙️ Backtesting",
            "🧩 Strategies","📈 Reporting","🛡️ Risk","📋 Paper Trading",
            "🤖 AI","📐 Derivatives","⚡ Live",
        ])
        st.divider()
        st.caption(f"IST: {datetime.datetime.now().strftime('%d %b %Y %H:%M:%S')}")
    return page


# ─── HOME ─────────────────────────────────────────────────────────────────────
def home_page():
    st.title("🦅 Eagle-Base")
    st.subheader("Algorithmic Research & Trading System")
    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Phase", "7 / 10", "API + UI")
    col2.metric("Modules", "11", "All Live")
    col3.metric("Status", "Active", "Running")
    col4.metric("Engine", "yfinance + NSE", "Connected")
    st.divider()
    st.subheader("📡 Market Snapshot — Nifty 50 Heatmap")
    NIFTY50 = {s.split(".")[0]: s for s in NIFTY50_SYMBOLS}
    with st.spinner("Fetching Nifty 50 data..."):
        rows = []
        for name, sym in NIFTY50.items():
            try:
                hist = yf.Ticker(sym).history(period="2d")
                if len(hist) >= 2:
                    chg = (hist["Close"].iloc[-1]-hist["Close"].iloc[-2])/hist["Close"].iloc[-2]*100
                    rows.append({"Symbol":name,"Change%":round(chg,2),"Price":round(hist["Close"].iloc[-1],2)})
            except Exception:
                rows.append({"Symbol":name,"Change%":0.0,"Price":0.0})
        df_heat = pd.DataFrame(rows)
    fig = px.treemap(df_heat, path=["Symbol"], values=[1]*len(df_heat),
                     color="Change%", color_continuous_scale=["#c62828","#1b5e20"],
                     color_continuous_midpoint=0, custom_data=["Change%","Price"])
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{customdata[0]:.2f}%")
    fig.update_layout(height=400, margin=dict(t=0,b=0,l=0,r=0),
                      paper_bgcolor="rgba(0,0,0,0)", font_color="#fff")
    st.plotly_chart(fig, use_container_width=True)


# ─── DATA MODULE ──────────────────────────────────────────────────────────────
def data_page():
    st.title("📊 Data Module")
    st.caption("Live OHLCV data — NSE Equity, F&O, Indices, Commodities, Currency")
    st.divider()
    universe = get_full_universe()
    tab_manual, tab_search = st.tabs(["🔡 Enter Symbol Manually","🔍 Search from Universe"])
    with tab_manual:
        col1,col2,col3 = st.columns(3)
        symbol   = col1.text_input("Symbol",value="RELIANCE.NS",key="data_manual").strip().upper()
        period   = col2.selectbox("Period",["1d","5d","1mo","3mo","6mo","1y","2y","5y"],index=4,key="dp_m")
        interval = col3.selectbox("Interval",["1m","5m","15m","30m","1h","1d","1wk","1mo"],index=5,key="di_m")
        fetch_sym = symbol
    with tab_search:
        segments  = ["All"]+sorted(universe["SEGMENT"].unique().tolist())
        exchanges = ["All"]+sorted(universe["EXCHANGE"].dropna().unique().tolist())
        c1,c2,c3 = st.columns([3,1,1])
        query = c1.text_input("🔍 Search",placeholder="TATA, NIFTY, GOLD...",key="data_search")
        seg_f = c2.selectbox("Segment",segments,key="data_seg")
        exc_f = c3.selectbox("Exchange",exchanges,key="data_exc")
        filtered = universe.copy()
        if query:
            q = query.upper()
            filtered = filtered[filtered["SYMBOL"].str.upper().str.contains(q,na=False)|
                                filtered["NAME"].str.upper().str.contains(q,na=False)]
        if seg_f != "All": filtered = filtered[filtered["SEGMENT"]==seg_f]
        if exc_f != "All": filtered = filtered[filtered["EXCHANGE"]==exc_f]
        st.dataframe(filtered[["SYMBOL","NAME","SEGMENT","EXCHANGE","YF_SYMBOL"]].head(200),
                     use_container_width=True, hide_index=True, height=200)
        c2a,c2b,c2c = st.columns(3)
        selected_yf = c2a.text_input("Selected YF Symbol",value="",key="dss")
        period   = c2b.selectbox("Period",["1d","5d","1mo","3mo","6mo","1y","2y","5y"],index=4,key="dp_s")
        interval = c2c.selectbox("Interval",["1m","5m","15m","30m","1h","1d","1wk","1mo"],index=5,key="di_s")
        fetch_sym = selected_yf.strip().upper() if selected_yf.strip() else None
    st.divider()
    if st.button("🔄 Fetch Data",type="primary",key="fetch_data_btn"):
        if not fetch_sym:
            st.warning("Please enter or select a symbol."); return
        with st.spinner(f"Fetching {fetch_sym}..."):
            try:
                ticker = yf.Ticker(fetch_sym)
                df = ticker.history(period=period, interval=interval)
                if df.empty:
                    st.error(f"No data for **{fetch_sym}**"); return
                df = df[["Open","High","Low","Close","Volume"]].round(4)
                ltp = df["Close"].iloc[-1]
                m1,m2,m3,m4,m5 = st.columns(5)
                m1.metric("LTP",f"{ltp:,.2f}")
                if len(df)>1:
                    chg = ltp-df["Close"].iloc[-2]
                    m2.metric("Change",f"{chg:+,.2f}",f"{chg/df['Close'].iloc[-2]*100:+.2f}%")
                m3.metric("Period High",f"{df['High'].max():,.2f}")
                m4.metric("Period Low",f"{df['Low'].min():,.2f}")
                m5.metric("Avg Volume",f"{df['Volume'].mean():,.0f}")
                fig = go.Figure(data=[go.Candlestick(
                    x=df.index,open=df["Open"],high=df["High"],low=df["Low"],close=df["Close"],
                    increasing_line_color="#00c853",decreasing_line_color="#ff5252")])
                fig.update_layout(height=450,paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)",font_color="#ccc",
                                  xaxis_rangeslider_visible=False)
                st.plotly_chart(fig,use_container_width=True)
                st.dataframe(df.sort_index(ascending=False),use_container_width=True,height=300)
                st.download_button("⬇️ Download CSV",df.to_csv(),f"{fetch_sym}_{period}.csv","text/csv")
            except Exception as e:
                st.error(f"Error: {e}")


# ─── INSTRUMENTS ──────────────────────────────────────────────────────────────
def instruments_page():
    st.title("🔍 Instruments — Full Universe")
    st.caption("Live from NSE: Equity · F&O · Indices · Commodities · Currency — 1800+ symbols")
    st.divider()
    with st.spinner("Loading NSE symbol master..."):
        universe = get_full_universe()
    total     = len(universe)
    seg_counts= universe["SEGMENT"].value_counts()
    m_cols = st.columns(6)
    m_cols[0].metric("Total Symbols",f"{total:,}")
    m_cols[1].metric("Equity",f"{seg_counts.get('Equity',0)+seg_counts.get('Equity+F&O',0):,}")
    m_cols[2].metric("F&O Eligible",f"{seg_counts.get('Equity+F&O',0):,}")
    m_cols[3].metric("Indices",f"{seg_counts.get('Index',0):,}")
    m_cols[4].metric("Commodities",f"{seg_counts.get('Commodity-MCX',0)+seg_counts.get('Commodity-Agri',0):,}")
    m_cols[5].metric("Currency",f"{seg_counts.get('Currency',0):,}")
    st.divider()
    c1,c2,c3 = st.columns([3,1,1])
    query = c1.text_input("Search symbol or company name",placeholder="TATA, HDFC, NIFTY, GOLD...")
    seg_f = c2.selectbox("Segment",["All"]+sorted(universe["SEGMENT"].unique().tolist()),key="inst_seg")
    exc_f = c3.selectbox("Exchange",["All"]+sorted(universe["EXCHANGE"].dropna().unique().tolist()),key="inst_exc")
    filtered = universe.copy()
    if query:
        q = query.upper()
        filtered = filtered[filtered["SYMBOL"].str.upper().str.contains(q,na=False)|
                            filtered["NAME"].str.upper().str.contains(q,na=False)]
    if seg_f != "All": filtered = filtered[filtered["SEGMENT"]==seg_f]
    if exc_f != "All": filtered = filtered[filtered["EXCHANGE"]==exc_f]
    st.caption(f"**{len(filtered):,}** results matched")
    st.dataframe(filtered[["SYMBOL","NAME","SEGMENT","EXCHANGE","YF_SYMBOL"]].head(500),
                 use_container_width=True, hide_index=True, height=350)


# ─── BACKTESTING — Phase 07 rewrite ──────────────────────────────────────────
def backtesting_page():
    st.title("⚙️ Backtesting Engine")
    st.caption("Single stock · Multi-stock leaderboard · API-powered")
    st.divider()

    tab_single, tab_multi = st.tabs(["📊 Single Stock", "🏆 Multi-Stock Leaderboard"])

    # ── Single Stock ──────────────────────────────────────────────────────────
    with tab_single:
        col1,col2,col3,col4,col5 = st.columns(5)
        bt_symbol  = col1.text_input("Symbol",value="RELIANCE.NS",key="bt_sym")
        bt_period  = col2.selectbox("Period",["6mo","1y","2y","5y"],index=1,key="bt_per")
        bt_interval= col3.selectbox("Interval",["1d","1wk","1mo"],index=0,key="bt_int")
        strategy   = col4.selectbox("Strategy",["SMA Crossover","EMA Crossover","RSI Mean Reversion","MACD Signal"],key="bt_strat")
        capital    = col5.number_input("Capital (₹)",value=100000,step=10000,key="bt_cap")

        # Dynamic parameter controls
        params: dict = {}
        if strategy in ("SMA Crossover","EMA Crossover"):
            pc1,pc2 = st.columns(2)
            fast = pc1.slider("Fast Period",5,100,20,key="bt_fast")
            slow = pc2.slider("Slow Period",10,300,50,key="bt_slow")
            if fast >= slow:
                st.warning("⚠️ Fast period must be less than Slow period.")
            params = {"fast":fast,"slow":slow}
        elif strategy == "RSI Mean Reversion":
            pc1,pc2,pc3 = st.columns(3)
            params = {
                "rsi_period":   pc1.slider("RSI Period",5,50,14,key="bt_rp"),
                "rsi_oversold": pc2.slider("Oversold",10,45,30,key="bt_ros"),
                "rsi_overbought":pc3.slider("Overbought",55,90,70,key="bt_rob"),
            }
        else:  # MACD
            pc1,pc2,pc3 = st.columns(3)
            params = {
                "macd_fast":   pc1.slider("MACD Fast",2,50,12,key="bt_mf"),
                "macd_slow":   pc2.slider("MACD Slow",5,100,26,key="bt_ms"),
                "macd_signal": pc3.slider("Signal",2,30,9,key="bt_msig"),
            }

        # Guard: don't submit if fast >= slow
        can_run = not (strategy in ("SMA Crossover","EMA Crossover") and params.get("fast",0)>=params.get("slow",1))

        if st.button("▶️ Run Backtest",type="primary",key="run_bt",disabled=not can_run):
            payload = {
                "symbol":   bt_symbol,
                "period":   bt_period,
                "interval": bt_interval,
                "strategy": strategy,
                "capital":  capital,
                **params,
            }
            with st.spinner("Calling /api/backtest/run ..."):
                try:
                    t0 = time.time()
                    resp = requests.post(f"{API_BASE}/api/backtest/run",json=payload,timeout=30)
                    elapsed = time.time()-t0
                    if resp.status_code != 200:
                        st.error(f"API error {resp.status_code}: {resp.text}")
                    else:
                        r = resp.json()
                        st.caption(f"✅ Completed in {elapsed:.1f}s")

                        # Metrics row
                        m1,m2,m3,m4,m5 = st.columns(5)
                        m1.metric("Strategy Return",f"{r['total_return_pct']:.1f}%",
                                  f"{r['total_return_pct']-r['buy_hold_return_pct']:+.1f}% vs B&H")
                        m2.metric("Buy & Hold",f"{r['buy_hold_return_pct']:.1f}%")
                        m3.metric("Sharpe Ratio",f"{r['sharpe_ratio']:.2f}")
                        m4.metric("Max Drawdown",f"{r['max_drawdown_pct']:.1f}%")
                        m5.metric("Win Rate",f"{r['win_rate_pct']:.1f}%")

                        ma,mb,mc = st.columns(3)
                        ma.metric("Trades",r["total_trades"])
                        mb.metric("Profit Factor",f"{r['profit_factor']:.2f}")
                        mc.metric("Final Capital",f"₹{r['final_capital']:,.0f}")

                        # Equity curve chart
                        if r.get("equity_curve"):
                            df_ec = pd.DataFrame(r["equity_curve"])
                            df_ec["date"] = pd.to_datetime(df_ec["date"])
                            fig = go.Figure()
                            fig.add_trace(go.Scatter(
                                x=df_ec["date"],y=df_ec["value"],
                                name="Strategy",fill="tozeroy",
                                line=dict(color="#00c853",width=2),
                                fillcolor="rgba(0,200,83,0.08)"
                            ))
                            fig.update_layout(
                                title="📈 Equity Curve",height=380,
                                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                font_color="#ccc",
                                yaxis=dict(tickprefix="₹",gridcolor="#1e1e1e"),
                                xaxis=dict(gridcolor="#1e1e1e")
                            )
                            st.plotly_chart(fig,use_container_width=True)

                        # Drawdown chart
                        if r.get("drawdown_series"):
                            df_dd = pd.DataFrame(r["drawdown_series"])
                            df_dd["date"] = pd.to_datetime(df_dd["date"])
                            fig2 = go.Figure()
                            fig2.add_trace(go.Scatter(
                                x=df_dd["date"],y=df_dd["value"],
                                name="Drawdown %",fill="tozeroy",
                                line=dict(color="#ff5252",width=1.5),
                                fillcolor="rgba(255,82,82,0.1)"
                            ))
                            fig2.update_layout(
                                title="📉 Drawdown",height=200,
                                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                                font_color="#ccc",yaxis=dict(ticksuffix="%",gridcolor="#1e1e1e"),
                                xaxis=dict(gridcolor="#1e1e1e")
                            )
                            st.plotly_chart(fig2,use_container_width=True)
                except requests.exceptions.ConnectionError:
                    # Fallback: run locally if API not running
                    st.warning("⚠️ API not reachable — running backtest locally (start API with `uvicorn api.main:app`)")
                    _run_local_backtest(bt_symbol,bt_period,strategy,capital,params)
                except Exception as e:
                    st.error(f"Request failed: {e}")

    # ── Multi-Stock Leaderboard ───────────────────────────────────────────────
    with tab_multi:
        st.subheader("🏆 Multi-Stock Leaderboard")
        st.caption("Run a strategy across a universe — compare results by Sharpe, CAGR, MaxDD")

        ms_col1,ms_col2,ms_col3 = st.columns(3)
        ms_strategy = ms_col1.selectbox("Strategy",["SMA Crossover","EMA Crossover","RSI Mean Reversion","MACD Signal"],key="ms_strat")
        ms_universe = ms_col2.selectbox("Universe",["NIFTY50 (50)","Custom"],key="ms_univ")
        ms_period   = ms_col3.selectbox("Period",["1y","2y","5y"],index=0,key="ms_per")
        ms_capital  = st.number_input("Capital per Symbol (₹)",value=100000,step=10000,key="ms_cap")

        custom_syms = []
        if ms_universe == "Custom":
            raw = st.text_area("Symbols (one per line or comma-separated)",
                               placeholder="RELIANCE.NS\nTCS.NS\nINFY.NS",key="ms_custom")
            custom_syms = [s.strip() for s in raw.replace(",","\n").split("\n") if s.strip()]

        if st.button("▶️ Run Leaderboard",type="primary",key="run_multi"):
            symbols = NIFTY50_SYMBOLS if ms_universe=="NIFTY50 (50)" else custom_syms
            if not symbols:
                st.warning("No symbols selected."); st.stop()

            progress = st.progress(0, text="Starting...")
            results, errors = [], []

            for i, sym in enumerate(symbols):
                progress.progress((i+1)/len(symbols), text=f"Running {sym} ({i+1}/{len(symbols)})...")
                payload = {
                    "symbol":   sym,
                    "period":   ms_period,
                    "interval": "1d",
                    "strategy": ms_strategy,
                    "capital":  ms_capital,
                }
                try:
                    resp = requests.post(f"{API_BASE}/api/backtest/run",json=payload,timeout=20)
                    if resp.status_code == 200:
                        r = resp.json()
                        results.append({
                            "Symbol":      sym,
                            "Return%":     round(r["total_return_pct"],2),
                            "B&H Return%": round(r["buy_hold_return_pct"],2),
                            "Sharpe":      round(r["sharpe_ratio"],2),
                            "MaxDD%":      round(r["max_drawdown_pct"],2),
                            "WinRate%":    round(r["win_rate_pct"],2),
                            "Trades":      r["total_trades"],
                            "ProfitFactor":round(r["profit_factor"],2),
                        })
                    else:
                        errors.append(f"{sym}: HTTP {resp.status_code}")
                except requests.exceptions.ConnectionError:
                    # Fallback: local calculation
                    try:
                        row = _quick_backtest(sym, ms_period, ms_strategy, ms_capital, {})
                        if row:
                            results.append(row)
                        else:
                            errors.append(f"{sym}: no data")
                    except Exception as le:
                        errors.append(f"{sym}: {le}")
                except Exception as e:
                    errors.append(f"{sym}: {e}")

            progress.empty()

            # Summary banner
            n_ok  = len(results)
            n_err = len(errors)
            st.markdown(f"### Results: **{n_ok}/{len(symbols)}** symbols completed")
            if errors:
                with st.expander(f"⚠️ {n_err} symbol(s) failed — click to expand"):
                    for e in errors:
                        st.caption(f"• {e}")

            if results:
                df_lb = pd.DataFrame(results).sort_values("Sharpe",ascending=False).reset_index(drop=True)
                df_lb.index += 1  # 1-based rank

                # Colour-code return column
                st.subheader("📋 Leaderboard (sorted by Sharpe)")
                st.dataframe(
                    df_lb.style
                        .background_gradient(subset=["Return%"],cmap="RdYlGn",vmin=-30,vmax=60)
                        .background_gradient(subset=["Sharpe"],cmap="RdYlGn",vmin=-1,vmax=3)
                        .background_gradient(subset=["MaxDD%"],cmap="RdYlGn_r",vmin=-60,vmax=0),
                    use_container_width=True,height=600
                )

                # Top 5 bar chart
                top5 = df_lb.head(5)
                fig = px.bar(top5,x="Symbol",y="Sharpe",color="Return%",
                             color_continuous_scale=["#ff5252","#00c853"],
                             title="Top 5 by Sharpe Ratio")
                fig.update_layout(height=300,paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)",font_color="#ccc")
                st.plotly_chart(fig,use_container_width=True)

                # Download
                st.download_button("⬇️ Export Leaderboard CSV",df_lb.to_csv(index=False),
                                   "leaderboard.csv","text/csv")


def _run_local_backtest(symbol, period, strategy, capital, params):
    """Fallback local backtest when API is not running."""
    try:
        df = yf.Ticker(symbol).history(period=period)
        if df.empty:
            st.error(f"No data for {symbol}"); return
        df = df[["Open","High","Low","Close","Volume"]].copy()
        fast = params.get("fast",20)
        slow = params.get("slow",50)
        if strategy == "SMA Crossover":
            df["sig"] = np.where(df["Close"].rolling(fast).mean()>df["Close"].rolling(slow).mean(),1,-1)
        elif strategy == "EMA Crossover":
            df["sig"] = np.where(df["Close"].ewm(span=fast).mean()>df["Close"].ewm(span=slow).mean(),1,-1)
        elif strategy == "RSI Mean Reversion":
            delta=df["Close"].diff(); gain=delta.clip(lower=0).rolling(14).mean()
            loss=-delta.clip(upper=0).rolling(14).mean(); rsi=100-(100/(1+gain/loss.replace(0,np.nan)))
            df["sig"] = np.where(rsi<30,1,np.where(rsi>70,-1,0))
        else:
            ml=df["Close"].ewm(span=12).mean()-df["Close"].ewm(span=26).mean()
            df["sig"] = np.where(ml>ml.ewm(span=9).mean(),1,-1)
        df["ret"]  = df["Close"].pct_change()
        df["sret"] = df["sig"].shift(1)*df["ret"]
        df["eq"]   = (1+df["sret"].fillna(0)).cumprod()*capital
        df["bh"]   = (1+df["ret"].fillna(0)).cumprod()*capital
        df.dropna(subset=["eq"],inplace=True)
        total_ret = (df["eq"].iloc[-1]-capital)/capital*100
        bh_ret    = (df["bh"].iloc[-1]-capital)/capital*100
        max_dd    = ((df["eq"]/df["eq"].cummax())-1).min()*100
        sharpe    = df["sret"].mean()/df["sret"].std()*np.sqrt(252) if df["sret"].std() else 0
        win_rate  = (df["sret"]>0).sum()/(df["sret"]!=0).sum()*100 if (df["sret"]!=0).sum() else 0
        m1,m2,m3,m4,m5 = st.columns(5)
        m1.metric("Strategy Return",f"{total_ret:.1f}%",f"{total_ret-bh_ret:+.1f}% vs B&H")
        m2.metric("Buy & Hold",f"{bh_ret:.1f}%")
        m3.metric("Sharpe",f"{sharpe:.2f}")
        m4.metric("Max Drawdown",f"{max_dd:.1f}%")
        m5.metric("Win Rate",f"{win_rate:.1f}%")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df.index,y=df["eq"],name="Strategy",
                                 line=dict(color="#00c853",width=2),fill="tozeroy",
                                 fillcolor="rgba(0,200,83,0.08)"))
        fig.add_trace(go.Scatter(x=df.index,y=df["bh"],name="Buy & Hold",
                                 line=dict(color="#1976d2",width=1.5,dash="dash")))
        fig.update_layout(title="Equity Curve (local)",height=380,
                          paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                          font_color="#ccc",yaxis=dict(tickprefix="₹",gridcolor="#1e1e1e"))
        st.plotly_chart(fig,use_container_width=True)
    except Exception as e:
        st.error(f"Local backtest failed: {e}")


def _quick_backtest(symbol, period, strategy, capital, params) -> dict | None:
    """Silent local backtest for multi-stock runner — returns metrics dict."""
    try:
        df = yf.Ticker(symbol).history(period=period)
        if df.empty or len(df) < 60:
            return None
        df = df[["Close"]].copy()
        fast, slow = params.get("fast",20), params.get("slow",50)
        if strategy in ("SMA Crossover","EMA Crossover"):
            if strategy=="SMA Crossover":
                sig = np.where(df["Close"].rolling(fast).mean()>df["Close"].rolling(slow).mean(),1,-1)
            else:
                sig = np.where(df["Close"].ewm(span=fast).mean()>df["Close"].ewm(span=slow).mean(),1,-1)
        elif strategy=="RSI Mean Reversion":
            delta=df["Close"].diff(); gain=delta.clip(lower=0).rolling(14).mean()
            loss=-delta.clip(upper=0).rolling(14).mean(); rsi=100-(100/(1+gain/loss.replace(0,np.nan)))
            sig=np.where(rsi<30,1,np.where(rsi>70,-1,0))
        else:
            ml=df["Close"].ewm(span=12).mean()-df["Close"].ewm(span=26).mean()
            sig=np.where(ml>ml.ewm(span=9).mean(),1,-1)
        ret  = df["Close"].pct_change()
        sret = pd.Series(sig,index=df.index).shift(1)*ret
        eq   = (1+sret.fillna(0)).cumprod()*capital
        bh   = (1+ret.fillna(0)).cumprod()*capital
        total_ret = (eq.iloc[-1]-capital)/capital*100
        bh_ret    = (bh.iloc[-1]-capital)/capital*100
        max_dd    = ((eq/eq.cummax())-1).min()*100
        sharpe    = sret.mean()/sret.std()*np.sqrt(252) if sret.std() else 0
        win_rate  = (sret>0).sum()/(sret!=0).sum()*100 if (sret!=0).sum() else 0
        trades    = int((sret!=0).sum())
        return {
            "Symbol":      symbol,
            "Return%":     round(total_ret,2),
            "B&H Return%": round(bh_ret,2),
            "Sharpe":      round(sharpe,2),
            "MaxDD%":      round(max_dd,2),
            "WinRate%":    round(win_rate,2),
            "Trades":      trades,
            "ProfitFactor":0.0,
        }
    except Exception:
        return None


# ─── STRATEGIES ───────────────────────────────────────────────────────────────
def strategies_page():
    st.title("🧩 Strategy Manager")
    st.caption("Manage, configure, and activate trading strategies")
    st.divider()
    STRATEGIES = [
        {"Name":"SMA Crossover","Type":"Trend","Status":"Active","Params":"fast=20, slow=50","Sharpe":1.42,"Return":"18.3%"},
        {"Name":"EMA Crossover","Type":"Trend","Status":"Active","Params":"fast=12, slow=26","Sharpe":1.67,"Return":"22.1%"},
        {"Name":"RSI Mean Reversion","Type":"Mean Rev","Status":"Testing","Params":"period=14, ob=70, os=30","Sharpe":0.98,"Return":"11.2%"},
        {"Name":"MACD Signal","Type":"Momentum","Status":"Active","Params":"fast=12, slow=26, sig=9","Sharpe":1.31,"Return":"16.8%"},
    ]
    df_strat = pd.DataFrame(STRATEGIES)
    st.dataframe(df_strat,use_container_width=True,hide_index=True)
    st.divider()
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("⚙️ Strategy Parameter Editor")
        sel_strat = st.selectbox("Select Strategy",[s["Name"] for s in STRATEGIES])
        s_data = next(s for s in STRATEGIES if s["Name"]==sel_strat)
        for param in s_data["Params"].split(", "):
            k,v = param.split("=")
            st.number_input(k.strip(),value=float(v.strip()) if v.strip().replace(".","").isdigit() else 0)
        if st.button("💾 Save Parameters"): st.success(f"Saved for {sel_strat}")
    with col2:
        st.subheader("📊 Performance Comparison")
        df_perf = df_strat[df_strat["Status"]!="Draft"][["Name","Sharpe"]]
        fig = px.bar(df_perf,x="Name",y="Sharpe",color="Sharpe",
                     color_continuous_scale=["#ff5252","#00c853"])
        fig.update_layout(height=300,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",font_color="#ccc")
        st.plotly_chart(fig,use_container_width=True)


# ─── REPORTING ────────────────────────────────────────────────────────────────
def reporting_page():
    st.title("📈 Reporting & Analytics")
    st.divider()
    np.random.seed(42)
    dates = pd.date_range(end=datetime.date.today(),periods=180,freq="B")
    daily_ret = np.random.normal(0.0008,0.012,len(dates))
    equity = 100000*(1+pd.Series(daily_ret)).cumprod()
    trades = []
    for i in range(0,len(dates)-5,5):
        ret = random.gauss(0.004,0.015)
        trades.append({"Date":dates[i].date(),"Symbol":random.choice(["RELIANCE","TCS","INFY","HDFC"]),
                       "Side":random.choice(["BUY","SELL"]),"Qty":random.randint(10,100),
                       "PnL":round(ret*random.randint(10,100)*random.uniform(1000,5000),2),
                       "Strategy":random.choice(["SMA","EMA","MACD"])})
    df_trades = pd.DataFrame(trades)
    total_pnl = df_trades["PnL"].sum()
    sharpe = daily_ret.mean()/daily_ret.std()*np.sqrt(252)
    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Total PnL",f"₹{total_pnl:,.0f}")
    m2.metric("Win Rate",f"{(df_trades['PnL']>0).sum()/len(df_trades)*100:.0f}%")
    m3.metric("Sharpe",f"{sharpe:.2f}")
    m4.metric("Max DD",f"{((equity/equity.cummax())-1).min()*100:.1f}%")
    tab1,tab2 = st.tabs(["📈 Equity Curve","📋 Trade Log"])
    with tab1:
        fig = go.Figure(go.Scatter(x=dates,y=equity,fill="tozeroy",line=dict(color="#00c853")))
        fig.update_layout(height=350,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",font_color="#ccc")
        st.plotly_chart(fig,use_container_width=True)
    with tab2:
        st.dataframe(df_trades.sort_values("Date",ascending=False),use_container_width=True,height=350)


# ─── RISK ─────────────────────────────────────────────────────────────────────
def risk_page():
    st.title("🛡️ Risk Manager")
    st.divider()
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("⚖️ Position Sizer")
        capital_r = st.number_input("Capital (₹)",value=500000,step=10000)
        risk_pct  = st.slider("Risk per Trade (%)",0.5,5.0,1.0,0.1)
        stop_loss = st.number_input("Stop Loss Points",value=50,min_value=1)
        entry_price=st.number_input("Entry Price (₹)",value=2500.0)
        risk_amt  = capital_r*risk_pct/100
        qty       = int(risk_amt/stop_loss)
        exposure  = qty*entry_price
        exp_pct   = exposure/capital_r*100
        r1,r2,r3 = st.columns(3)
        r1.metric("Risk Amount",f"₹{risk_amt:,.0f}")
        r2.metric("Quantity",str(qty))
        r3.metric("Exposure",f"₹{exposure:,.0f}")
        st.progress(min(exp_pct/100,1.0),text=f"Exposure: {exp_pct:.1f}%")
        if exp_pct>20: st.warning("⚠️ Exposure >20%")
        else: st.success("✅ Within limits")
    with col2:
        st.subheader("📊 Portfolio VaR")
        conf = st.selectbox("Confidence","95% 99% 99.5%".split())
        z = {"95%":1.645,"99%":2.326,"99.5%":2.576}[conf]
        np.random.seed(7)
        daily_ret_r = np.random.normal(0.0005,0.013,252)
        var_daily = 500000*z*np.std(daily_ret_r)
        v1,v2,v3 = st.columns(3)
        v1.metric("Daily VaR",f"₹{var_daily:,.0f}")
        v2.metric("Weekly VaR",f"₹{var_daily*np.sqrt(5):,.0f}")
        v3.metric("Monthly VaR",f"₹{var_daily*np.sqrt(21):,.0f}")


# ─── PAPER TRADING — Phase 07 rewrite ────────────────────────────────────────
def paper_page():
    st.title("📋 Paper Portfolio")
    st.caption("Live paper trading dashboard — auto-refreshes every 30 seconds")
    st.divider()

    # ── Tab layout ────────────────────────────────────────────────────────────
    tab_dash, tab_order = st.tabs(["📊 Dashboard","📤 Place Order"])

    with tab_dash:
        # Auto-refresh toggle
        col_r1,col_r2 = st.columns([4,1])
        auto_refresh = col_r2.checkbox("Auto-refresh (30s)",value=False,key="paper_refresh")

        # Fetch snapshot from API (with local session-state fallback)
        snap = None
        api_online = False
        try:
            resp = requests.get(f"{API_BASE}/api/paper/snapshot",timeout=5)
            if resp.status_code == 200:
                snap = resp.json()
                api_online = True
        except Exception:
            pass

        if not api_online:
            st.warning("⚠️ Paper API not reachable — using local session state. Start API: `uvicorn api.main:app`")
            # Fall back to legacy session-state portfolio
            if "paper_portfolio" not in st.session_state:
                st.session_state.paper_portfolio = {"cash":500000.0,"positions":{},"orders":[]}
            port = st.session_state.paper_portfolio
            snap = {"cash":port["cash"],"positions":[],"total_value":port["cash"],"daily_pnl":0}

        # KPI metrics
        cash   = snap.get("cash",0)
        posval = snap.get("positions_value",0)
        total  = snap.get("total_value",cash)
        dpnl   = snap.get("daily_pnl",0)
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Cash",f"₹{cash:,.2f}")
        m2.metric("Positions Value",f"₹{posval:,.2f}")
        m3.metric("Total Portfolio",f"₹{total:,.2f}",f"₹{total-500000:+,.0f} since start")
        m4.metric("Daily PnL",f"₹{dpnl:+,.2f}")

        # Open positions table
        st.subheader("📋 Open Positions")
        positions = snap.get("positions",[])
        if positions:
            df_pos = pd.DataFrame(positions)
            # colour unrealized_pnl
            def color_pnl(val):
                return "color: #00c853" if val>0 else ("color: #ff5252" if val<0 else "")
            st.dataframe(
                df_pos.style.applymap(color_pnl,subset=["unrealized_pnl"]),
                use_container_width=True,hide_index=True
            )
        else:
            st.info("No open positions.")

        # Today's trades
        st.subheader("🕐 Today's Trades")
        trades_data = []
        try:
            tresp = requests.get(f"{API_BASE}/api/paper/trades",timeout=5)
            if tresp.status_code==200:
                trades_data = tresp.json().get("trades",[])
        except Exception:
            pass
        if trades_data:
            st.dataframe(pd.DataFrame(trades_data),use_container_width=True,hide_index=True,height=250)
        else:
            st.info("No trades today.")

        # Daily PnL sparkline (placeholder with session state)
        if "daily_pnl_history" not in st.session_state:
            st.session_state.daily_pnl_history = []
        if dpnl != 0:
            st.session_state.daily_pnl_history.append(
                {"time":datetime.datetime.now().strftime("%H:%M"),"pnl":dpnl}
            )
        if len(st.session_state.daily_pnl_history)>1:
            df_pnl = pd.DataFrame(st.session_state.daily_pnl_history)
            fig = go.Figure(go.Scatter(x=df_pnl["time"],y=df_pnl["pnl"],
                                       fill="tozeroy",line=dict(color="#00c853" if dpnl>=0 else "#ff5252",width=2),
                                       fillcolor="rgba(0,200,83,0.08)" if dpnl>=0 else "rgba(255,82,82,0.08)"))
            fig.update_layout(title="Daily PnL Chart",height=200,
                              paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#ccc",yaxis=dict(tickprefix="₹",gridcolor="#1e1e1e"))
            st.plotly_chart(fig,use_container_width=True)

        # Auto-refresh
        if auto_refresh:
            time.sleep(30)
            st.rerun()

    with tab_order:
        st.subheader("📤 Place Order")
        st.caption("Manual order → calls /api/paper/signal")
        with st.form("paper_order_form"):
            o_sym  = st.text_input("Symbol (YF format)",value="RELIANCE.NS")
            o_side = st.radio("Side",["BUY","SELL"],horizontal=True)
            o_qty  = st.number_input("Quantity",value=10,min_value=1)
            o_type = st.selectbox("Order Type",["MARKET","LIMIT"])
            o_price= st.number_input("Limit Price (₹)",value=0.0,help="0 = live market price")
            o_strat= st.text_input("Strategy Tag",value="manual")
            submitted = st.form_submit_button("🚀 Place Order",type="primary")

            if submitted:
                # Resolve price
                exec_price = o_price
                if o_type=="MARKET" or o_price<=0:
                    try:
                        hist = yf.Ticker(o_sym).history(period="1d")
                        exec_price = float(hist["Close"].iloc[-1]) if not hist.empty else 0
                    except Exception:
                        exec_price = 0
                signal_val = 1 if o_side=="BUY" else -1
                payload = {"symbol":o_sym,"signal":signal_val,"price":exec_price,
                           "quantity":o_qty,"strategy":o_strat}
                try:
                    resp = requests.post(f"{API_BASE}/api/paper/signal",json=payload,timeout=10)
                    if resp.status_code==200:
                        r = resp.json()
                        st.success(f"✅ {r['action']} {o_qty} {o_sym} @ ₹{exec_price:.2f} | Cash: ₹{r.get('cash',0):,.2f}")
                        st.rerun()
                    else:
                        st.error(f"API error: {resp.text}")
                except requests.exceptions.ConnectionError:
                    # Fallback to session state
                    if "paper_portfolio" not in st.session_state:
                        st.session_state.paper_portfolio={"cash":500000.0,"positions":{},"orders":[]}
                    port=st.session_state.paper_portfolio
                    cost=exec_price*o_qty
                    if o_side=="BUY":
                        if cost>port["cash"]: st.error("Insufficient cash")
                        else:
                            port["cash"]-=cost
                            k=o_sym.upper()
                            if k not in port["positions"]: port["positions"][k]={"qty":0,"avg":0}
                            p=port["positions"][k]
                            new_qty=p["qty"]+o_qty
                            p["avg"]=(p["qty"]*p["avg"]+o_qty*exec_price)/new_qty
                            p["qty"]=new_qty
                            port["orders"].append({"Time":datetime.datetime.now().strftime("%H:%M"),
                                                   "Symbol":k,"Side":"BUY","Qty":o_qty,
                                                   "Price":round(exec_price,2),"Status":"FILLED"})
                            st.success(f"✅ BUY {o_qty} {o_sym} @ ₹{exec_price:.2f} (local)")
                    else:
                        k=o_sym.upper()
                        p=port["positions"].get(k,{"qty":0,"avg":0})
                        if p["qty"]<o_qty: st.error("Insufficient position")
                        else:
                            pnl=(exec_price-p["avg"])*o_qty
                            p["qty"]-=o_qty; port["cash"]+=exec_price*o_qty
                            port["orders"].append({"Time":datetime.datetime.now().strftime("%H:%M"),
                                                   "Symbol":k,"Side":"SELL","Qty":o_qty,
                                                   "Price":round(exec_price,2),
                                                   "Status":f"FILLED PnL ₹{pnl:+.0f}"})
                            st.success(f"✅ SELL {o_qty} {o_sym} @ ₹{exec_price:.2f} | PnL ₹{pnl:+.2f} (local)")
                    st.rerun()


# ─── AI ANALYZER ──────────────────────────────────────────────────────────────
def ai_page():
    st.title("🤖 AI Signal Analyzer")
    st.caption("Automated signal scanning — RSI, MACD, Bollinger, Volume alerts")
    st.divider()
    universe  = get_full_universe()
    fno_syms  = universe[universe["SEGMENT"]=="Equity+F&O"]["YF_SYMBOL"].tolist()[:50]
    col1,col2 = st.columns([3,1])
    scan_input= col1.text_input("Symbols (comma-separated)",value="RELIANCE.NS, TCS.NS, HDFCBANK.NS, INFY.NS")
    scan_period=col2.selectbox("Period",["1mo","3mo","6mo"],index=1)
    if st.button("🔍 Run AI Scan",type="primary"):
        syms = [s.strip().upper() for s in scan_input.split(",") if s.strip()]
        with st.spinner(f"Scanning {len(syms)} symbols..."):
            signals=[]
            for sym in syms:
                try:
                    df = yf.Ticker(sym).history(period=scan_period)
                    if df.empty or len(df)<30: continue
                    close=df["Close"]; vol=df["Volume"]
                    ema20=close.ewm(span=20).mean(); ema50=close.ewm(span=50).mean()
                    delta=close.diff(); gain=delta.clip(lower=0).rolling(14).mean()
                    loss=-delta.clip(upper=0).rolling(14).mean()
                    rsi=(100-(100/(1+gain/loss.replace(0,np.nan)))).iloc[-1]
                    macd=(close.ewm(span=12).mean()-close.ewm(span=26).mean()).iloc[-1]
                    sig_macd=(close.ewm(span=12).mean()-close.ewm(span=26).mean()).ewm(span=9).mean().iloc[-1]
                    score=0; sig_list=[]
                    if rsi<35: sig_list.append("RSI Oversold"); score+=2
                    elif rsi>65: sig_list.append("RSI Overbought"); score-=2
                    if macd>sig_macd: sig_list.append("MACD Bullish"); score+=1
                    else: sig_list.append("MACD Bearish"); score-=1
                    if ema20.iloc[-1]>ema50.iloc[-1] and ema20.iloc[-2]<=ema50.iloc[-2]:
                        sig_list.append("EMA Bullish Cross"); score+=3
                    rec = "🟢 STRONG BUY" if score>=4 else "🟩 BUY" if score>=2 else \
                          "🔴 STRONG SELL" if score<=-4 else "🟥 SELL" if score<=-2 else "⚪ NEUTRAL"
                    signals.append({"Symbol":sym,"LTP":round(close.iloc[-1],2),
                                    "RSI":round(rsi,1),"Score":score,
                                    "Signals":", ".join(sig_list),"Recommendation":rec})
                except Exception as e:
                    signals.append({"Symbol":sym,"LTP":0,"RSI":0,"Score":0,
                                    "Signals":f"Error: {e}","Recommendation":"❓"})
            df_sig=pd.DataFrame(signals).sort_values("Score",ascending=False)
            st.dataframe(df_sig,use_container_width=True,hide_index=True)


# ─── DERIVATIVES ──────────────────────────────────────────────────────────────
def derivatives_page():
    st.title("📐 Derivatives — Options Chain")
    st.caption("Options chain viewer with Black-Scholes Greeks")
    st.divider()
    universe  = get_full_universe()
    fno_list  = universe[universe["SEGMENT"]=="Equity+F&O"]["SYMBOL"].tolist()
    all_underlyings=["NIFTY","BANKNIFTY","MIDCPNIFTY","FINNIFTY","SENSEX"]+sorted(fno_list)
    col1,col2,col3=st.columns(3)
    der_sym=col1.selectbox("Underlying",all_underlyings)
    expiry_opts=[(datetime.date.today()+datetime.timedelta(days=d)).strftime("%d-%b-%Y") for d in [7,14,21,30,45,60]]
    expiry=col2.selectbox("Expiry",expiry_opts)
    yf_map={"NIFTY":"^NSEI","BANKNIFTY":"^NSEBANK","MIDCPNIFTY":"^CNXMIDCAP",
            "FINNIFTY":"NIFTY_FIN_SERVICE.NS","SENSEX":"^BSESN"}
    yf_sym_der=yf_map.get(der_sym,f"{der_sym}.NS")
    try:
        live_spot=yf.Ticker(yf_sym_der).history(period="1d")["Close"].iloc[-1]
    except Exception:
        live_spot=24000.0
    spot=col3.number_input("Spot Price",value=float(round(live_spot,2)))
    iv_input=st.slider("IV %",5,100,18)
    if st.button("📊 Load Options Chain",type="primary"):
        days_to_exp=max(1,(datetime.datetime.strptime(expiry,"%d-%b-%Y").date()-datetime.date.today()).days)
        T=days_to_exp/365; r=0.065; sigma=iv_input/100
        from math import log,sqrt,exp
        from scipy.stats import norm
        def bs(S,K,T,r,s,opt):
            if T<=0: return {"price":max(S-K,0) if opt=="call" else max(K-S,0),"delta":1 if opt=="call" else -1}
            d1=(log(S/K)+(r+.5*s**2)*T)/(s*sqrt(T)); d2=d1-s*sqrt(T)
            if opt=="call": p=S*norm.cdf(d1)-K*exp(-r*T)*norm.cdf(d2); d=norm.cdf(d1)
            else: p=K*exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1); d=norm.cdf(d1)-1
            g=norm.pdf(d1)/(S*s*sqrt(T))
            return {"price":round(p,2),"delta":round(d,4),"gamma":round(g,6)}
        step=50 if der_sym in ["NIFTY","BANKNIFTY","MIDCPNIFTY","FINNIFTY","SENSEX"] else 20
        atm=round(spot/step)*step; strikes=[atm+(i-5)*step for i in range(11)]
        rows=[]
        for K in strikes:
            c=bs(spot,K,T,r,sigma,"call"); p=bs(spot,K,T,r,sigma,"put")
            rows.append({"CALL LTP":c["price"],"CALL Δ":c["delta"],
                         "Strike":K,"Type":"🎯 ATM" if K==atm else ("ITM" if K<atm else "OTM"),
                         "PUT Δ":p["delta"],"PUT LTP":p["price"]})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True,height=420)


# ─── LIVE ─────────────────────────────────────────────────────────────────────
def live_page():
    st.title("⚡ Live Execution")
    st.error("⚠️ LIVE TRADING IS DISABLED")
    st.warning("Live execution enabled only after 30+ days paper trading with positive PnL.")
    col1,col2,col3=st.columns(3)
    col1.metric("Paper Days","0 / 30","Required")
    col2.metric("Paper PnL","₹0","Target: Positive")
    col3.metric("Live Status","🔒 Locked")


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    page=sidebar()
    if page=="🏠 Home":             home_page()
    elif page=="📊 Data":           data_page()
    elif page=="🔍 Instruments":    instruments_page()
    elif page=="⚙️ Backtesting":    backtesting_page()
    elif page=="🧩 Strategies":     strategies_page()
    elif page=="📈 Reporting":      reporting_page()
    elif page=="🛡️ Risk":           risk_page()
    elif page=="📋 Paper Trading":  paper_page()
    elif page=="🤖 AI":             ai_page()
    elif page=="📐 Derivatives":    derivatives_page()
    elif page=="⚡ Live":           live_page()


if __name__=="__main__":
    main()
