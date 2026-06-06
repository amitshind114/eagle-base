"""Live order executor via Angel One SmartAPI — Phase 8 Live Safety.

⚠️  This module places REAL orders with REAL money.
Set EAGLE_LIVE_ENABLED=true in .env ONLY after paper trading is fully validated.

Safety chain (all must pass before any order is submitted):
    1. EAGLE_LIVE_ENABLED env var     — hard off-switch via environment
    2. Credential validation          — all 4 vars checked at connect(), not at order time
    3. Token map validation           — instrument master loaded at connect()
    4. Idempotency key check          — duplicate orders blocked in-memory + SQLite
    5. Circuit breaker                — 3 consecutive failures → all orders refused
    6. Risk gate                      — deterministic pre-trade check
    7. Risk limits                    — daily loss cap / trade count
    8. Audit record                   — every decision logged regardless of outcome
    9. reconcile()                    — run at session start + every 30 min

Angel One SmartAPI credentials (all required):
    ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET

Live toggle:
    EAGLE_LIVE_ENABLED=false   # default — safe
    EAGLE_LIVE_ENABLED=true    # set ONLY after paper validation
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from core.audit import audit
from core.base import BaseExecutor
from core.logger import logger
from risk.gate import compute_allowed_actions
from risk.limits import RiskLimitBreached, risk_limits

# ── Live toggle — read from env, never hardcoded ───────────────────────────
LIVE_ENABLED: bool = os.environ.get("EAGLE_LIVE_ENABLED", "false").lower() == "true"

# Required Angel One env vars — validated at connect(), not at order time
_REQUIRED_VARS = ["ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET"]

# SQLite path for idempotency key persistence
_DB_PATH = Path(os.environ.get("EAGLE_DATA_DIR", "eagle_base/data")) / "live_orders.db"

# Circuit breaker threshold
_CIRCUIT_BREAKER_THRESHOLD = 3


class DuplicateOrderError(RuntimeError):
    """Raised when an idempotency key collision is detected.

    Means the exact same order (symbol + side + qty + signal_timestamp)
    has already been placed in this session or within the last 24h.
    This is NOT an error — it is the correct safe behaviour on retry.
    """


class CircuitOpenError(RuntimeError):
    """Raised when circuit breaker is open due to repeated order failures."""


class LiveExecutor(BaseExecutor):
    """Live order executor via Angel One SmartAPI.

    Pre-trade safety checks run even when the Angel One call is stubbed—
    so the full gate + audit chain is testable without real credentials.
    """

    def __init__(self) -> None:
        if not LIVE_ENABLED:
            logger.warning("LiveExecutor: EAGLE_LIVE_ENABLED=false — live trading disabled")
        self._client                = None   # Angel One SmartConnect client
        self._placed_orders: set[str] = set()  # in-memory idempotency keys
        self._consecutive_failures: int = 0
        self._circuit_open: bool        = False
        self._db_conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # -------------------------------------------------------------------------
    # Database init (idempotency persistence)
    # -------------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create placed_orders table and load last 24h of keys into memory."""
        try:
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(_DB_PATH))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS placed_orders (
                    key        TEXT PRIMARY KEY,
                    broker_id  TEXT NOT NULL DEFAULT '',
                    timestamp  TEXT NOT NULL
                )
            """)
            conn.commit()
            # Load last 24h of keys into memory to guard against replay on restart
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            rows = conn.execute(
                "SELECT key FROM placed_orders WHERE timestamp > ?", (cutoff,)
            ).fetchall()
            self._placed_orders = {row[0] for row in rows}
            self._db_conn = conn
            logger.info(
                f"[live] Idempotency store ready: {len(self._placed_orders)} "
                f"keys loaded from last 24h."
            )
        except Exception as exc:
            logger.error(f"[live] DB init failed: {exc}. Idempotency will be in-memory only.")
            self._db_conn = None

    def _persist_order_key(self, key: str, broker_id: str) -> None:
        """Write an idempotency key + broker_id to SQLite."""
        if not self._db_conn:
            return
        try:
            self._db_conn.execute(
                "INSERT OR IGNORE INTO placed_orders(key, broker_id, timestamp) VALUES(?,?,?)",
                (key, broker_id, datetime.now(timezone.utc).isoformat()),
            )
            self._db_conn.commit()
        except Exception as exc:
            logger.warning(f"[live] Failed to persist order key {key}: {exc}")

    def _expire_old_keys(self) -> None:
        """Remove placed_orders rows older than 24h."""
        if not self._db_conn:
            return
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            self._db_conn.execute(
                "DELETE FROM placed_orders WHERE timestamp < ?", (cutoff,)
            )
            self._db_conn.commit()
        except Exception as exc:
            logger.warning(f"[live] Key expiry failed: {exc}")

    # -------------------------------------------------------------------------
    # Connection
    # -------------------------------------------------------------------------

    def connect(self) -> None:
        """Authenticate with Angel One. Call once at session start.

        Validates ALL required env vars before attempting network calls.
        Raises ValueError listing every missing var (not a cryptic KeyError).
        Refreshes instrument token map — raises RuntimeError if unavailable.
        """
        if not LIVE_ENABLED:
            logger.info("LiveExecutor.connect(): skipped (EAGLE_LIVE_ENABLED=false)")
            return

        # ─ P0: Validate all credentials upfront ──────────────────────────────
        missing = [v for v in _REQUIRED_VARS if not os.environ.get(v, "").strip()]
        if missing:
            raise ValueError(
                f"Missing required credentials: {missing}. "
                f"Add them to your .env file before starting live trading."
            )

        # ─ P0: Validate token map before session ────────────────────────────
        try:
            from instruments.token_map import refresh_if_stale, token_count
            refresh_if_stale()
            if token_count() == 0:
                raise RuntimeError(
                    "Instrument token map unavailable — cannot place orders safely."
                )
            logger.info(f"[live] Token map ready: {token_count()} instruments loaded.")
        except ImportError as exc:
            raise RuntimeError(
                "instruments/token_map.py not found. "
                "Build it before enabling live trading."
            ) from exc

        # ─ Establish Angel One session ─────────────────────────────────────
        try:
            from SmartApi import SmartConnect
            import pyotp
            key  = os.environ["ANGEL_API_KEY"]
            cid  = os.environ["ANGEL_CLIENT_ID"]
            pwd  = os.environ["ANGEL_PASSWORD"]
            totp = pyotp.TOTP(os.environ["ANGEL_TOTP_SECRET"]).now()
            self._client = SmartConnect(api_key=key)
            self._client.generateSession(cid, pwd, totp)
            logger.info("[live] Angel One session established.")
            audit.record("SESSION_START", "SYSTEM", session="live")
        except Exception as exc:
            logger.error(f"[live] connect() failed: {exc}")
            raise

        # Expire stale idempotency keys on session start
        self._expire_old_keys()
        # Run reconciliation at session start
        self.reconcile()

    # -------------------------------------------------------------------------
    # Place order
    # -------------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float = 0.0,
        order_type: str = "MARKET",
        tag: str = "",
        capital: float | None = None,
        prices: dict | None = None,
        portfolio: dict | None = None,
        vix: float | None = None,
        signal_timestamp: str = "",   # ISO timestamp of the signal that triggered this order
    ) -> dict[str, Any]:
        """Place a live order via Angel One after all safety checks pass.

        Returns the broker response dict on success.

        Raises:
            RuntimeError        : LIVE_ENABLED=False or client not connected.
            CircuitOpenError    : Circuit breaker open — manual reset required.
            DuplicateOrderError : Same order already placed (idempotency block).
            ValueError          : Risk gate blocked the trade.
            RiskLimitBreached   : Daily limits exceeded.
        """
        sym = symbol.upper().replace(".NS", "")

        if not LIVE_ENABLED:
            raise RuntimeError(
                "Live trading is disabled. Set EAGLE_LIVE_ENABLED=true in .env "
                "ONLY after full paper trading validation."
            )

        # ─ P1: Circuit breaker ─────────────────────────────────────────────────
        if self._circuit_open:
            logger.critical(
                f"[live] Circuit breaker is OPEN. All orders refused. "
                f"Consecutive failures: {self._consecutive_failures}. "
                f"Call reset_circuit() after investigating."
            )
            audit.record("CIRCUIT_OPEN", sym, session="live",
                         failures=self._consecutive_failures)
            raise CircuitOpenError(
                f"Circuit breaker open after {self._consecutive_failures} consecutive "
                f"failures. Call LiveExecutor.reset_circuit() to resume."
            )

        # ─ P0: Idempotency key check ──────────────────────────────────────────
        ts  = signal_timestamp or datetime.now(timezone.utc).isoformat()
        order_key = hashlib.md5(
            f"{sym}:{side.upper()}:{qty}:{ts}".encode()
        ).hexdigest()

        if order_key in self._placed_orders:
            logger.warning(
                f"[live] DUPLICATE ORDER BLOCKED: {side} {qty} {sym} "
                f"(key={order_key[:8]}...). Same signal already placed."
            )
            audit.record("DUPLICATE_BLOCKED", sym, session="live",
                         order_key=order_key, side=side, qty=qty)
            raise DuplicateOrderError(
                f"Order already placed for signal [{sym} {side} x{qty} @ {ts}]. "
                f"Idempotency key: {order_key}"
            )

        # ─ Risk gate ──────────────────────────────────────────────────────────────
        allowed = compute_allowed_actions(
            symbol=sym, capital=capital, prices=prices,
            portfolio=portfolio, vix=vix,
        )
        if not allowed:
            audit.record("GATE_BLOCK", sym, session="live",
                         reason=allowed.block_reason, flags=allowed.flags)
            raise ValueError(f"Gate blocked [{sym}]: {allowed.block_reason}")

        # ─ Daily limits ───────────────────────────────────────────────────────────
        safe_qty = min(qty, allowed.max_qty) if allowed.max_qty > 0 else qty
        try:
            risk_limits.check(sym, side, safe_qty, price or 0.0)
        except RiskLimitBreached as exc:
            audit.record("LIMIT_BREACH", sym, session="live", reason=str(exc))
            raise

        # ─ Submit to Angel One ──────────────────────────────────────────────────
        if not self._client:
            raise RuntimeError("Call connect() before place_order()")

        order_params = {
            "variety":         "NORMAL",
            "tradingsymbol":   sym,
            "symboltoken":     self._resolve_token(sym),
            "transactiontype": side.upper(),
            "exchange":        "NSE",
            "ordertype":       order_type.upper(),
            "producttype":     "INTRADAY",
            "duration":        "DAY",
            "price":           str(price) if order_type == "LIMIT" else "0",
            "quantity":        str(safe_qty),
            "squareoff":       "0",
            "stoploss":        "0",
        }

        try:
            response  = self._client.placeOrder(order_params)
            broker_id = response.get("data", {}).get("orderid", "")

            # Register idempotency key AFTER successful broker response
            self._placed_orders.add(order_key)
            self._persist_order_key(order_key, broker_id)

            # Reset circuit breaker on success
            self._consecutive_failures = 0

            risk_limits.record_trade(sym, side, safe_qty, price or 0.0)
            audit.record(
                "ORDER_PLACED", sym, session="live",
                side=side, qty=safe_qty, price=price,
                broker_order_id=broker_id, tag=tag,
                order_key=order_key,
            )
            logger.info(
                f"[live] Order placed: {side} {safe_qty} {sym} "
                f"broker_id={broker_id} key={order_key[:8]}..."
            )
            return response

        except (DuplicateOrderError, CircuitOpenError, ValueError, RiskLimitBreached):
            raise  # re-raise safety exceptions without counting as broker failure

        except Exception as exc:
            self._consecutive_failures += 1
            audit.record("ORDER_ERROR", sym, session="live", error=str(exc),
                         consecutive_failures=self._consecutive_failures)
            logger.error(
                f"[live] Order failed [{sym}]: {exc} "
                f"(consecutive failures: {self._consecutive_failures})"
            )
            # Open circuit after threshold
            if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                self._circuit_open = True
                logger.critical(
                    f"[live] CIRCUIT BREAKER OPEN after "
                    f"{self._consecutive_failures} consecutive failures. "
                    f"All further orders are refused until reset_circuit() is called."
                )
                audit.record("CIRCUIT_OPENED", sym, session="live",
                             failures=self._consecutive_failures)
            raise

    # -------------------------------------------------------------------------
    # Reconciliation
    # -------------------------------------------------------------------------

    def reconcile(self, position_book=None) -> dict[str, Any]:
        """Compare broker positions vs internal position_book.

        Run at session start and every 30 min to detect state divergence.

        Three cases handled:
          (1) Broker HAS position, internal does NOT  → add with RECONCILE tag, log CRITICAL
          (2) Internal HAS position, broker does NOT  → remove from book, log CRITICAL
          (3) Quantities DIFFER                        → update internal to match broker, log WARNING

        Args:
            position_book: optional PositionBook instance. If None, loads from
                           paper.position_book if available.

        Returns:
            dict with keys: added, removed, updated (lists of symbol strings)
        """
        if not LIVE_ENABLED or not self._client:
            logger.debug("[live] reconcile(): skipped (live disabled or not connected)")
            return {"added": [], "removed": [], "updated": []}

        result: dict[str, list[str]] = {"added": [], "removed": [], "updated": []}

        # Fetch broker positions
        try:
            resp             = self._client.position()
            broker_positions = resp.get("data") or []
        except Exception as exc:
            logger.error(f"[live] reconcile(): broker position fetch failed: {exc}")
            return result

        # Build broker map: {symbol: net_qty}
        broker_map: dict[str, int] = {}
        for pos in broker_positions:
            sym = str(pos.get("tradingsymbol", "")).strip().upper()
            qty = int(pos.get("netqty", 0))
            if sym and qty != 0:
                broker_map[sym] = qty

        # Get internal positions
        internal_map: dict[str, int] = {}
        if position_book is not None:
            for pos in position_book.all_open():
                internal_map[pos.symbol.upper()] = pos.quantity

        all_symbols = set(broker_map) | set(internal_map)

        for sym in all_symbols:
            broker_qty   = broker_map.get(sym)
            internal_qty = internal_map.get(sym)

            if broker_qty is not None and internal_qty is None:
                # Case 1: Broker has it, we don't
                logger.critical(
                    f"[live] RECONCILE: Broker has {broker_qty} {sym} "
                    f"but internal state has NONE. Adding with RECONCILE tag."
                )
                audit.record("RECONCILE_ADD", sym, session="live",
                             broker_qty=broker_qty, internal_qty=0)
                if position_book is not None:
                    from paper.models import Position
                    position_book.positions[sym] = Position(
                        symbol=sym, quantity=broker_qty,
                        avg_cost=0.0, current_price=0.0
                    )
                result["added"].append(sym)

            elif internal_qty is not None and broker_qty is None:
                # Case 2: We have it, broker doesn't
                logger.critical(
                    f"[live] RECONCILE: Internal has {internal_qty} {sym} "
                    f"but broker has NONE. Removing from internal state."
                )
                audit.record("RECONCILE_REMOVE", sym, session="live",
                             broker_qty=0, internal_qty=internal_qty)
                if position_book is not None:
                    position_book.positions.pop(sym, None)
                result["removed"].append(sym)

            elif broker_qty != internal_qty:
                # Case 3: Quantities differ
                logger.warning(
                    f"[live] RECONCILE: {sym} qty mismatch — "
                    f"broker={broker_qty} internal={internal_qty}. "
                    f"Updating internal to match broker."
                )
                audit.record("RECONCILE_UPDATE", sym, session="live",
                             broker_qty=broker_qty, internal_qty=internal_qty)
                if position_book is not None and sym in position_book.positions:
                    pos = position_book.positions[sym]
                    position_book.positions[sym] = pos.model_copy(
                        update={"quantity": broker_qty}
                    )
                result["updated"].append(sym)

        if any(result.values()):
            logger.warning(f"[live] Reconciliation complete: {result}")
        else:
            logger.info("[live] Reconciliation complete: no divergence detected.")

        return result

    # -------------------------------------------------------------------------
    # Circuit breaker reset
    # -------------------------------------------------------------------------

    def reset_circuit(self) -> None:
        """Manually reset circuit breaker after investigating failures."""
        self._circuit_open       = False
        self._consecutive_failures = 0
        logger.info("[live] Circuit breaker reset. Orders will resume.")
        audit.record("CIRCUIT_RESET", "SYSTEM", session="live")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        """Cancel a live order by broker order ID."""
        if not LIVE_ENABLED or not self._client:
            raise RuntimeError("Live trading not active")
        try:
            self._client.cancelOrder(order_id, variety)
            audit.record("ORDER_CANCELLED", "SYSTEM", session="live", order_id=order_id)
            logger.info(f"[live] Order {order_id} cancelled")
            return True
        except Exception as exc:
            logger.error(f"[live] Cancel failed [{order_id}]: {exc}")
            return False

    def get_positions(self) -> list[dict[str, Any]]:
        """Fetch current open positions from Angel One."""
        if not LIVE_ENABLED or not self._client:
            return []
        try:
            resp = self._client.position()
            return resp.get("data") or []
        except Exception as exc:
            logger.error(f"[live] get_positions failed: {exc}")
            return []

    def _resolve_token(self, symbol: str) -> str:
        """Resolve symbol to Angel One instrument token.

        Raises instead of returning empty string — empty token causes orders
        to route to wrong instrument or fail with cryptic broker errors.

        Raises:
            RuntimeError: instruments/token_map.py not found (ImportError).
            ValueError  : symbol has no token in instrument master (KeyError).
        """
        try:
            from instruments.token_map import get_token
            return get_token(symbol)
        except ImportError as exc:
            raise RuntimeError(
                "instruments/token_map.py not found. "
                "Build the token map before enabling live trading."
            ) from exc
        except (ValueError, RuntimeError):
            raise  # re-raise with original message from get_token()
        except Exception as exc:
            raise ValueError(
                f"Unexpected error resolving token for '{symbol}': {exc}"
            ) from exc
