# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Mercari is a **full-stack inventory and order management system** with deep integration to the Japanese Mercari marketplace. It's built as a Vue 3 frontend (Vite) with a Python FastAPI backend, featuring order synchronization, product listing automation, and local inventory management with support for barcode scanning and OCR.

## Database Safety

Which database is safe to write to is decided by the **database name**, not by the backend type.
Read the active name from `backend/system.db` (`system_settings.mysql_database`) or `MYSQL_DATABASE`.

- **`freemarket_test` — test database.** Normal development work, schema migrations, and test data are all fine here. This is the database usually configured in this repo.
- **SQLite (`backend/mercariDB.db`) — local development.** Free to modify.
- **Any other MySQL database — treat as production.** Do NOT run or generate any statement that changes data or schema (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, migrations, seed data, manual ORM writes). Read-only inspection (`SELECT`, `SHOW`, `DESCRIBE`) is fine. If a task appears to require a change there, **stop and ask first**.

When unsure which database is active, check the name before writing — an unrecognized name counts as production.

## Code Organization Rules

- **Target file length: 500 lines.** Keep `.py` files under `backend/` at or below **500 lines**. When a module grows past this, prefer splitting it by feature — convert it into a package (a folder named after the module with an `__init__.py` that re-exports the public API so existing imports keep working) and group related functions into separate files. Keep shared helpers in a `_common`/`_helpers` module and group cohesive features into their own files (and subfolders when a feature spans several files).

- **Exceeding 500 lines is allowed when splitting would hurt.** Some files are more readable whole — a single cohesive state machine, a long linear automation script, or a registry of related definitions. Don't split a file *just* to satisfy the number, and don't refactor an existing over-length file unless you're already changing it for another reason. Current accepted exceptions: `db_manage/db_manager.py`, `web_drive/listing/units/post_to_macket/post.py`, `use_mercari/get_to_du_list/transaction_detail/wait_shipping/ship_finalize.py`. For **new** files, still aim under 500 — go over only deliberately.

## Technology Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Frontend | Vue 3, Vite, Vue Router, Pinia, Element Plus | Dev: port 9600 (HTTPS), Prod: static SPA |
| Backend | Python 3.11+, FastAPI, Uvicorn | Port 9601, OpenAPI docs at /docs |
| Database | SQLite WAL mode (default) / MySQL 8.0+ | backend/mercariDB.db (auto-created); MySQL via `DB_BACKEND=mysql` |
| Authentication | JWT (Bearer tokens) | 12-hour expiry by default |
| Image Storage | Local filesystem | backend/imges/ directory |
| Browser Automation | Playwright | For Mercari listing management |
| Request Inspection | mitmproxy | SSL/TLS interception (Windows) |
| ML/Vision | EasyOCR, OpenCV | For barcode/text recognition |

## Development Setup

### Quick Start

```powershell
start.bat   # Windows
```

```bash
./start.sh  # Mac / Linux
```

