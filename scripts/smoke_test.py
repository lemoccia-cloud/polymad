#!/usr/bin/env python3.11
"""
polyMad Billing Smoke Test
==========================

Arranca FastAPI local, cria um JWT de teste, e chama cada endpoint
de billing com as Stripe keys reais (test mode).

Uso:
    bash scripts/smoke_test.sh           # lê .stripe_test_keys automaticamente
    python3.11 scripts/smoke_test.py     # usa env vars já exportadas

Keys necessárias (env vars ou .stripe_test_keys):
    STRIPE_SECRET_KEY          sk_test_...
    STRIPE_PRICE_PRO_MONTHLY   price_...
    STRIPE_PRICE_TRADER_MONTHLY price_...

Exit code: 0 se todos os testes passam, 1 se algum falha.
"""

import os
import sys
import time
import signal
import subprocess
import textwrap

# ── Ensure project root is in path ──────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import httpx

FASTAPI_PORT = 8099
BASE = f"http://127.0.0.1:{FASTAPI_PORT}"
PYTHON = sys.executable

# ── Safety check: refuse to run if stripe key looks live ────────────────────
_sk = os.environ.get("STRIPE_SECRET_KEY", "")
if _sk.startswith("sk_live_"):
    print("❌ ABORTED: STRIPE_SECRET_KEY is a LIVE key. Use sk_test_ for smoke tests.")
    sys.exit(1)

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

results: list[tuple[str, bool, str]] = []


def _ok(name: str, detail: str = "") -> None:
    results.append((name, True, detail))
    print(f"  {GREEN}✅ {name}{RESET}" + (f"  {YELLOW}{detail[:80]}{RESET}" if detail else ""))


def _fail(name: str, detail: str = "") -> None:
    results.append((name, False, detail))
    print(f"  {RED}❌ {name}{RESET}" + (f"\n     {detail[:200]}" if detail else ""))


def _skip(name: str, reason: str) -> None:
    results.append((name, True, f"SKIP: {reason}"))
    print(f"  {YELLOW}⏭  {name} — {reason}{RESET}")


# ── Mint a test JWT ───────────────────────────────────────────────────────────
def _mint_jwt(address: str = "email:smoke-test-user-000", plan: str = "free") -> str:
    from src.api.security.jwt_handler import create_access_token
    token, _ = create_access_token(address=address, plan=plan)
    return token


# ── Start / stop FastAPI ──────────────────────────────────────────────────────
def _start_fastapi() -> subprocess.Popen:
    env = {**os.environ, "FASTAPI_INTERNAL_URL": BASE}
    # JWT key — use dev key file or generate ephemeral
    if not env.get("JWT_SECRET_KEY"):
        key_file = os.path.join(ROOT, ".dev_jwt_key")
        if os.path.exists(key_file):
            env["JWT_SECRET_KEY"] = open(key_file).read().strip()
        else:
            import secrets
            env["JWT_SECRET_KEY"] = secrets.token_hex(32)

    proc = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "src.api.main:app",
         "--host", "127.0.0.1", "--port", str(FASTAPI_PORT), "--log-level", "error"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait up to 10s for health
    for _ in range(20):
        try:
            r = httpx.get(f"{BASE}/health", timeout=1)
            if r.status_code == 200:
                return proc
        except Exception:
            pass
        time.sleep(0.5)

    proc.kill()
    stderr = proc.stderr.read().decode() if proc.stderr else ""
    print(f"{RED}FastAPI failed to start:{RESET}\n{textwrap.indent(stderr[:600], '  ')}")
    sys.exit(1)


