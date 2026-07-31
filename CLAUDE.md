# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FreeMarket Manager is a **full-stack inventory and order management system** with deep integration to the Japanese Mercari and Yahoo!フリマ marketplaces. It's built as a Vue 3 frontend (Vite) with a Python FastAPI backend, featuring order synchronization, product listing automation, and local inventory management with support for barcode scanning and OCR.

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

### Yahoo!フリマ (PayPayフリマ) Listing

`mercari_accounts.platform` (`mercari` default / `yahoo`) selects the marketplace. Implemented for
Yahoo: **listing, on-sale list+detail sync, revise/suspend/resume/delete, sold-order sync +
single-order refresh + order-status batch refresh + fee backfill, auto-relist, todo sync,
notification sync, and the todo 处理 flow (trade detail / 发货 / 交易留言)**. Still Mercari-only:
受取評価, the bulk todo operations (一键好评 / 一键确认发送), QR/扫码 (Yahoo has no equivalent —
its 配送コード is issued server-side, nothing to scan), and every *notification* action
(回复评论/同意降价) — Yahoo notices remain display-only.

**Every account-driven entry point dispatches on `mercari_accounts.platform`** — the auto-fetch
loop, the account page's 同步数据, on-sale sync / full-update / fetch-detail (single + batch),
order sync + single-row refresh + batch status refresh, todo sync, todo 处理, and
listing/revise/suspend/delete. Unsupported
combinations skip with a note or return a clear 400; nothing falls through to a Mercari
implementation with a Yahoo account.

Yahoo has no usable list/detail API — every page is server-rendered, so `use_yahoo/` parses pages
with the automation browser. Two things make that tolerable: item cards carry a structured
`data-cl-params` attribute (`rcconid` / `opentime` / `wl` / `viewcnt` / `srchcnt`), and the parsed
rows are fed into the **existing Mercari writers** (`apply_on_sale_list_sync`, `_upsert_order`), so
soft-delete, inventory counters and order upsert semantics stay identical across platforms.

- `use_yahoo/on_sale/list_sync.py` — `/my/item/selling` → `on_sale_items` (`platform='yahoo'`).
  Soft-delete only fires when the crawl is provably complete (`出品数: N/100` vs collected count).
- `use_yahoo/on_sale/detail_sync.py` — reads the **edit page**'s form fields (textarea gives the
  description verbatim, so the `-=~<>` mgmt cipher survives) and feeds a Mercari-shaped pseudo
  `items/get` response into `detail_sync_inventory_from_item_get_response`. This is what binds a
  Yahoo listing to inventory and consumes the listing reservation; it runs automatically for newly
  inserted items after each list sync (`WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL=0` disables it).
- `use_yahoo/orders/sold_sync.py` — `/my/item/sold` + each `/item/{id}/trade/seller` → `orders`
  (`order_no` = Yahoo item id). Status is matched **only in the page's first 400 chars**: the
  trade page keeps a hidden 取引キャンセル dialog in the DOM that makes whole-body matching report
  every pending order as cancelled. Unrecognized status → skipped and reported, never guessed.
  After shipment the page rewrites itself: the status line becomes 「商品の発送を通知しました」
  (→ `wait_review`), 配送方法 switches from the pre-ship 「おてがる配送（…）」 to the concrete method
  (e.g. ゆうパケットポスト（専用箱/シール）), and the tracking number appears under
  「配送のお問い合わせ」 — not 「送り状番号」. All three are parsed; `_upsert_order` writes
  `carrier_display_name`/`tracking_no` only when non-empty so the two platforms never blank
  each other's values.
  **A sold-list card is the `<a>` itself** — the list has no `li`, so `a.parentElement` is the
  container holding *every* card and reading its `innerText` silently gives all rows the *first*
  card's title and price. Scope card parsing to the anchor. Item name is also taken from the trade
  page (the line above the 成交价 / 売上履歴を見る block), so single-row 刷新 can correct it without
  the list. `thumbnails` must be stored as a **JSON array string** (`["https://…"]`) like Mercari's —
  the orders table `JSON.parse`s it and renders a bare URL as no image.