All-in-one: activates conda env (or auto-creates backend/.venv on Mac/Linux), starts backend & frontend.

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Development (with auto-reload)
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601
```

First startup auto-creates default admin: `admin / admin` — change immediately in System tab.

### Frontend

```powershell
cd webside
npm install
npm run dev
```

Frontend server: **https://localhost:9600** (self-signed HTTPS by default)
- HTTP only: set `MERCARI_DEV_HTTP=1` before `npm run dev`
- Remote/domain HMR: set `MERCARI_DEV_PUBLIC_HOST=yourhost` in `webside/.env.development`

### Production Build (Frontend)

```powershell
cd webside
npm run build  # Output to webside/dist/
```

The FastAPI backend can serve the SPA by mounting `webside/dist`. Override with `MERCARI_WEBSIDE_DIST` env var or disable with `MERCARI_NO_STATIC=1`.

## Project Structure

```
backend/
├── main.py                          # FastAPI entry point, app initialization
├── requirements.txt                 # Python dependencies
├── mercariDB.db                     # SQLite database (WAL mode)
├── imges/                           # Product image storage
└── src/
    ├── auth.py                      # JWT token generation & verification
    ├── app_paths.py                 # Development vs PyInstaller path handling
    ├── image_storage.py             # Base64/upload image handling
    ├── mercari_auto_fetch_loop.py     # Background task: periodic Mercari sync
    ├── system_service.py            # System utilities (restart, etc.)
    ├── order_goods_ratio.py         # Order-to-inventory analysis
    ├── db_manage/                   # Database layer
    │   ├── base_model.py            # Abstract BaseModel for all tables
    │   ├── database.py              # DatabaseManager singleton (SQLite connection pooling)
    │   ├── db_manager.py            # DBManager: coordinated table init & migrations
    │   └── models/                  # Table models (inventory.py, user.py, etc.)
    ├── routes/                      # REST API blueprints
    │   ├── auth.py                  # Login, token refresh
    │   ├── inventory.py             # Product inventory CRUD
    │   ├── orders.py                # Order management
    │   ├── mercari_accounts.py        # Mercari account config
    │   ├── on_sale_items.py         # Mercari listing sync display
    │   ├── warehouses.py            # Warehouse & shelf location management
    │   └── [other routes]
    ├── use_mercari/           # Mercari API & sync logic
    │   ├── API.py                   # FastAPI router for /api/mercari endpoints
    │   ├── sync_data.py             # Mercari API client wrapper
    │   ├── on_sale_items_sync.py    # Fetch & sync item listings
    │   └── mgmt_id_cipher.py        # Encode/decode secret code from descriptions
    ├── web_drive/                   # Playwright browser automation
    │   ├── manager.py               # Browser manager singleton
    │   ├── interactive_browser.py   # Headed browser for user interaction
    │   ├── mitm_session.py          # Per-op headed minimized Edge for MITM ops
    │   └── account_serial_queue.py  # Serial task execution per account
    └── ssl_mitm_proxy/              # mitmproxy integration
        ├── runner.py                # Start/stop MITM proxy
        ├── mitm_addon.py            # Custom mitmproxy addon for request capture
        └── windows_trust.py         # Windows cert trust utilities

webside/
├── package.json
├── vite.config.js                   # Dev server: port 9600, /api & /imges proxy to 9601
├── dist/                            # Production build output
└── src/
    ├── main.js                      # Vue app initialization (Pinia, router, Element Plus)
    ├── api/index.js                 # Axios HTTP client with JWT interceptors
    ├── router/index.js              # Vue Router with auth guards
    ├── views/                       # Page components (Dashboard, Inventory, Orders, etc.)
    └── components/                  # Reusable components (Layout, dialogs, forms)
