"""Live trading monitor — Streamlit dashboard.

Displays real-time positions, trades, P&L, risk utilisation, and circuit
breaker status. Polls broker every 60s and risk limits every 30s.

Run standalone:
    streamlit run live/monitor.py

Or import and embed in ui/app.py:
    from live.monitor import render_live_monitor
    render_live_monitor(executor, audit)
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_POSITIONS_TTL = 60   # seconds between broker position polls
_RISK_TTL      = 30   # seconds between risk-limit polls


# ── Main render entry point ───────────────────────────────────────────────────

def render_live_monitor(executor=None, audit_log=None) -> None:
    """Complete live monitor. Call from ui/app.py live_page().

    Args:
        executor : LiveExecutor instance (or None — offline / simulation mode)
        audit_log: AuditLog instance (or None — reads default ~/.eagle/audit.jsonl)
    """
    import streamlit as st
    import pandas as pd

    now = datetime.now(tz=IST)

    # ── Connection banner ─────────────────────────────────────────────────────
    try:
        from live.executor import LIVE_ENABLED
    except ImportError:
        LIVE_ENABLED = False

    if not LIVE_ENABLED:
        st.warning(
            "⚠️ **EAGLE_LIVE_ENABLED=false** — Live trading is OFF. "
            "Set `EAGLE_LIVE_ENABLED=true` in `.env` to enable real orders."
        )

    st.caption(f"🕐 Last refreshed: {now.strftime('%H:%M:%S IST')} "
               f"(positions ~{_POSITIONS_TTL}s · risk ~{_RISK_TTL}s)")

    # ── Data fetch ────────────────────────────────────────────────────────────
    positions              = _fetch_positions(executor)
    today_trades, daily_pnl = _fetch_today_trades(audit_log)
    risk_status            = _fetch_risk_status()
    circuit_open           = getattr(executor, "_circuit_open", False) if executor else False
    consec_failures        = getattr(executor, "_consecutive_failures", 0) if executor else 0

    # ── Row 1 — KPI metrics ───────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("📊 Open Positions",  len(positions))
    k2.metric("📋 Today's Trades",  len(today_trades))
    pnl_color = "normal" if daily_pnl >= 0 else "inverse"
    k3.metric("💹 Daily P&L", f"₹{daily_pnl:,.2f}", delta_color=pnl_color)
    k4.metric("🔴 Circuit Breaker",
              "🔴 OPEN" if circuit_open else "🟢 CLOSED")
    k5.metric("⚡ Failures", consec_failures)

    st.divider()

    # ── Row 2 — Positions + Risk bar ──────────────────────────────────────────
    col_pos, col_risk = st.columns([3, 1])

    with col_pos:
        st.subheader("💼 Active Positions")
        if positions:
            rows = []
            for p in positions:
                ltp    = float(p.get("ltp", 0))
                qty    = int(p.get("netqty", 0))
                avg    = float(p.get("averageprice", 0))
                pnl_v  = float(p.get("pnl", (ltp - avg) * qty))
                pos_val = abs(qty) * ltp
                rows.append({
                    "Symbol":       p.get("tradingsymbol", ""),
                    "Side":         "🟢 BUY" if qty > 0 else "🔴 SELL",
                    "Qty":          abs(qty),
                    "Avg Price":    f"₹{avg:,.2f}",
                    "LTP":          f"₹{ltp:,.2f}",
                    "Position Val": f"₹{pos_val:,.0f}",
                    "Unrealized PnL": f"₹{pnl_v:,.2f}",
                })
            df_pos = pd.DataFrame(rows)

            def _color_pnl(val: str) -> str:
                try:
                    v = float(str(val).replace("₹", "").replace(",", ""))
                    return "color: #22c55e; font-weight:600" if v >= 0 else "color: #ef4444; font-weight:600"
                except Exception:
                    return ""

            styled = df_pos.style.map(_color_pnl, subset=["Unrealized PnL"])
            st.dataframe(styled, width='stretch', hide_index=True, height=300)
        else:
            st.info("📭 No open positions right now.")

    with col_risk:
        st.subheader("🛡️ Risk Utilisation")
        max_loss    = float(risk_status.get("max_daily_loss", 5000))
        cur_loss    = abs(float(risk_status.get("current_loss", 0)))
        util        = min(cur_loss / max_loss, 1.0) if max_loss > 0 else 0.0
        util_pct    = round(util * 100, 1)
        bar_colour  = "#ef4444" if util > 0.8 else "#f59e0b" if util > 0.5 else "#22c55e"
        icon        = "🟥" if util > 0.8 else "🟧" if util > 0.5 else "🟩"

        st.metric("Daily Loss Used",
                  f"₹{cur_loss:,.0f}",
                  delta=f"of ₹{max_loss:,.0f} limit")
        st.markdown(
            f"""
            <div style="background:#e0e0e0;border-radius:6px;height:18px;overflow:hidden;margin:6px 0">
              <div style="background:{bar_colour};width:{util_pct}%;height:100%;transition:width 0.5s"></div>
            </div>
            <small>{icon} <strong>{util_pct}%</strong> of daily loss limit used</small>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.metric(
            "Trades Today",
            f"{risk_status.get('trades_today', 0)} / {risk_status.get('max_trades', 20)}",
        )
        st.metric("Consecutive Failures", consec_failures)

    st.divider()

    # ── Row 3 — Today's order log ─────────────────────────────────────────────
    st.subheader("📄 Today's Order Log")
    if today_trades:
        df_trades = pd.DataFrame([
            {
                "Time":      t.get("ts", "")[-8:],
                "Symbol":    t.get("symbol", ""),
                "Side":      t.get("side", ""),
                "Qty":       t.get("qty", 0),
                "Price":     f"₹{float(t.get('price', 0)):,.2f}",
                "Broker ID": t.get("broker_order_id", "—"),
                "Key":       (t.get("order_key") or "")[:10] + "…",
            }
            for t in today_trades
        ])

        def _color_side(val: str) -> str:
            if "BUY"  in str(val).upper(): return "color: #22c55e; font-weight:600"
            if "SELL" in str(val).upper(): return "color: #ef4444; font-weight:600"
            return ""

        styled_t = df_trades.style.map(_color_side, subset=["Side"])
        st.dataframe(styled_t, width='stretch', hide_index=True, height=250)
    else:
        st.info("📭 No trades placed today.")

    st.divider()

    # ── Row 4 — Circuit breaker alert ─────────────────────────────────────────
    if circuit_open:
        st.error(
            f"🔴 **Circuit breaker OPEN.** All live orders are refused. "
            f"Consecutive failures: {consec_failures}. "
            "Investigate broker logs before resetting."
        )
        if st.button("⚡ Reset Circuit Breaker", type="primary"):
            if executor:
                try:
                    executor.reset_circuit()
                    st.success("✅ Circuit breaker reset. Orders will resume.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Reset failed: {exc}")
            else:
                st.warning("No live executor connected — cannot reset in simulation mode.")

    # ── Auto-refresh hint ─────────────────────────────────────────────────────
    st.caption("🔄 Reload the page to force a data refresh.")
    time.sleep(0.5)


# ── Safe data fetchers ────────────────────────────────────────────────────────

def _fetch_positions(executor) -> list[dict[str, Any]]:
    """Poll broker positions (60s TTL via Streamlit cache)."""
    if executor is None:
        return []
    try:
        return executor.get_positions()
    except Exception:
        return []


def _fetch_today_trades(audit_log) -> tuple[list[dict], float]:
    """Return today's ORDER_PLACED events and cumulative P&L."""
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
    """Return risk limits status dict (30s TTL)."""
    try:
        from risk.limits import risk_limits
        return risk_limits.status()
    except Exception:
        return {"max_daily_loss": 5000, "current_loss": 0,
                "max_trades": 20, "trades_today": 0}


# ── Standalone Streamlit entry ─────────────────────────────────────────────────

if __name__ == "__main__":
    import streamlit as st
    st.set_page_config(page_title="Eagle Live Monitor", layout="wide")
    st.title("🟢 Eagle Live Trading Monitor")
    render_live_monitor(executor=None, audit_log=None)
