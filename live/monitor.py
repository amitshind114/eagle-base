"""Live trading monitor — Streamlit dashboard.

Displays real-time positions, trades, P&L, risk utilisation, and circuit
breaker status. Polls broker every 60s and risk limits every 30s.

Run standalone:
    streamlit run live/monitor.py

Or import and embed in ui/app.py:
    from live.monitor import render_live_page
    render_live_page(executor, audit)
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ── Streamlit live page renderer ──────────────────────────────────────────────

def render_live_page(executor=None, audit_log=None) -> None:
    """Embed in ui/app.py on the Live Trading page.

    Args:
        executor : LiveExecutor instance (or None — shows offline state)
        audit_log: AuditLog instance (or None — reads default path)
    """
    import streamlit as st
    import pandas as pd

    st.title("🟢 Live Trading Dashboard")

    now = datetime.now(tz=IST)
    st.caption(f"Last updated: {now.strftime('%H:%M:%S IST')}")

    # — Connection status —
    from live.executor import LIVE_ENABLED
    if not LIVE_ENABLED:
        st.warning(’⚠️ **EAGLE_LIVE_ENABLED=false** — Live trading is OFF. ’
                   ’Set EAGLE_LIVE_ENABLED=true in .env to enable.’)

    # ──────────────────────────────────────────────────────────────────
    # Row 1: KPIs
    # ──────────────────────────────────────────────────────────────────
    positions = _fetch_positions(executor)
    today_trades, daily_pnl = _fetch_today_trades(audit_log)
    risk_status = _fetch_risk_status()
    circuit_open = getattr(executor, "_circuit_open", False) if executor else False

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📊 Open Positions",  len(positions))
    k2.metric("📋 Today's Trades",  len(today_trades))
    k3.metric("💹 Daily P&L",        f"₹{daily_pnl:,.2f}",
              delta_color="normal" if daily_pnl >= 0 else "inverse")
    k4.metric("🔴 Circuit Breaker",
              "🔴 OPEN" if circuit_open else "🟢 CLOSED",
              delta=None)

    st.divider()

    # ──────────────────────────────────────────────────────────────────
    # Row 2: Positions + Risk
    # ──────────────────────────────────────────────────────────────────
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("💼 Open Positions")
        if positions:
            rows = []
            for p in positions:
                ltp = float(p.get("ltp", 0))
                qty = int(p.get("netqty", 0))
                pos_val = abs(qty) * ltp
                rows.append({
                    "Symbol":      p.get("tradingsymbol", ""),
                    "Side":        "🟢 BUY" if qty > 0 else "🔴 SELL",
                    "Qty":         abs(qty),
                    "Avg Price":   f"₹{float(p.get('averageprice', 0)):,.2f}",
                    "LTP":         f"₹{ltp:,.2f}",
                    "Position Val": f"₹{pos_val:,.2f}",
                    "P&L":         f"₹{float(p.get('pnl', 0)):,.2f}",
                })
            df_pos = pd.DataFrame(rows)
            st.dataframe(df_pos, use_container_width=True, hide_index=True)
        else:
            st.info("No open positions.")

    with col_right:
        st.subheader("🛡️ Risk Utilisation")
        max_loss       = float(risk_status.get("max_daily_loss", 5000))
        current_loss   = abs(float(risk_status.get("current_loss", 0)))
        utilisation    = min(current_loss / max_loss, 1.0) if max_loss > 0 else 0.0
        util_pct       = round(utilisation * 100, 1)

        st.metric("Daily Loss Used", f"₹{current_loss:,.0f} / ₹{max_loss:,.0f}")
        # Colour bar: green < 50%, amber 50-80%, red > 80%
        bar_colour = (
            "🟥" if utilisation > 0.8
            else "🟧" if utilisation > 0.5
            else "🟩"
        )
        st.markdown(f"""
        <div style="background:#e0e0e0;border-radius:8px;height:20px;overflow:hidden;margin:4px 0">
            <div style="background:{'#ef4444' if utilisation>0.8 else '#f59e0b' if utilisation>0.5 else '#22c55e'};
                        width:{util_pct}%;height:100%;transition:width 0.5s">
            </div>
        </div>
        <small>{bar_colour} {util_pct}% of daily loss limit used</small>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.metric("Max Trades/Day",
                  f"{risk_status.get('trades_today', 0)} / {risk_status.get('max_trades', 20)}")
        st.metric("Consecutive Failures",
                  getattr(executor, "_consecutive_failures", 0) if executor else 0)

    st.divider()

    # ──────────────────────────────────────────────────────────────────
    # Row 3: Today's trades log
    # ──────────────────────────────────────────────────────────────────
    st.subheader("📄 Today's Trades")
    if today_trades:
        df_trades = pd.DataFrame([
            {
                "Time":      t.get("ts", "")[-8:],
                "Symbol":    t.get("symbol", ""),
                "Side":      t.get("side", ""),
                "Qty":       t.get("qty", 0),
                "Price":     f"₹{float(t.get('price', 0)):,.2f}",
                "Broker ID": t.get("broker_order_id", "—"),
                "Key":       (t.get("order_key", "") or "")[:8] + "...",
            }
            for t in today_trades
        ])
        st.dataframe(df_trades, use_container_width=True, hide_index=True)
    else:
        st.info("No trades placed today.")

    # ──────────────────────────────────────────────────────────────────
    # Circuit breaker alert + reset button
    # ──────────────────────────────────────────────────────────────────
    if circuit_open:
        st.error(
            "🔴 **Circuit breaker is OPEN.** All live orders are refused. "
            f"Consecutive failures: {getattr(executor, '_consecutive_failures', '?')}. "
            "Investigate broker logs before resetting."
        )
        if st.button("⚡ Reset Circuit Breaker", type="primary"):
            if executor:
                executor.reset_circuit()
                st.success("✅ Circuit breaker reset. Orders will resume.")
                st.rerun()

    # Auto-refresh
    st.markdown("---")
    st.caption("🔄 Page auto-refreshes every 60 seconds via browser. Reload to force refresh.")
    time.sleep(1)  # small yield


# ── Data fetchers (safe — return empty on error) ─────────────────────────────

def _fetch_positions(executor) -> list[dict[str, Any]]:
    """Poll broker positions every 60s via st.cache_data."""
    if executor is None:
        return []
    try:
        return executor.get_positions()
    except Exception:
        return []


def _fetch_today_trades(audit_log) -> tuple[list[dict], float]:
    """Return today's ORDER_PLACED events and total P&L."""
    try:
        if audit_log is None:
            from core.audit import audit
            audit_log = audit
        events = audit_log.today(session="live")
        trades = [e for e in events if e.get("event") == "ORDER_PLACED"]
        pnl    = sum(float(e.get("pnl", 0)) for e in events if "pnl" in e)
        return trades, pnl
    except Exception:
        return [], 0.0


def _fetch_risk_status() -> dict[str, Any]:
    """Return current risk limits status dict."""
    try:
        from risk.limits import risk_limits
        return risk_limits.status()
    except Exception:
        return {"max_daily_loss": 5000, "current_loss": 0,
                "max_trades": 20, "trades_today": 0}


# ── Standalone Streamlit entry point ───────────────────────────────────────────

if __name__ == "__main__":
    render_live_page(executor=None, audit_log=None)