```

## Database Models & Core Tables

Key tables in `backend/src/db_manage/models/`:

- **users**: User accounts with bcrypt passwords
- **inventory**: Products with barcode, SKU, price, quantity, images (filesystem paths in `images_json`; images saved under `backend/imges/`)
- **warehouses**: Storage locations (shelf names duplicable per warehouse)
- **mercari_accounts**: Mercari account config (headers in value JSON field)
- **on_sale_items**: Mercari listing records synced from API
- **orders**: Mercari orders synced from API
- **order_outbound_lines**: Line items for outbound shipments
- **transactions**: In/out stock movements with warehouse tracking
- **cost_records**: Packaging material inventory
- **cost_expenses**: Packaging material usage per order

## Key Architectural Patterns

### Custom ORM Database Layer

1. **BaseModel** (`base_model.py`): Abstract base defining `get_table_name()` and `get_fields()`
2. **DatabaseManager** (singleton): Manages SQLite connection pooling with WAL mode
3. **DBManager** (`db_manager.py`): Coordinates all model registration, table creation, migrations
4. Migrations handled in `db_manager.py` (e.g., warehouses composite unique constraint)

### Authentication Flow

1. User logs in via `POST /api/auth/login` (username + password)
2. Backend verifies with bcrypt, creates JWT with `user_id` and `username`
3. Frontend stores token in `localStorage`
4. Axios interceptor adds `Authorization: Bearer <token>` to all requests
5. Backend `require_auth()` dependency verifies JWT, raises 401 if expired/invalid
6. Token expiry: `JWT_EXPIRE_HOURS` env var (default 12)

### Mercari Integration Pipeline

1. User adds Mercari account in Web UI → headers & cookies stored in `mercari_accounts.value` (JSON)
2. `mercari_auto_fetch_loop()` runs on startup, periodically syncs orders & items
3. `sync_data.py`: Wraps Mercari API calls (fetch orders, items, etc.)
4. `on_sale_items_sync.py`: Incremental sync with local DB
5. `mgmt_id_cipher.py`: Decodes secret codes embedded in item descriptions
6. Browser automation (`web_drive/`): Playwright for listing operations
7. SSL MITM proxy: Captures HTTP traffic for debugging/inspection

### Task Queue (`src/task_queue/`)

All **heavy Mercari automations** run as background tasks instead of blocking the HTTP request.
The frontend submits and returns immediately; progress is watched on `/#/tasks`.

Queued operations (9 types, see `registry.py`): inventory listing; orders update-list /
update-status / single-row refresh; on-sale sync / full-update / revise; todos bulk-review /
bulk-confirm-ship. **Batch revise is not a separate type** — the frontend submits N `on_sale.revise`
tasks, so closing the page no longer aborts halfway.

- **Single global worker, strictly serial** (`worker.py`) — matches the existing global
  `sync_lock` / `listing_lock` semantics. Tasks still descend into `run_mercari_serial_async`,
  so per-account browser reuse/auto-close is unchanged.
- Handlers (`handlers/`) are thin: they unpack the payload, bridge progress, and call the
  **existing** business functions. Automation logic was not moved.
- Endpoints that used to hold `sync_lock` now expose a lock-free `*_core()`; the HTTP entry keeps
  409-on-conflict while handlers use `sync_lock.begin_waiting()` to **queue** instead of failing.
- `progress.py` copies the existing in-memory `*_progress` stores into `task_queue.progress_label`,
  so deep automation code needed no changes.
- **Duplicate submission is blocked server-side** by two unique indexes: `client_token`
  (one click = one task, immune to double-click/retry) and `active_dedup_key` (nulled on terminal
  state, so one "update list" at a time).
- **Listing reservations** (`reservations.py`): enqueueing a listing immediately increments
  `inventory.pending_listing_qty`, so 可上架 drops at click time and over-listing is impossible.
  The reservation is held until on-sale sync binds the new item (`_adjust_on_sale` → `consume`),
  released only when a listing is *confirmed* not submitted, with a TTL sweep
  (`TASK_LISTING_RESERVATION_TTL_SEC`, default 6h) as backstop. An unexpected crash **keeps** the
  reservation — under-listing is recoverable, duplicate listing is not.
- Ordering: since the worker is FIFO, a sync task submitted after listings naturally waits for them.
  `mercari_auto_fetch_loop` additionally defers while listing tasks are queued (max 30 min).
- On restart, `running` tasks are marked failed and their reservations released — browser
  automation is never auto-retried (it may already have clicked 出品する).

## Environment Variables

