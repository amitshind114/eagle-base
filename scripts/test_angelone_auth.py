"""
Angel One auth + connection pool test.

Credentials are read from environment variables set in your CMD session:

    set ANGELONE_API_KEY=...
    set ANGELONE_CLIENT_ID=...
    set ANGELONE_PASSWORD=...
    set ANGELONE_TOTP_SECRET=...

Run:
    python scripts/test_angelone_auth.py

Never hardcode credentials here. This file is safe to commit.
"""

from __future__ import annotations

import os
import sys

SEP = "-" * 60


def check_env() -> bool:
    required = [
        "ANGELONE_API_KEY",
        "ANGELONE_CLIENT_ID",
        "ANGELONE_PASSWORD",
        "ANGELONE_TOTP_SECRET",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print("[FAIL] Missing env vars:")
        for k in missing:
            print(f"       set {k}=your_value_here")
        return False
    print("[OK]  All 4 env vars present")
    return True


def test_login() -> "AngelOneBroker | None":
    print(SEP)
    print("STEP 1 — Angel One Login")
    print(SEP)
    try:
        from brokers.adapters.angelone import AngelOneBroker
        broker = AngelOneBroker()
        success = broker.login()
        if success:
            print(f"[OK]  Login successful")
            print(f"      client_id  : {os.getenv('ANGELONE_CLIENT_ID')}")
            print(f"      connected  : {broker.is_connected}")
            print(f"      auth_token : {broker._auth_token[:16]}...")
            return broker
        else:
            print("[FAIL] Login returned False — check credentials or TOTP secret")
            return None
    except ImportError as e:
        print(f"[FAIL] Import error: {e}")
        print("       Run: pip install smartapi-python pyotp")
        return None
    except Exception as e:
        print(f"[FAIL] Login error: {e}")
        return None


def test_profile(broker) -> bool:
    print(SEP)
    print("STEP 2 — Profile Fetch")
    print(SEP)
    try:
        profile = broker.get_profile()
        print(f"[OK]  Profile fetched")
        print(f"      name       : {profile.name}")
        print(f"      client_id  : {profile.client_id}")
        print(f"      email      : {profile.email}")
        print(f"      exchanges  : {profile.exchanges}")
        print(f"      products   : {profile.products}")
        return True
    except Exception as e:
        print(f"[FAIL] Profile fetch error: {e}")
        return False


def test_funds(broker) -> bool:
    print(SEP)
    print("STEP 3 — Funds / RMS Limit")
    print(SEP)
    try:
        funds = broker.get_funds()
        if funds:
            net = funds.get("net", funds.get("availablecash", "N/A"))
            print(f"[OK]  Funds fetched")
            print(f"      available  : {net}")
            return True
        else:
            print("[WARN] Funds returned empty dict")
            return True
    except Exception as e:
        print(f"[FAIL] Funds fetch error: {e}")
        return False


def test_positions(broker) -> bool:
    print(SEP)
    print("STEP 4 — Positions")
    print(SEP)
    try:
        positions = broker.get_positions()
        print(f"[OK]  Positions fetched: {len(positions)} open position(s)")
        for p in positions:
            print(f"      {p.symbol:20s} qty={p.quantity:>6}  ltp={p.ltp:.2f}  pnl={p.pnl:.2f}")
        if not positions:
            print("      (no open positions — expected for a fresh session)")
        return True
    except Exception as e:
        print(f"[FAIL] Positions error: {e}")
        return False


def test_orders(broker) -> bool:
    print(SEP)
    print("STEP 5 — Order Book")
    print(SEP)
    try:
        orders = broker.get_orders()
        print(f"[OK]  Order book fetched: {len(orders)} order(s)")
        for o in (orders[:3] if orders else []):
            print(
                f"      {o.get('tradingsymbol','?'):20s} "
                f"{o.get('transactiontype','?'):4s} "
                f"qty={o.get('quantity','?'):>5}  "
                f"status={o.get('status','?')}"
            )
        return True
    except Exception as e:
        print(f"[FAIL] Order book error: {e}")
        return False


def test_logout(broker) -> None:
    print(SEP)
    print("STEP 6 — Logout")
    print(SEP)
    try:
        broker.logout()
        print(f"[OK]  Logged out. connected={broker.is_connected}")
    except Exception as e:
        print(f"[WARN] Logout error (non-critical): {e}")


def main():
    print()
    print("=" * 60)
    print(" EAGLE — Angel One Connection Test")
    print("=" * 60)
    print()

    if not check_env():
        sys.exit(1)

    broker = test_login()
    if broker is None:
        print()
        print("[ABORT] Cannot proceed without a valid session.")
        sys.exit(1)

    results = []
    results.append(("Profile",   test_profile(broker)))
    results.append(("Funds",     test_funds(broker)))
    results.append(("Positions", test_positions(broker)))
    results.append(("Orders",    test_orders(broker)))
    test_logout(broker)

    print()
    print("=" * 60)
    print(" SUMMARY")
    print("=" * 60)
    passed = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        mark   = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if ok:
            passed += 1

    print()
    print(f"  {passed}/{len(results)} checks passed")
    if passed == len(results):
        print("  Angel One connection is HEALTHY.")
        print("  Ready for paper trading.")
    else:
        print("  Fix the failures above before proceeding.")
    print()


if __name__ == "__main__":
    main()
