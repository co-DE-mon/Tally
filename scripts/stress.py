"""Stress test for the Transaction Ledger API. Standard library only.

It drives a running server over HTTP: every endpoint once, then concurrent debits,
concurrent duplicates and a mixed load, and finally checks that every balance equals
its credits minus its debits and that no row is repeated.

Run it against a server that uses the TEST database, never the main one:

    set -a && . config/.env && set +a
    DB_NAME="$TEST_DB_NAME" .venv/bin/uvicorn app.main:app --port 8765 --workers 2 &
    .venv/bin/python -I scripts/stress.py http://localhost:8765 32

Arguments: BASE_URL and the number of concurrent clients (keep it below the
database's max_connections). It creates accounts named test-stress-*; remove them with:

    psql -h "$DB_HOST" -d "$TEST_DB_NAME" -c "DELETE FROM transactions WHERE account_id IN
      (SELECT id FROM accounts WHERE name LIKE 'test-stress-%'); DELETE FROM accounts
      WHERE name LIKE 'test-stress-%';"

Exit status is 0 when every check passes. If the database is far away (high latency) or the
server is starved of connections, the scenarios that pile requests onto one account can
legitimately get 503 and fail their count checks; the balance and history checks are the
ones that must still hold.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

BASE = sys.argv[1]
CLIENTS = int(sys.argv[2])
failures = []


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"null"), dict(resp.headers)
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw), dict(err.headers)
        except ValueError:
            return err.code, raw.decode(errors="replace"), dict(err.headers)


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name} {detail}")
    if not ok:
        failures.append(name)


def new_account(tag):
    status, body, _ = call("POST", "/accounts", {"name": f"test-stress-{tag}"})
    assert status == 201, (status, body)
    return body["id"]


def tx(account, type_, amount, ref):
    return call("POST", f"/accounts/{account}/transactions",
                {"type": type_, "amount": amount, "reference_id": ref})


def timed(fn, items):
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CLIENTS) as pool:
        results = list(pool.map(fn, items))
    return results, time.perf_counter() - start


# 1. Every endpoint, success and failure, one pass.
print("1. pipeline pass")
a = new_account("pipeline")
check("credit 100", tx(a, "credit", "100.00", "p1")[0] == 201)
check("credit 50", tx(a, "credit", "50.00", "p2")[0] == 201)
check("debit 30", tx(a, "debit", "30.00", "p3")[0] == 201)
check("debit 20", tx(a, "debit", "20.00", "p4")[0] == 201)
status, body, _ = call("GET", f"/accounts/{a}/balance")
check("balance is 100.00", status == 200 and body["balance"] == "100.00", str(body))
check("overdraw refused 422", tx(a, "debit", "100.01", "p5")[:2][0] == 422)
check("duplicate refused 409", tx(a, "credit", "1.00", "p1")[0] == 409)
status, body, _ = call("GET", f"/accounts/{a}/transactions?limit=3&page=1")
check("history page 1", status == 200 and [r["reference_id"] for r in body["data"]] == ["p4", "p3", "p2"]
      and body["total_records"] == 4 and body["total_pages"] == 2, str(body)[:100])
status, body, _ = call("GET", f"/accounts/{a}/transactions?type=debit")
check("history type=debit", status == 200 and body["total_records"] == 2)
status, body, headers = call("GET", f"/accounts/{a}/transactions?limit=999")
check("limit clamp + header", status == 200 and body["limit"] == 100 and "x-pagination-warning" in {k.lower() for k in headers})
for method in ("PUT", "PATCH", "DELETE"):
    check(f"{method} refused", call(method, f"/accounts/{a}/transactions")[0] in (404, 405))
status, body, _ = call("GET", "/accounts/not-a-uuid/balance")
check("malformed id 422 + error shape", status == 422 and list(body) == ["error"])

# 2. Concurrent debits on one account: balance 1000, 60 debits of 30 -> exactly 33 succeed.
print(f"2. concurrent debits ({CLIENTS} clients)")
a = new_account("debits")
tx(a, "credit", "1000.00", "seed")
results, secs = timed(lambda n: tx(a, "debit", "30.00", f"d-{n}")[0], range(60))
counts = Counter(results)
balance = call("GET", f"/accounts/{a}/balance")[1]["balance"]
check("33 succeed, 27 refused", counts == {201: 33, 422: 27}, f"{dict(counts)} in {secs:.2f}s")
check("final balance 10.00", balance == "10.00", balance)

# 3. Same reference_id from many clients at once -> exactly one row.
print("3. concurrent duplicates")
a = new_account("dupes")
results, secs = timed(lambda n: tx(a, "credit", "5.00", "same")[0], range(60))
counts = Counter(results)
body = call("GET", f"/accounts/{a}/transactions")[1]
check("one 201, rest 409", counts == {201: 1, 409: 59}, f"{dict(counts)} in {secs:.2f}s")
check("one row, balance 5.00", body["total_records"] == 1
      and call("GET", f"/accounts/{a}/balance")[1]["balance"] == "5.00")

# 4. Many accounts, random mixed load, plus history reads racing the writes.
print("4. mixed load across accounts")
accounts = [new_account(f"mixed-{i}") for i in range(8)]
for acc in accounts:
    tx(acc, "credit", "500.00", "seed")


def mixed(n):
    acc = accounts[n % len(accounts)]
    kind = n % 4
    if kind == 0:
        return "credit", tx(acc, "credit", "7.25", f"m-{n}")[0]
    if kind == 1:
        return "debit", tx(acc, "debit", "3.10", f"m-{n}")[0]
    if kind == 2:
        status, body, _ = call("GET", f"/accounts/{acc}/transactions?limit=50")
        ok = status == 200 and body["total_records"] >= len(body["data"]) if body["page"] == 1 else True
        return "history", 200 if ok else 599
    return "balance", call("GET", f"/accounts/{acc}/balance")[0]


results, secs = timed(mixed, range(800))
counts = Counter(results)
bad = {k: v for k, v in counts.items() if k[1] not in (200, 201)}
check("no unexpected statuses", not bad, f"{dict(counts)} in {secs:.2f}s ({800 / secs:.0f} req/s)")

# 5. Balance equals credits minus debits for every stress account.
print("5. invariant (read through the API)")
all_accounts = accounts + [a]
for acc in accounts:
    rows, page = [], 1
    while True:
        _, body, _ = call("GET", f"/accounts/{acc}/transactions?limit=100&page={page}")
        rows += body["data"]
        if page >= body["total_pages"]:
            break
        page += 1
    expected = sum(Decimal(r["amount"]) * (1 if r["type"] == "credit" else -1) for r in rows)
    balance = Decimal(call("GET", f"/accounts/{acc}/balance")[1]["balance"])
    check(f"{acc[:8]} balance == sum of history", balance == expected and balance >= 0,
          f"{balance} vs {expected}")
    ids = [r["id"] for r in rows]
    check(f"{acc[:8]} no repeated rows", len(ids) == len(set(ids)))

# 6. Transfers: opposite directions at once (no deadlock), and no overdraw.
print(f"6. concurrent transfers ({CLIENTS} clients)")


def transfer(source, destination, amount, ref):
    return call("POST", "/transfers", {"source_account_id": source, "destination_account_id": destination,
                                       "amount": amount, "reference_id": ref})[0]


x, y = new_account("transfer-x"), new_account("transfer-y")
tx(x, "credit", "1000.00", "seed")
tx(y, "credit", "1000.00", "seed")
results, secs = timed(lambda n: transfer(x, y, "7.50", f"t-{n}") if n % 2 == 0
                      else transfer(y, x, "7.50", f"t-{n}"), range(80))
check("80 opposite transfers all succeed", Counter(results) == {201: 80}, f"{dict(Counter(results))} in {secs:.2f}s")
bx = call("GET", f"/accounts/{x}/balance")[1]["balance"]
by = call("GET", f"/accounts/{y}/balance")[1]["balance"]
check("forty each way cancel out", (bx, by) == ("1000.00", "1000.00"), f"{bx} {by}")

p, q = new_account("transfer-p"), new_account("transfer-q")
tx(p, "credit", "100.00", "seed")
results, secs = timed(lambda n: transfer(p, q, "30.00", f"o-{n}"), range(40))
check("100 pays for exactly three transfers of 30", Counter(results) == {201: 3, 422: 37}, f"{dict(Counter(results))}")
check("balances 10.00 and 90.00", (call("GET", f"/accounts/{p}/balance")[1]["balance"],
                                   call("GET", f"/accounts/{q}/balance")[1]["balance"]) == ("10.00", "90.00"))
for acc in (x, y, p, q):
    _, body, _ = call("GET", f"/accounts/{acc}/transactions?limit=100")
    rows = body["data"]
    expected = sum(Decimal(r["amount"]) * (1 if r["type"] == "credit" else -1) for r in rows)
    balance = Decimal(call("GET", f"/accounts/{acc}/balance")[1]["balance"])
    check(f"{acc[:8]} balance == sum of history", balance == expected and balance >= 0, f"{balance} vs {expected}")

print()
print("FAILED:" if failures else "ALL CHECKS PASSED", failures or "")
sys.exit(1 if failures else 0)