**Backend**:
- `DB_BACKEND`: Database backend — `sqlite` (default) or `mysql`. The database layer is dialect-abstracted (`src/db_manage/dialects/`); all call sites write SQLite-style SQL (`?` placeholders, `[identifier]` brackets) and the MySQL dialect translates at execution time. Switching backends requires no call-site changes. **Backend selection precedence: the UI/`system.db` setting > this env var > default `sqlite`.** The active backend is normally managed from the UI (see below), which persists it to `backend/system.db`.
- `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` / `MYSQL_POOL_SIZE`: MySQL 8.0+ connection fallback settings (used when not configured via the UI; requires `PyMySQL`). The target database is auto-created on startup when privileges allow. Migrate existing SQLite data with `python -m tools.sqlite_to_mysql` (see that script's header).

**Database management UI**: System 管理 → 数据库管理 (`/system/database`) lets the user choose SQLite/MySQL, test the MySQL connection, and switch backends. Switching migrates all data from the current backend to the target (`src/db_manage/migrate.py`), persists the choice + connection params to the always-SQLite bootstrap store `backend/system.db` (`src/db_manage/db_settings.py`), then auto-restarts the backend. In MySQL mode, `system.db` (SQLite) retains only this bootstrap config; all business data lives in MySQL.
- `JWT_SECRET`: Signing key (change in production)
- `JWT_EXPIRE_HOURS`: Token validity (default: 12)
- `SSL_MITM_AUTO_START`: Set to `0` to disable mitmproxy (default: 1)
- `INTERACTIVE_BROWSER_AUTO_START`: Set to `0` to disable headed browser auto-start at boot (default: 0)
- `WEB_DRIVE_AUTOMATION_HEADLESS`: When enabled, all automation browsers (data fetch / startup pre-warm / MITM listing/delete/revise / mercari MITM capture) launch truly headless (silent, never shown in the foreground). Does NOT affect the manual "Open Browser" button on `/mercari-accounts` (always headed). **Default: 1 (headless).** Set to `0` to launch them headed+minimized for debugging.
- `WEB_DRIVE_MITM_MINIMIZED`: Set to `0` to keep MITM automation windows in the foreground; otherwise they are minimized to the taskbar. Default: 1. Has no effect when automation is headless (the default).
- `TASK_LISTING_RESERVATION_TTL_SEC`: How long a listing's 可上架 reservation may stay unclaimed before the task queue force-releases it and logs a warning (default 21600 = 6h). See "Task Queue" above.

**Frontend** (`webside/.env.development`):
- `MERCARI_DEV_HTTP`: Use HTTP instead of HTTPS (default: 0)
- `MERCARI_DEV_PUBLIC_HOST`: Hostname for remote HMR WebSocket
- `MERCARI_DEV_HMR_CLIENT_PORT`: Custom HMR port (default: 9600)

## Accessing the Application

**Development**:
- Frontend: https://localhost:9600 (self-signed cert)
- Backend API: http://localhost:9601
- OpenAPI docs: http://localhost:9601/docs
- Health check: http://localhost:9601/api/health

**Network Access**: Vite and uvicorn are both bound to `0.0.0.0` — LAN access via `https://<your-ip>:9600`.

## Adding a New API Route

1. Create `backend/src/routes/myfeature.py` with a FastAPI router
2. Import in `backend/main.py` and register with `app.include_router()`
3. If auth required, add `dependencies=auth_required`
4. Frontend: Add API calls in `webside/src/api/index.js`, add route in `webside/src/router/index.js`

## Adding a New Database Table

1. Create model in `backend/src/db_manage/models/mymodel.py` extending `BaseModel`
2. Define `get_table_name()`, `get_fields()`, optionally `get_indexes()`
3. Import & register in `backend/src/db_manage/db_manager.py`
4. Table auto-created on backend startup via `init_database()`

## Useful Commands

| Task | Command |
|------|---------|
| Backend dev (auto-reload) | `cd backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601` |
| Frontend dev | `cd webside && npm run dev` |
| Frontend build | `cd webside && npm run build` |
| Backend deps | `cd backend && pip install -r requirements.txt` |
| Frontend deps | `cd webside && npm install` |
| Disable heavy startup features | `SSL_MITM_AUTO_START=0 INTERACTIVE_BROWSER_AUTO_START=0 python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601` |
"" 
# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