def _stop_fastapi(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


# ── Individual tests ─────────────────────────────────────────────────────────
def test_health() -> None:
    r = httpx.get(f"{BASE}/health", timeout=5)
    if r.status_code == 200 and r.json().get("status") == "ok":
        _ok("health")
    else:
        _fail("health", f"{r.status_code} {r.text[:100]}")


def test_checkout_no_auth() -> None:
    r = httpx.post(
        f"{BASE}/api/billing/checkout",
        params={"plan": "pro", "success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel"},
        timeout=5,
    )
    if r.status_code == 401:
        _ok("checkout — no auth → 401")
    else:
        _fail("checkout — no auth", f"expected 401, got {r.status_code}: {r.text[:100]}")


def test_checkout_invalid_plan(jwt: str) -> None:
    r = httpx.post(
        f"{BASE}/api/billing/checkout",
        params={"plan": "bogus", "success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel"},
        headers={"Authorization": f"Bearer {jwt}"},
        timeout=5,
    )
    if r.status_code == 422:
        _ok("checkout — invalid plan → 422")
    else:
        _fail("checkout — invalid plan", f"expected 422, got {r.status_code}: {r.text[:100]}")


def test_checkout_plan(jwt: str, plan: str) -> None:
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "")
    price_key = f"STRIPE_PRICE_{plan.upper()}_MONTHLY"
    price_id = os.environ.get(price_key, "")

    if not stripe_key or stripe_key in ("sk_test_stub", ""):
        _skip(f"checkout/{plan}", "STRIPE_SECRET_KEY not set (use .stripe_test_keys)")
        return
    if not price_id or price_id.startswith("price_stub"):
        _skip(f"checkout/{plan}", f"{price_key} not set")
        return

    try:
        r = httpx.post(
            f"{BASE}/api/billing/checkout",
            params={
                "plan": plan,
                "success_url": "https://polymad-production.up.railway.app/?plan_success=1",
                "cancel_url": "https://polymad-production.up.railway.app/Billing",
            },
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=15,
        )
        if r.status_code == 200:
            url = r.json().get("checkout_url", "")
            if url.startswith("https://checkout.stripe.com"):
                _ok(f"checkout/{plan}", f"URL: {url[:60]}…")
            else:
                _fail(f"checkout/{plan}", f"Unexpected URL: {url[:100]}")
        else:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            _fail(f"checkout/{plan}", f"HTTP {r.status_code}: {detail[:150]}")
    except httpx.TimeoutException:
        _fail(f"checkout/{plan}", "Timeout — Stripe API call took >15s")


def test_invoices(jwt: str) -> None:
    r = httpx.get(
        f"{BASE}/api/billing/invoices",
        headers={"Authorization": f"Bearer {jwt}"},
        timeout=10,
    )
    if r.status_code == 200 and isinstance(r.json(), list):
        _ok("invoices", f"{len(r.json())} invoice(s) returned")
    elif r.status_code == 503:
        _skip("invoices", "Stripe not configured — expected in stub mode")
    else:
        _fail("invoices", f"HTTP {r.status_code}: {r.text[:100]}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"\n{BOLD}polyMad Billing Smoke Test{RESET}")
    print(f"  FastAPI port : {FASTAPI_PORT}")
    print(f"  Stripe mode  : {'test' if os.environ.get('STRIPE_SECRET_KEY','').startswith('sk_test_') else 'stub / not set'}")
    print(f"  Pro price    : {os.environ.get('STRIPE_PRICE_PRO_MONTHLY', '(not set)')}")
    print(f"  Trader price : {os.environ.get('STRIPE_PRICE_TRADER_MONTHLY', '(not set)')}")
    print()

    print("Starting FastAPI…")
    proc = _start_fastapi()
    print(f"FastAPI up on :{FASTAPI_PORT}\n")

    jwt = _mint_jwt()

    try:
        test_health()
        test_checkout_no_auth()
        test_checkout_invalid_plan(jwt)
        test_checkout_plan(jwt, "pro")
        test_checkout_plan(jwt, "trader")
        test_invoices(jwt)
    finally:
        _stop_fastapi(proc)

    # ── Summary ───────────────────────────────────────────────────────────────
    passed  = sum(1 for _, ok, d in results if ok and not d.startswith("SKIP"))
    skipped = sum(1 for _, ok, d in results if ok and d.startswith("SKIP"))
    failed  = sum(1 for _, ok, _ in results if not ok)
    total   = len(results)

    print(f"\n{'─'*50}")
    if failed == 0:
        print(f"{GREEN}{BOLD}PASSED {passed}/{total - skipped}{RESET}" +
              (f"  ({YELLOW}{skipped} skipped — add .stripe_test_keys to test billing{RESET})" if skipped else ""))
    else:
        print(f"{RED}{BOLD}FAILED {failed}/{total - skipped}{RESET}")

    print()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
