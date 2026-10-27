# Transaction Ledger API

A ledger API for accounts and transactions, built with Python, FastAPI, and PostgreSQL. The spec is in `docs/transaction-ledger-api.md`.

## Project layout

The code is split into three layers, one folder each. Each folder holds one file per resource (for example, `accounts` and `transactions`).

| Folder | Responsibility | Must not |
|---|---|---|
| `routes/` | Parse and validate HTTP input, call a service, map business errors to HTTP status codes and the standard error body | Contain SQL or business rules |
| `services/` | Own the business rules and the database transaction (start, commit, rollback). Turn database errors into business errors | Contain SQL or HTTP code |
| `repositories/` | Run all SQL: reads, writes, and locking reads. SQL on a table lives in that table's file (for example, the guarded balance update is in `accounts.py`) | Know about HTTP or business rules |

The database enforces the integrity rules as a last line of defence: unique, check, and foreign key constraints in the schema.

Why this split: each layer can be tested on its own. The transaction boundary lives in `services/`; the overdraw check lives in one SQL statement in `repositories/accounts.py`, so the row lock covers the check and the write together.

## What is implemented

| Endpoint | Behaviour |
|---|---|
| `POST /accounts` | Creates an account with balance 0. Returns 201 |
| `POST /accounts/{id}/transactions` | Adds a `credit` or `debit` and returns 201 with the transaction and the new balance. 404 unknown account, 409 duplicate `reference_id` on the account, 422 insufficient balance, balance limit exceeded, or invalid input |
| `GET /accounts/{id}/transactions` | Lists transactions latest-first. Query: `type` (`credit` or `debit`), `page` (default 1, at most 1,000,000), `limit` (default 20, at most 100). Returns `{data, page, limit, total_records, total_pages}`. A `limit` above 100 is clamped and sets an `X-Pagination-Warning` header. 404 unknown account, 422 invalid `type`, `page` or `limit` |
| `POST /transfers` | Moves money between two accounts as a debit on the source and a credit on the destination, in one database transaction. Returns 201 with both legs. 404 unknown account, 409 duplicate `reference_id` on either account, 422 insufficient balance, same account or invalid input |
| `GET /accounts/{id}/balance` | Returns `{account_id, balance}`. 404 unknown account, 422 malformed account ID |

Every error uses one body, `{"error": {"code", "message"}}`; the codes are listed in `ASSUMPTIONS.md`.

Every endpoint, with request and response examples, validation rules and error codes, is documented in `API.md`; the live contract is at `/docs`.

## Stress test

`scripts/stress.py` drives a running server over HTTP (every endpoint, concurrent debits and duplicates, a mixed load) and checks that each balance equals its credits minus its debits. Run it against a server on the test database only; the header of the script has the exact commands and the cleanup query.

## Frontend (Tally demo app)

`frontend/` is a small banking app on top of the API: a demo sign-in, your accounts with a total, and per account a balance, add money / withdraw / send, and a ledger-style transaction feed with a running balance, a type filter and "show older" paging. It is plain HTML, CSS and ES modules: no build step, no dependencies, no network calls except to the API. Amounts are handled as exact integers (paise) and shown in rupees; the currency symbol is display-only, since the API has no currency.

Use the test database, in two terminals from the project root:

```
set -a && . config/.env && set +a
DB_NAME="$TEST_DB_NAME" .venv/bin/uvicorn app.main:app --port 8000
python3 -m http.server 5500 --directory frontend
```

Then open `http://localhost:5500`. The API allows browser calls only from that origin (`app/main.py`).

- **The sign-in is a demo.** There are no passwords and nothing is secured; the name is kept in the browser's `localStorage`. The API has no authentication.
- **The API has no "list accounts" call**, so the app remembers the accounts you opened in this browser (also `localStorage`). Clearing site data loses that list, not the accounts. "Add sample accounts" creates two accounts with some history through the API; they are stored as `test-Everyday` and `test-Savings` (shown without the prefix), so a pytest run on the test database deletes them. Do not run the tests while you are using the app.
- **To try a transfer with only one account**, choose Send and click "Add test recipient". It creates a throwaway account (stored as `test-Recipient N`) and selects it.
- **Each attempt carries one `reference_id`.** A retry of the same attempt is a duplicate (409) and the app says it was already processed; after a success the next attempt gets a new one.
- `frontend/tester/` is the earlier raw API tester (every endpoint, status and body as returned): `http://localhost:5500/tester/`.

## Assumptions and decisions

Status codes, input rules and the money format are in `ASSUMPTIONS.md`.

## Setup and run

Prerequisites: Python 3 and a running PostgreSQL server with two empty databases, one for the app and one for tests.

1. Copy `config/.env.example` to `config/.env` and fill in your values. `DB_NAME` is the app database and `TEST_DB_NAME` is the test database. If TCP login is blocked by ident authentication, set `DB_HOST` to the Unix socket directory (for example `/var/run/postgresql`).
2. Install dependencies:

   ```
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```

3. Load the settings into your shell, then create the tables in each database (the file is safe to re-run):

   ```
   set -a && . config/.env && set +a
   psql -h "$DB_HOST" -d "$DB_NAME" -f db/schema.sql
   psql -h "$DB_HOST" -d "$TEST_DB_NAME" -f db/schema.sql
   ```

4. Run the tests. They always use `TEST_DB_NAME`, whatever `DB_NAME` is set to:

   ```
   .venv/bin/python -m pytest tests -q
   ```

5. Run the API (interactive docs at `/docs`):

   ```
   .venv/bin/uvicorn app.main:app
   ```

Each command was run on the author's machine. The schema was applied to both the app and the test database.