- `use_yahoo/item_page.py` — reads a listing's description from the **public** item page. The order
  → inventory binding needs the mgmt cipher in the description, normally taken from
  `on_sale_items.listing_description`; but an item that sold before its first on-sale sync has no
  such row, and a sold item's **edit page 404s**, so it can never be backfilled from there.
  `_resolve_description` in `sold_sync.py` therefore falls back: on_sale_items → the order row's
  stored description → the item page. Two traps on that page: the description is collapsed behind
  「もっと読む」 and **the cipher is the last line**, so it must be expanded before reading; and once
  expanded the container also swallows the 購入日時/公開日時/出品日時 block, so parsing must cut at the
  first metadata line rather than trim trailing blanks (trimming stops at 出品日時 and leaves the
  cipher stranded mid-text, where `parse_trailing_cipher_mgmt_tokens` won't see it).
- `use_yahoo/seller.py` — Yahoo has no seller_id in any payload; it is scraped once from the
  `/user/{id}` link on `/my` and written back to `mercari_accounts.seller_id`. That same link also
  carries the nickname (first line of its text), which is what the account dialog's 获取基础信息
  button returns for Yahoo — **no MITM**, unlike Mercari where seller_id only exists in the
  `items/get_items` query string. Like Mercari's button it does not persist; the form saves.
  Avatar is deliberately not synced: Yahoo's profile header has no avatar `<img>`, only
  `_next/static` icons, so there is nothing safe to pick. New-account fetches run against the
  `yahoo_prepare` pre-login session, which `resolve_prepare_alias` now isolates per user the same
  way it always did for `mercari_prepare`.
- `web_drive/yahoo_item/` — revise / suspend / delete all live on one page
  (`/item/{id}/edit`, public domain — the `-sec` host 404s) whose form is identical to the listing
  form, so `post_to_yahoo._fields` is reused. Buttons: 変更する / 出品を停止する / 商品を削除する.
- `web_drive/core/yahoo_session.py` — same MITM + cookie-clone session as Mercari, only with
  `cookie_domains=("yahoo","paypay")`; `export_cookies_full` filters by domain, so without this the
  Yahoo session is silently logged out.
- `use_yahoo/todos/todo_sync.py` — the one Yahoo endpoint that is a clean JSON API:
  `GET /api/v1/notices/todo?result=30&offset=0` (login cookies required). Yahoo todo types map to
  their own `Yahoo*` kinds (`ooesh` → `YahooShipRequest`) rather than onto Mercari kinds — reusing
  `WaitShippingCard` etc. would make the todos page run Mercari-only ship/QR automation on a Yahoo
  row. The kind *is* listed in `_WAIT_SHIPPING_COND` so 発送依頼 lands in the 待发货 chip. This
  naming is also what keeps 一键好评 / 一键确认发送 / 详情预抓 off Yahoo rows for free — they all
  filter on Mercari `kind`/`title` constants that no `Yahoo*` value matches.
- `web_drive/yahoo_trade/` + `use_yahoo/todos/trade_actions.py` — the todo 処理 flow. The whole
  Yahoo transaction lives on one page, so this package splits by *action* (`_page` sheet/row
  primitives, `detail`, `ship`, `message`) rather than by page.
  - **发货 is one form, not a wizard**: 品名 (maxlength 17) + サイズ + 発送場所, then one button.
    That button is the state machine — it reads 「発送情報を入力してください」 and is disabled until
    all three are set, then flips to 「配送コードを表示する」. `ship.py` **verifies the flip before
    clicking** and aborts otherwise; a half-filled submit issues a 配送コード for the wrong size and
    the postage difference gets billed later. `dry_run=True` stops exactly at that check.
  - **Size/location options are read from the live page, never hard-coded** — the list changes with
    the 配送会社 (日本郵便 → ゆうパケット/プラス/ゆうパック; ヤマト has its own). They're read off the
    sheet's `input[type=radio]` → first text leaf of its `<label>`, which is the same string
    `_SHEET_CLICK_JS` matches, so enumerate and click can't drift apart. Scanning `li/p/label` text
    instead returns the same option at several nesting depths (`ゆうパケットプラス` *and*
    `ゆうパケットプラス24cm×17cm以内`).
  - `発送場所` is an `h3` row, not a `<button>` like `サイズ` — hence the unified "click the element
    whose first line is X and let React bubble it" helper instead of `get_by_role`.
  - The page has no trade API at all: `__NEXT_DATA__` carries only an empty Redux state and no XHR
    fetches trade data — it is server-rendered HTML. Messages are parsed as `sender / text / stamp`
    from the row containing a relative-time leaf.
  - Endpoints are a separate `/{todo_id}/yahoo/*` group; the Mercari `transaction-detail` endpoints
    now **400 on a Yahoo todo** rather than opening `jp.mercari.com/transaction/z…`.
- `use_yahoo/orders/batch_refresh.py` — 订单「更新状态」的雅虎实现（逐条重读交易页）。
  `OrderModel.find_for_batch_info_refresh` now takes `platform`; without it the Mercari
  `transaction_evidences` batch would pick up `z…` orders and open Mercari transaction pages that
  don't exist. With no account specified the endpoint runs **both** platforms and merges the stats.
- `use_yahoo/notifications/notice_sync.py` — `GET /api/v1/notices/personal`, same JSON shape and
  same `Yahoo*` kind policy as todos.
- `use_yahoo/orders/sales_history.py` — 販売手数料/送料/到手金額 live on a **different domain**,
  `salesmanagement.yahoo.co.jp/list` (shared Yahoo sales ledger, same login cookies). The 内訳
  `dl/dt/dd` is in the DOM even while collapsed, so no clicking. Runs at the end of order sync.
  Fees are **always the ledger's own numbers, never computed** — Yahoo's cut is not a clean
  percentage (2,850円 → 141円, not 5%'s 142.5). When a fee is zero (e.g. the 販売手数料0円 campaign
  shown as a banner on `/my`) Yahoo simply **omits the 販売手数料 row**, which is indistinguishable
  from "breakdown not read" if you only write what you find. The parser resolves that by
  arithmetic: 決済金額 present and 到手金額 == 決済金額 ⇒ genuinely no deduction ⇒ `service_fee = 0`.
  Books that don't balance write nothing and stay empty for the next run. `shipping_fee` gets no
  such zero-fill — a shipped ゆうパケットポスト order still shows no 送料 row and nets exactly
  amount − fee, i.e. postage is settled elsewhere, not free.
- `platform` columns on `on_sale_items` / `orders` / `todo_items` / `notifications` drive the 平台
  filter + tag on `/#/on-sale-items`, `/#/orders`, `/#/todos`, `/#/notifications`. Mercari writers
  set `'mercari'` explicitly; legacy rows with no value are treated as Mercari in every filter.

- `web_drive/listing/units/post_to_yahoo/` mirrors `post_to_macket/` and returns the **same result
  keys** (`submitted` / `submit_clicked` / `submit_uncertain` / `*_error`), so the task queue
  handler and frontend need no platform branches. Form URL: `paypayfleamarket-sec.yahoo.co.jp/item/add`.
- Dispatch happens in `use_web/web_drive/units/web_drive_handler/listing.py::post_to_market`, which
  looks up the account platform. Session reuse is total: `listing_automation_browser` gained
  `cookie_domains` so the same MITM + cookie-clone machinery clones Yahoo cookies instead of Mercari's.
- **Category**: Yahoo's tree is unrelated to Mercari's and must be drilled to a leaf, so
  `product_type_category_mappings.yahoo_category_path` stores the full Japanese path
  (`本、雑誌、コミック > 医学、薬学、看護 > 医学一般 > 医学一般全般`), edited in 系统管理 → 煤炉类型映射.
  Missing path → the listing is rejected up front with a clear 400.
- **Category catalog**: 系统管理 → 雅虎类型映射 (`/system/yahoo-category-mappings`) is a hand-maintained
  catalog of Yahoo leaf categories in table `yahoo_category_mappings` (id + 3 levels + leaf name +
  full path). It is paginated/searchable server-side because the tree is large. The Mercari mapping
  page's 雅虎分类 field autocompletes from it, so the path that drives the automation is picked rather
  than typed. (Auto-scraping Yahoo's `/api/v1/categories/{id}/children` was tried and dropped: the
  endpoint returns intermittent 500s under any sustained crawl, so the collected tree came out
  badly truncated.)
- Yahoo has no 送料負担 (always seller) and no auction; those fields are hidden in the listing dialogs
  (`useListingPlatform.js`) and ignored by the backend. Shipping method maps
  `rakuraku`→ヤマト運輸 / `yuuyu`→日本郵便; other values keep the page default (日本郵便).
- The page is React-controlled: values must be typed (not set via DOM setters) and **committed on
  blur** — the price only reaches state after blur. Selection sheets are detected by the inline
  style `bottom: 0px` (closed sheets stay in the DOM with nonzero size).

### Task Queue (`src/task_queue/`)

All **heavy Mercari automations** run as background tasks instead of blocking the HTTP request.
The frontend submits and returns immediately; progress is watched on `/#/tasks`.

Queued operations (see `registry.py` for the authoritative list): inventory listing; orders
update-list / update-status / single-row refresh; on-sale sync / full-update / revise / delist /
suspend / resume; todos sync / bulk-review / bulk-confirm-ship / shipping-QR; and the account
card's 同步数据 (`account.sync_data`). **Batch revise is not a separate type** — the frontend
submits N `on_sale.revise` tasks, so closing the page no longer aborts halfway.

`account.sync_data` dedups **per account** (`account.sync_data:{id}`), so different accounts can
each hold a queued sync while one account can't be double-queued. Its handler waits on the global
`sync_lock` via `begin_waiting` rather than 409-ing, and converts the `HTTPException` that the
shared `*_core()` raises for a disabled/missing account into a plain error so the task row shows
the message instead of `404: …`.

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
- On restart, `running` tasks are marked failed but their listing reservations are **kept**
  (released only by the TTL sweep) — a hard crash cannot tell whether 出品する was already
  clicked, and browser automation is never auto-retried.

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
