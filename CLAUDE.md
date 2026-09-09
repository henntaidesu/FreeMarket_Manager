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

`db_manage/db_settings.py::is_test_database()` whitelists `freemarket_test` (plus anything in
`TEST_DATABASE_NAMES`) and treats SQLite as a test DB. The production DB name is `mercari`.

**What that predicate actually gates is narrow, so read this before assuming you are protected.**
It guards exactly one thing: the two destructive schema-sync steps, via
`db_manage/schema_guard.py::destructive_schema_allowed()` —
`initialize_database()`'s drop-unknown-tables pass and `BaseModel`'s drop-undeclared-columns pass.
On a non-test database both are **skipped, not aborted** (raising would make the app unbootable in
production), and every skip *and* every executed drop is written to `system_logs` under category
`schema`. `DB_DESTRUCTIVE_SCHEMA_SYNC=0` turns them off on test databases too.
Ordinary `INSERT`/`UPDATE`/`DELETE` are **not** gated by anything — the rule above is a convention
you have to follow, not something the code will stop you from breaking.

## Code Organization Rules

- **Target file length: 500 lines.** Keep `.py` files under `backend/` at or below **500 lines**. When a module grows past this, prefer splitting it by feature — convert it into a package (a folder named after the module with an `__init__.py` that re-exports the public API so existing imports keep working) and group related functions into separate files. Keep shared helpers in a `_common`/`_helpers` module and group cohesive features into their own files (and subfolders when a feature spans several files).

- **Exceeding 500 lines is allowed when splitting would hurt.** Some files are more readable whole — a single cohesive state machine, a long linear automation script, or a registry of related definitions. Don't split a file *just* to satisfy the number, and don't refactor an existing over-length file unless you're already changing it for another reason. Current over-length files (all deliberate): `db_manage/db_manager.py` (832), `use_mercari/get_to_du_list/transaction_detail/wait_shipping/ship_finalize.py` (592), `use_mercari/inventory_counters.py` (573), `use_web/todos/units/todos_query.py` (532), `web_drive/listing/units/post_to_macket/post.py` (526), `web_drive/core/mitm_session.py` (506), `use_mercari/get_order/get_in_progress_order/get_order_info.py` (503). For **new** files, still aim under 500 — go over only deliberately.

  Re-check the list with:
  `find backend/src -name "*.py" -exec wc -l {} + | sort -rn | awk '$1>500'`

## Technology Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| Frontend | Vue 3, Vite, Vue Router, Pinia, Element Plus | Dev: port 9600 (HTTPS), Prod: static SPA |
| Backend | Python 3.11+, FastAPI, Uvicorn | Port 9601 (dev) / 9600 (frozen); `/docs` off by default |
| Database | SQLite WAL mode (default) / MySQL 8.0+ | backend/mercariDB.db (auto-created); MySQL via `DB_BACKEND=mysql` |
| Authentication | JWT (Bearer tokens) | **No expiry by default** (`JWT_EXPIRE_HOURS=0`); revoked via `token_version` |
| Image Storage | Local filesystem (default) / Image Hosting | `backend/imges/`; switchable to a remote image host at runtime — see 图床存储 below |
| Browser Automation | Playwright | Edge/Chromium; drives both Mercari and Yahoo |
| Request Inspection | mitmproxy | SSL/TLS interception (Windows) |
| ML/Vision | EasyOCR, OpenCV, CLIP (ONNX Runtime) | Barcode/text recognition + image search |
| AI | DeepSeek (OpenAI-compatible) | Generates Japanese listing title/description |
| i18n | vue-i18n | zh-CN / ja / en — all three locales must stay in sync |
| Packaging | PyInstaller + pystray | Windows .exe with tray icon & log window |

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

Frontend server: **http://localhost:9600** — plain HTTP, no built-in TLS anywhere in this app.
HTTPS is terminated by an external nginx reverse proxy.
- **No host binding**: `allowedHosts: true` (DNS-rebinding protection deliberately off, self-hosted
  only) and the HMR client infers its hostname from the page, so any domain or LAN IP works unchanged.
- Behind nginx over https: set `MERCARI_DEV_PUBLIC_ORIGIN=https://yourhost` in
  `webside/.env.development` — only its scheme+port are used, to make HMR connect over `wss` on that
  port. Otherwise the https page's `ws://` socket is blocked as mixed content.

### Production Build (Frontend)

```powershell
cd webside
npm run build  # Output to webside/dist/
```

The FastAPI backend can serve the SPA by mounting `webside/dist`. Override with `MERCARI_WEBSIDE_DIST` env var or disable with `MERCARI_NO_STATIC=1`.

## Project Structure

There is **no `src/routes/` package** — the HTTP layer is `use_web/`, one folder per frontend page.

```
backend/
├── main.py                          # Thin entry: mitmdump self-dispatch, console/log window,
│                                    #   FastAPI app, CORS, /imges route, router + lifecycle
├── mercariDB.db                     # SQLite business data (WAL); system.db = bootstrap config
├── imges/                           # Product image storage (local backend; also thumb/CDN caches)
├── models/                          # Downloaded ML weights (CLIP ONNX) — not DB models
├── tools/                           # sqlite_to_mysql.py, clone_mysql_to_test.py (run via -m)
└── src/
    ├── API.py                       # /mercariV2 root router + /mercariV2/health
    ├── lifecycle.py                 # startup/shutdown orchestration (see Startup Sequence)
    ├── server.py                    # uvicorn launch, TLS resolution, tray, hard-kill on exit
    ├── readiness.py                 # is_ready()/mark_ready() — health 503s until startup done
    ├── auth.py  app_paths.py  system_service.py  memory_recycle.py
    ├── tray.py  log_window.py  console_win.py     # frozen(.exe)-only Windows UI
    ├── db_manage/                   # Custom ORM: base_model, database, db_manager,
    │   ├── dialects/                #   dialect abstraction (sqlite / mysql translation)
    │   ├── db_settings.py           #   bootstrap store in system.db + is_test_database()
    │   ├── migrate.py               #   SQLite <-> MySQL data migration
    │   └── models/                  #   grouped by domain: inventory/ orders/ system/ todos/ ...
    ├── use_web/                     # ==> THE REST API LAYER (one package per frontend page)
    │   ├── API.py                   #   aggregates all page routers under /use_web
    │   ├── <page>/API.py            #   router; <page>/units/*.py holds the handlers
    │   ├── inventory/image_search/  #   CLIP-ONNX image similarity search
    │   └── web_drive/               #   browser-automation endpoints (incl. listing dispatch)
    ├── use_mercari/                 # Mercari business orchestration
    │   ├── API.py  auto_relist.py  inventory_counters.py   # 计数模型的权威实现
    │   ├── inventory_stock_apply.py  # ⚠ 已废弃、零调用（旧数量模型，接回去会双重扣减）
    │   ├── mgmt_id_cipher.py     # secret code in item descriptions — the real binding
    │   ├── mgmt_image_cipher.py  # QIM image watermark — embedded but never decoded (see below)
    │   └── sync/  on_sale/  get_order/  get_to_du_list/  get_notifications/
    ├── use_yahoo/                   # Yahoo!フリマ equivalents (page scraping, see below)
    │   ├── app_api/                 #   手机 App 的 sparkle JSON API（ゆうパケットポスト 发货唯一口子）
    │   └── on_sale/  orders/  todos/  notifications/  seller.py  item_page.py
    ├── web_drive/                   # Playwright automation
    │   ├── core/                    #   manager/, mitm_session, listing_session, yahoo_session,
    │   │                            #   interactive_browser, account_serial_queue, paths
    │   ├── sell_edit_state.py       #   煤炉编辑页按钮回读 + 暂停/恢复的生效校验（共享）
    │   └── listing/ revise/ suspend/ resume/ delete/ yahoo_item/ yahoo_trade/
    ├── task_queue/                  # Background job queue (see Task Queue below)
    ├── ssl_mitm_proxy/              # mitmproxy runner, addon, Windows cert trust
    ├── mercari_proxy/               # Node reverse proxy subprocess (runner.py + server.js)
    └── ai/deepseek_client.py        # DeepSeek: AI-generated listing title/description

webside/
├── vite.config.js                   # Port 9600 HTTPS; proxies /mercariV2, /api, /imges -> 9601
└── src/
    ├── api/                         # One module per resource; index.js re-exports them all
    │   └── http.js                  #   Axios instance + JWT interceptors
    ├── i18n/locales/                # zh-CN / ja / en — all three must be updated together
    ├── router/index.js              # Routes + auth guards
    ├── views/                       # Page components; views/system/* for the system sub-pages
    └── components/ composables/ stores/ utils/ constants/
```

### API Path Convention

Everything is mounted under **`/mercariV2`** — there is no `/api/*` business route
(`/api/health` survives only as a legacy alias registered in `web_static.py`).

```
/mercariV2/health                              # 503 until startup completes
/mercariV2/src/use_web/<page>/<endpoint>       # frontend page APIs
/mercariV2/src/use_mercari/<module>/<endpoint> # Mercari orchestration (auth required)
```

Auth is applied **at the aggregation point**, not per-endpoint: `use_web/API.py` attaches
`dependencies=[Depends(require_auth)]` when including each page router, and `src/API.py` does the
same for the whole `use_mercari` tree. Public endpoints must be exported as a separate
`public_router` and included without that dependency (see `login`, `inventory.public_router`,
`mercari_image.public_router`).

### Startup Sequence (`src/lifecycle.py`)

Order matters and is documented in-file: MITM proxy → mercari-proxy → `init_database()` → image
search indexer → headed-debug flag → Mercari auto-fetch loop → memory recycler → optional
interactive browser → `mark_ready()`. Health checks return 503 until that last step.

## Database Models & Core Tables

Key tables in `backend/src/db_manage/models/`:

- **users**: User accounts with bcrypt passwords
- **inventory**: Products with barcode, SKU, price, quantity, images (filesystem paths in `images_json`; images saved under `backend/imges/`)
- **warehouses**: Storage locations (shelf names duplicable per warehouse)
- **product_type_category_mappings**: 商品类型主表 (one row = one 商品类型). `inventory.product_type_id` → `mapping_id` (TEXT PK, numeric, auto-incremented on create, never user-visible). See 商品类型映射 below.
- **shop_accounts**: Marketplace account config (headers in `value` JSON field, `platform`,
  `seller_id`). **Renamed twice** — `meilu_accounts` → `mercari_accounts` → `shop_accounts`, with
  startup migrations in `models/shop_accounts/shop_account.py` and a self-check in `db_manager.py`.
  `ShopAccountModel.LEGACY_TABLE_NAME` still holds `mercari_accounts`; older docs/comments use the
  old names, but the live table is `shop_accounts`.
- **yahoo_app_tokens**: Yahoo phone-app OAuth tokens, one row per account (unique `account_id`).
  Deliberately *not* in `shop_accounts.value` — see `use_yahoo/app_api/` below.
- **on_sale_items**: Listing records synced from Mercari/Yahoo
- **orders**: Orders synced from Mercari/Yahoo
- **image_embeddings**: CLIP vectors for inventory image search (see Auxiliary Subsystems)
- **image_assets**: `/imges/<file>` → where that image actually lives. Only images that were moved
  to the image host get a row; no row = still a local file. See 图床存储 below.
- **task_queue**: Background job rows (see Task Queue)
- **config**: Generic key/value app settings — DeepSeek credentials live here, not in env vars
- **system_logs**, **memos**, **talk_scripts**, **settlement_records**, **desired_price_offers**,
  **bundle_purchase_requests**, **transaction_messages**, **categories**, **game_types**
- **order_outbound_lines**: Line items for outbound shipments
- **transactions**: In/out stock movements with warehouse tracking
- **cost_records**: Packaging material inventory
- **cost_expenses**: Packaging material usage per order

## 图床存储 (Image Hosting)

Product images live in `backend/imges/` by default. They can be moved wholesale to a separate
[Image Hosting](../Image_hosting) service, configured under System Config → 图床存储.

**`/imges/<file>` is a logical identifier, never rewritten.** Those strings sit in seven business
columns (`inventory.images_json`, `memos.images_json`, `transaction_messages.images_json`,
`image_embeddings.image_path`, `todo_items.qr_image_path`, `todo_items.ship_qr_photo_path`, plus
`shop_accounts.avatar`), and ~20 backend call sites and 5 frontend pages branch on
`startswith('/imges/')`. Rewriting them to absolute host URLs would mean touching every one of those
and would leave no way back. Instead, `image_assets` maps each logical path to where its bytes
actually are, and the switch changes only how that path is *resolved*.

```
src/image_hosting/
├── settings.py    # connection config + active backend, cached in-process (this is the hot-reload point)
├── client.py      # HTTP client for the host's /api/v1
├── assets.py      # image_assets read/write + hot-path cache
└── migration.py   # background local ⇄ host transfer (resumable, cancellable, reversible)
src/image_route.py # GET /imges/{path} — 302 to the host, or read from disk
src/use_web/image_storage.py  # the facade; THE ONLY module that knows which backend is active
```

- **Switching is instant and needs no restart.** The backend setting only decides where *new*
  images are written and how paths resolve; both are read per call through the cached settings.
- **Migration is a repeatable reconciliation, not a one-shot.** Its work set is "local file exists
  and has no mapping row", so a re-run picks up whatever is left. `external_key` (the logical path)
  makes the host side idempotent, so re-running never creates duplicates.
- **Not-yet-migrated images keep working**: no mapping row means "read from local disk". There is no
  window where an image 404s.
- **Upload failure degrades to local**: `_persist()` always writes to disk first, then tries to push
  to the host. If the host is down, the image stays local and the next migration run picks it up —
  a flaky image host must never fail a "save product".
- **Anything needing real pixels** (CLIP indexing, AI listing, watermarking, Playwright
  `set_input_files`) must go through `image_storage.read_image_bytes()`, and existence checks
  through `image_storage.image_exists()`. `os.path.exists` on an `/imges/` path is a bug once the
  image host is active.
- **Short-lived working files stay local** (`local_only=True` + `migration._SKIP_PREFIXES`): the
  `ship_qr_*` photo is opened by absolute path and deleted when the task ends.

**Deployment consequences.** With `delivery: redirect` (the default), the browser fetches images
straight from the image host, so nginx's `auth_basic` / Cloudflare Access no longer covers them —
the host's public URLs are unauthenticated by design (random UUID filenames). Protect the image
host's domain too, or set `delivery: proxy` to route bytes back through this service. Also, an
HTTPS page cannot load `http://` images (mixed content); the settings page warns about this.

## Key Architectural Patterns

### Custom ORM Database Layer

1. **BaseModel** (`base_model.py`): Abstract base defining `get_table_name()` and `get_fields()`
2. **DatabaseManager** (singleton): Manages SQLite connection pooling with WAL mode
3. **DBManager** (`db_manager.py`): Coordinates all model registration, table creation, migrations
4. Migrations handled in `db_manager.py` (e.g., warehouses composite unique constraint)

**Invariant you can silently break: a table targeted by `ON CONFLICT` must have exactly ONE
unique index.** All call sites write SQLite-style SQL; `dialects/_translate.py` rewrites
`ON CONFLICT(cols) DO UPDATE SET …` into MySQL's `ON DUPLICATE KEY UPDATE …` and **discards the
conflict-target column list**, because MySQL has no way to express it. SQLite fires only on the
named columns; MySQL fires on *any* unique key. So the moment a second unique index appears on
such a table, an insert that collides on the *other* key stops raising and silently UPDATEs that
row instead — on MySQL only, with no error anywhere.

Currently safe: the five UPSERT targets (`todo_items`, `notifications`, `desired_price_offers`,
`bundle_purchase_requests`, `image_embeddings`) each have exactly one unique index. `inventory`
(3 unique constraints incl. `barcode`) and `task_queue` (`client_token` + `active_dedup_key`)
have several — never convert their writes to UPSERT without restructuring first.
`_translate.py` also maps `excluded.col` → `VALUES(col)`, which MySQL 8.0.20+ deprecates.

**Startup does two destructive schema-sync passes, both gated by `db_manage/schema_guard.py`:**

- `initialize_database()` (`db_manager.py`) DROPs every table in the schema that no registered
  model declares. `get_all_tables()` is schema-wide, so this is "delete everything that isn't
  mine" — pointing the app at another application's database would wipe it.
- `_check_and_update_table_structure()` (`base_model.py`) auto-adds columns declared in
  `get_fields()` and DROPs columns that are not (both dialects implement `drop_column`).

`schema_guard.destructive_schema_allowed()` runs both **only on a test database** (and only while
`DB_DESTRUCTIVE_SCHEMA_SYNC` isn't `0`). Elsewhere they are skipped with a `system_logs` entry
rather than raising — an exception here would make the app unbootable in production. Executed drops
are logged too, so data that vanishes is always traceable.

On a test database the old behaviour still applies: removing a field from a model deletes its data
on the next startup, so any migration that needs to read a column being removed **must be
registered in the pre-model block of `init_database()`**, above the `ensure_table_exists()` loop,
not below it. Off a test database, undeclared columns/tables simply linger — harmless, since
nothing reads what `get_fields()` doesn't declare.

**Dialect traps that only bite on MySQL.** All four cost a real bug; none is caught by
`compileall`, which never executes SQL. Exercise changed SQL in its *actual* calling context.

- **`_listable_sql_expr(materialize_source=…)` must match the statement type.** `True` wraps the
  inner `inventory` in a derived table, required by `UPDATE [inventory] SET listable_quantity = …`
  because MySQL forbids re-referencing the UPDATE target inside a subquery FROM (error 1093).
  But in a **SELECT** that wrapper makes MySQL materialize before filtering, so `JSON_TABLE`
  receives rows whose `combined_items` is NULL (the vast majority) and raises 1210
  *Incorrect arguments to JSON_TABLE*. SELECT sites must pass `False`. The same applies to
  `_combined_reserved_sql_expr`; `_combined_reserved_agg_subquery` never wraps, so it is
  SELECT-safe by construction.
- **`||` is string concatenation only because `sql_mode` includes `PIPES_AS_CONCAT`**
  (set in `dialects/mysql.py` on every pooled connection). Without it MySQL reads `||` as logical
  OR and silently returns 0/1 instead of text. Don't drop it from `sql_mode`.
- **可上架 has exactly one 口径**: `max(0, 库存 − 在售 − 待出 − 组合预留 − 出品预扣减)`, defined by
  `inventory_counters._listable_sql_expr` (the stored value). Two read paths recompute it
  independently — `inventory_helpers` (库存列表) and `on_sale_items_query` (在售明细). Leave a term
  out of any one of them and the same item shows two different numbers on two pages.
- **`transactions` is an audit log, not a source of truth for stock.** Rows are written only for
  *subsequent* in/out movements — an inventory row's initial quantity never gets an `in` row, and
  splits write nothing (physically nothing enters or leaves). Deriving stock from
  `Σin − Σout` therefore yields nonsense, including negative totals. Every stock number must come
  from `inventory.quantity`.

**Decrementing stock**: always an atomic conditional UPDATE — `… SET quantity = quantity - ?
WHERE id = ? AND COALESCE(quantity,0) >= ?` plus a `rowcount <= 0` check — never a pre-check
followed by an unconditional decrement. A read-then-write pair leaves a TOCTOU window that
concurrent requests drive negative. See `_deduct_packaging_stock`, `orders_outbound/lines.py`,
`inventory_stock.py`, `inventory_split.py`.

### 商品类型映射 (`product_type_category_mappings`)

One row = one 商品类型. Each platform gets **one column holding a JSON array of button positions** —
`mercari_category_positions` / `yahoo_category_positions`, e.g. `"[2,7,1]"` — and the automation
clicks the N-th item at each level. Array length *is* the depth, so there are no fixed 1/2/3-level
columns and no per-platform cap on nesting. Adding a third marketplace = one more column + one entry
in `PLATFORM_POSITION_COLUMNS`; `ProductTypeCategoryMappingModel.positions_for(mapping_id, platform)`
is the single lookup used by the listing dispatcher.

- Mercari clicks `//*[@id="main"]/a[{pos}]` per level; Yahoo clicks the *pos*-th `li` in the bottom
  sheet. Yahoo's helper returns the label it actually hit and the level's item count — position
  clicking cannot self-validate, so that read-back is what makes a misconfiguration diagnosable
  (`位置 N 超出范围（当前层共 M 项）`).
- Empty array = not configured. Yahoo 400s up front; **Mercari silently skips category selection**
  (pre-existing asymmetry, not fixed).
- Positions have no upper bound; only ≥1 is enforced. A wrong value fails at listing time, loudly.
- `product_type` must be unique — the 库存/出品 pickers are flat single-level selects keyed on the
  name. Enforced by a save-time 400, **not** a DB unique index (legacy rows may already collide).

### Authentication Flow

1. User logs in via `POST /mercariV2/src/use_web/login/...` (username + password)
2. Backend verifies with bcrypt, creates JWT with `user_id` and `username`
3. Frontend stores token in `localStorage`
4. Axios interceptor (`api/http.js`) adds `Authorization: Bearer <token>` to all requests
5. Backend `require_auth()` dependency verifies JWT, raises 401 if expired/invalid
6. Token expiry: `JWT_EXPIRE_HOURS` env var — **default `0` = never expires** (no `exp` claim is
   written). Sessions are instead invalidated by bumping `users.token_version`, which
   `require_auth` compares on every request — changing a password, disabling an account or
   forcing a logout kills every existing token immediately. Set a positive number to also get
   time-based expiry.

CORS defaults to `allow_origins=["*"]` with **credentials disabled** — auth rides on the Bearer
header, not cookies, so the dangerous wildcard+credentials combination never occurs. Setting
`CORS_ORIGINS` to a comma-separated list locks origins down *and* enables credentials.

### Mercari Integration Pipeline

1. User adds Mercari account in Web UI → headers & cookies stored in `shop_accounts.value` (JSON)
2. `mercari_auto_fetch_loop()` runs on startup, periodically syncs orders & items
3. `use_mercari/sync/`: Mercari API client wrappers (fetch orders, items, etc.)
4. `use_mercari/on_sale/`: Incremental listing sync with local DB
5. `mgmt_id_cipher.py`: the `-=~<>` (or `◇◆`) cipher on the **last line of the item description**.
   This — and only this — is what binds a marketplace listing back to an inventory row.
   `mgmt_image_cipher.py` embeds the same id into images as a QIM watermark, but is currently
   **write-only**: `embed_mgmt_code_in_file` is called from both listing flows (and only when
   `watermark=True`), while `decode_mgmt_code_from_file` has **no callers anywhere**. Treat it as
   an unfinished feature, not part of the binding path — it costs CPU and alters every uploaded
   image for no current benefit.
6. Browser automation (`web_drive/`): Playwright for listing operations
7. SSL MITM proxy: Captures HTTP traffic to harvest tokens the public API does not expose

### Yahoo!フリマ (PayPayフリマ) Listing

`shop_accounts.platform` (`mercari` default / `yahoo`) selects the marketplace. Implemented for
Yahoo: **listing, on-sale list+detail sync, revise/suspend/resume/delete, sold-order sync +
single-order refresh + order-status batch refresh + fee backfill, auto-relist, todo sync,
notification sync, Cookie 注入, and the todo 处理 flow (trade detail / 发货 / 交易留言)** — 发货 covers
ゆうパケットポスト / mini too, via the App API (see `use_yahoo/app_api/` below). Still Mercari-only:
受取評価, the bulk todo operations (一键好评 / 一键确认发送), QR/扫码 (Yahoo has no equivalent —
its 配送コード is issued server-side, nothing to scan), and every *notification* action
(回复评论/同意降价) — Yahoo notices remain display-only.

**Every account-driven entry point dispatches on `shop_accounts.platform`** — the auto-fetch
loop, the account page's 同步数据, on-sale sync / full-update / fetch-detail (single + batch),
order sync + single-row refresh + batch status refresh, todo sync, todo 处理, and
listing/revise/suspend/delete, and Cookie 注入. Unsupported
combinations skip with a note or return a clear 400; nothing falls through to a Mercari
implementation with a Yahoo account. Note the profile key is **not** a platform hint — a Yahoo
account's main profile is also named `mercari_{id}` — so anything keyed on an `account_key` has to
resolve the platform from `shop_accounts` (see `proxy_inject.py::_platform_of`), never from the key.

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
  Two entry points, and picking the wrong one is a silent bug: `sync_yahoo_item_details` is the
  **batch** form and folds per-item failures into a stats dict, while `sync_yahoo_item_detail_one`
  is the **single-item** form that mirrors Mercari's `fetch_detail_and_sync_inventory` — same
  `{api, sync}` shape, same progress reporting, and it raises instead of swallowing. The 在售详情
  弹窗's 同步数据 button (`/fetch-detail`) needs the single-item form: fed the batch stats, the
  frontend finds no `sync` key and reports 未写入库存 on every Yahoo item, success or not.
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
  `/user/{id}` link on `/my` and written back to `shop_accounts.seller_id`. That same link also
  carries the nickname (first line of its text), which is what the account dialog's 获取基础信息
  button returns for Yahoo — **no MITM**, unlike Mercari where seller_id only exists in the
  `items/get_items` query string. Like Mercari's button it does not persist; the form saves.
  Avatar is deliberately not synced: Yahoo's profile header has no avatar `<img>`, only
  `_next/static` icons, so there is nothing safe to pick. New-account fetches run against the
  `yahoo_prepare` pre-login session, which `resolve_prepare_alias` now isolates per user the same
  way it always did for `mercari_prepare`.
- `web_drive/yahoo_item/` — revise / suspend / delete all live on one page
  (`/item/{id}/edit`, public domain — the `-sec` host 404s) whose form is identical to the listing
  form, so `post_to_yahoo._fields` is reused. Buttons: 変更する / 出品を停止する / 商品を削除する
  (a stopped item shows 出品を再開する in place of 停止する). Page primitives live in
  `units/_page.py`, the four actions in `units/item_edit.py`.
  **Success is judged by Yahoo's own rules, never Mercari's.** Mercari's 変更する leaves the edit
  page after the click; Yahoo's 停止/再開 mutate in place — the URL stays on `/edit` and only the
  button flips. (Mercari's own 一時停止/再開 behave the same way, which is why they were the two
  actions that shipped without a result check — see `web_drive/sell_edit_state.py`.)
  So `_run_edit_page_action` reloads the edit page and reads the buttons back: 停止 ⇒
  出品を再開する appears, 再開 ⇒ 出品を停止する returns, 削除 ⇒ the edit page 404s. Anything else
  **raises** — returning a `done: False` dict makes the task-queue worker record the task as
  *success*, which is exactly the "task succeeded but the listing never moved" bug. Errors carry a
  dump of the buttons actually on the page, so a Yahoo copy change is diagnosable from the task row.
  Buttons are clicked by accessible role first, then by JS first-line text (Yahoo "buttons" are not
  always `<button>`). The confirm-dialog helper only looks inside an open sheet / `[role=dialog]`
  **that does not contain the other action buttons** — the edit page's sticky action bar is itself
  `bottom: 0`, and mistaking it for the dialog re-clicks the button just pressed.
  Yahoo delete also calls `reconcile_listing_counts` itself: Mercari's delete re-runs the whole
  on-sale list sync to settle 在售 -1, but a row already soft-deleted here never re-enters the next
  sync's absent-set (`apply_on_sale_list_sync` reads via `find_all`, which excludes `is_delete=1`).
- `web_drive/core/yahoo_session.py` — same MITM + cookie-clone session as Mercari, only with
  `cookie_domains=("yahoo","paypay")`; `export_cookies_full` filters by domain, so without this the
  Yahoo session is silently logged out.
- `use_yahoo/todos/todo_sync.py` — the one Yahoo endpoint that is a clean JSON API:
  `GET /api/v1/notices/todo?result=30&offset=0` (login cookies required). Yahoo todo types map to
  their own `Yahoo*` kinds (`ooesh` → `YahooShipRequest`) rather than onto Mercari kinds — reusing
  `WaitShippingCard` etc. would make the todos page run Mercari-only ship/QR automation on a Yahoo
  row. The kind *is* listed in `_WAIT_SHIPPING_COND` so 発送依頼 lands in the 待发货 chip — and it
  must also be in `_WAIT_SHIPPING_KINDS_PY`, the Python twin used by the 期限 sort key; the two
  are documented as one 口径 and silently drifted apart once. The todo payload carries **no
  发货期限**, and `on_sale_items` is not a usable source either (an item that sold before its first
  on-sale sync has no row there at all), so the deadline is read from the **public item page** —
  `<th>発送までの日数</th><td>2〜3日で発送</td>` — by the same
  `fetch_and_store_shipping_durations` Mercari uses, dispatched on `platform=`. Unlike Mercari
  it re-tries every sync for any undeleted 発送依頼 still missing the value: Yahoo returns the
  full todo list each time and soft-deletes the rest, so the retry set is bounded by open trades.
  This naming is also what keeps 一键好评 / 一键确认发送 and Mercari's 详情预抓 off Yahoo rows for
  free — they all filter on Mercari `kind`/`title` constants that no `Yahoo*` value matches.
  **Two sync entry points, and calling the wrong one just silently does less work**:
  `sync_yahoo_todos` is the list-only form; `sync_yahoo_todos_with_details` is the twin of Mercari's
  `sync_todos_with_details` and is what every sync caller uses (待办页同步 / 账号同步数据 /
  自动获取循环) — list sync → precache each todo's trade page into `todo_items.detail_json`
  (`use_yahoo/todos/precache.py`, only the two kinds that *have* a seller trade page; an unknown
  `Yahoo:*` kind like `rsura`/商品の発送 is a **buyer**-side notice whose seller page doesn't exist)
  → on a newly-inserted 発送依頼, link-sync 在售 + 订单 once. The precache shares Mercari's
  `detail_fetch_failures` column, `PRECACHE_MAX_FAILURES` and `TXDETAIL_PRECACHE_MAX_PER_RUN`,
  because both compete for the same single global worker.
- `web_drive/yahoo_trade/` + `use_yahoo/todos/trade_actions.py` — the todo 処理 flow. The whole
  Yahoo transaction lives on one page, so this package splits by *action* (`_page` sheet/row
  primitives, `detail`, `ship`, `message`) rather than by page.
  - **发货 is one form, not a wizard**: 品名 (maxlength 17) + サイズ + 発送場所, then one button.
    That button is the state machine — it reads 「発送情報を入力してください」 and is disabled until
    all three are set, then flips to 「配送コードを表示する」. `ship.py` **verifies the flip before
    clicking** and aborts otherwise; a half-filled submit issues a 配送コード for the wrong size and
    the postage difference gets billed later. `dry_run=True` stops exactly at that check.
  - **ゆうパケットポスト / ゆうパケットポストmini are unavailable *on the web* — they ship through
    `use_yahoo/app_api` instead** (see 雅虎 App API 发货 below). Don't re-investigate the web side:
    the trade page itself says so — `※ゆうパケットポスト、ゆうパケットポストminiをご利用の場合は、
    アプリ版で発送手続きをしてください` — and the サイズ sheet simply never lists them. It is **not**
    client sniffing: probing the same trade as desktop Edge, as Android Chrome (with CDP
    `Emulation.setUserAgentOverride` so `navigator.userAgentData.mobile === true`, touch, 412px)
    and as iPhone Safari (390px) returns a byte-identical `['ゆうパケット','ゆうパケットプラス',
    'ゆうパック']`. The option list is server-rendered — it is not in the web JS bundle at all — so
    no amount of UA/viewport/Client-Hints spoofing changes it. `detail.py::_APP_ONLY_RE` still lifts
    that notice into `ship_form.app_only_note`, and the 处理 panel shows it **only when no App token
    is configured** — once the App path is available the notice would be actively misleading.
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
  - The **frontend** 处理 panel is the *same* dialog for both platforms (`views/Todos/index.vue`);
    only the 发货 section swaps to Yahoo's three-field form, keyed on `isYahoo`. That is what puts
    Yahoo on the same 关联库存 → 包材 → 出库 rails: `onSubmitYahooShip` reuses
    `validatePackagingBeforeShip` / `commitShipPackagingAndOutbound` and refuses to submit until a
    local inventory match *and* a packaging choice exist, exactly like Mercari's 発送 button. A
    separate Yahoo-only dialog (the deleted `YahooTradeDialog.vue`) shipped without ever touching
    包材 or 出库, so a Yahoo sale silently skipped both ledgers.
    "Already shipped" is `ship_form.pending === false` — Yahoo has no local QR file, so
    `isPackedDetail` can't key on `qr_image_url` the way Mercari does.
- `use_yahoo/app_api/` — **雅虎 App API 发货**（`sparkle-secure.yahooapis.jp`）。The phone app's
  backend is a real JSON API with **no client attestation** — `Authorization: Bearer` plus a few
  copied headers (`X-UUID` / `X-BCOOKIE` / `os` / `os-version` / `app-version` / `User-Agent`, all
  from `qy.IdentifierInterceptor`) is enough from this server. Used **only where the web cannot
  reach**: ゆうパケットポスト / mini shipping. Everything else stays on page automation.
  - **Endpoints** (all verified present in the APK's `zy.SparkleService` — the gateway answers a
    NestJS 404 for anything else, so guessing paths is useless):
    `GET /v2/items/{itemId}/seller` (→ `sellerId`/`buyerId`/`orderId`, `order.vendor`,
    `order.progress`, `order.isShipCodeCreated`, `order.jpYupacketPost.confirmCode`) →
    `GET /v1/items/{itemId}/jpPostMaterialCodeCheck` (→ `OK`/`SAME`/`NG`) →
    `POST /v2/items/{itemId}/shipcode` → `POST /v3/items/{itemId}/shipping`.
    `postage.method` is the `ShipMethod` enum name (`JP_YUPACKET_POST`…) and `postage.vendor` the
    `ShipVendor` name (`JAPAN_POST`); the enum ↔ 日文名 table lives in `app_api/trade.py`.
  - **発行配送コード and 発送通知 are merged into one action, by request.** Yahoo's own app guides
    「発行 → 郵便ポストに投函 → 発送通知」, and splitting them is the safer reading — merging tells the
    buyer "shipped" while the parcel is still in hand and starts their 受取期限. The operator here
    scans the code immediately before posting, so `_ship_yahoo_todo_via_app` issues the code and
    then notifies in the same call. **A failed notice never rolls back** the (irreversible) code
    issue: it returns `ship_notified: false` + `notify_error`, and the panel keeps a
    「补发发货通知」 button wired to `/yahoo/notify-shipped`, which now exists only for that retry.
    打包时间 is recorded at the code issue (same 口径 as the web path); the order status refresh
    happens after the notice, because that is when Yahoo actually moves the trade.
  - **`SAME` from the material-code check is a failure, not a warning** — that 専用箱/シール has
    already been bound to another trade, and reusing it misroutes the parcel.
  - **Login is in-app, and Yahoo has no credential API — stop looking for one.** Every
    `login_type` the SDK supports (`SSOLoginTypeDetail`: app_zerotap / app_onetap / app_deeplink /
    app_browsersync / app_login_refresh_token / …) either needs an SSO token that already exists,
    or is `webview_yconnect` — the app itself just loads `login.yahoo.co.jp/config/login` in a
    WebView and lets the user type. `/yconnect/v2/slogin` takes `token` + `snonce`, never a
    password. So `use_yahoo/app_api/oauth.py` drives the app's own **authorization** endpoint
    (`/yconnect/v2/authorization`, `response_type=code id_token`, `redirect_uri=yj-paypay-fleamarket:/`,
    PKCE S256, `display=inapp`, `sdk=7.5.0a` — all lifted from the APK's `i60.AppAuthorizationRequest`)
    and lets Yahoo render the login page. Verified: that URL 302s to
    `login.yahoo.co.jp/config/login?.src=yconnectv2&ckey=<client_id>&auth_lv=pw`.
    **An Android emulator buys nothing here** — the "Android-ness" of this flow is a UA string and
    a custom URI scheme; there is no attestation anywhere.
  - **The login browser is a separate profile (`mercari_{id}__appauth`), opened `fresh=True`.**
    That isolation *is* the "app token must not share the web session" requirement: its cookie jar
    is invisible to `__sync` / `__todo` / the main profile, and either side can be logged out
    without touching the other. `fresh` matters — a leftover session makes Yahoo skip the login
    page, so the user could never switch accounts.
  - **The code comes back in the URL *fragment*, and only the `response` event keeps it.**
    `response_type=code id_token` is the OIDC hybrid flow, so the response is fragment-encoded:
    `yj-paypay-fleamarket:/#code=…&state=…`. Chromium treats that as an unknown scheme and all
    three of `response` (Location header), `request` and `requestfailed` fire — but **`request` /
    `requestfailed` have the fragment stripped** (measured: they yield a bare
    `yj-paypay-fleamarket:/`) and usually arrive *first*. So `web_drive/yahoo_app_login.py` listens
    to all three but accepts only a URL that actually carries `code` or `error`; taking
    whichever arrives first yields an empty shell and a bogus "state 不匹配" error.
    `_parse_redirect` reads fragment *and* query for the same reason.
  - **Tokens live in `yahoo_app_tokens` (one row per account), not in `shop_accounts.value`**:
    that column is rewritten from a whitelist by `_norm_headers_dict`, which would silently drop
    them on any account edit. The login flow above is the **only** way to obtain them — there is no
    paste-a-captured-token path, because expecting a user to run a packet capture isn't a real
    workflow. Renewed automatically against
    `https://yjapp.auth.login.yahoo.co.jp/yconnect/v2/token` (`grant_type=refresh_token`, public
    client, **no secret** — see APK `m50.RefreshTokenClient`). Verified against the live endpoint:
    the access_token rotates and the expiry extends. **Refresh is lazy** — it fires from
    `_ensure_access_token` right before an App API call (or once on a 401, then retries); there is
    no background timer, so a token only renews when something actually ships.
    Yahoo *may* rotate the refresh_token too (the SDK reads one back, though an observed refresh
    returned the same one), so a refresh writes back whichever tokens the response carries and
    keeps the old refresh_token when none is returned. Refreshes are serialized per account by a
    lock that re-reads the row inside it — if Yahoo does rotate, two concurrent refreshes would
    otherwise make the loser present an already-invalidated token and report a good account as dead.
  - **The 发货 UI is the same multi-step wizard as Mercari's**, sharing one dialog
    (`shippingDialogVisible`) but its own step keys — 包材 → `ysize` (品名 + 尺寸) →
    `ylocation` *or* `yqr`. Sizes are merged: web options (read off the trade page) + the App-only
    two, the latter only when a token is configured *and* `order.vendor == JAPAN_POST` *and* the
    trade is still `WAIT_FOR_SELLER_SHIP`. **Which branch the third step takes is the same split as
    the backend's**: post-box → `yqr` → App API; the other three → `ylocation` → page automation.
    Don't reuse Mercari's `size`/`facility` steps — they read a hard-coded Mercari size table.
  - **The material code is photographed, and the shot goes to the task queue — not to a blocking
    request.** The `yqr` step reuses Mercari's capture machinery verbatim (`qrVideoEl` / `qrShot` /
    `openQrCamera` / `takeQrShot`) and, like Mercari's post-box flow, submits straight from the
    shot — no separate verify button and no confirm dialog. Submission goes to
    `POST /{todo_id}/yahoo/ship-qr` (`yahoo_ship_qr_endpoint`), which decodes the image with
    `qr_photo.decode_qr` (zxing-cpp) + `parse_material_code` **before enqueueing** (a photo that
    can't be read 400s on the spot instead of failing minutes later in a task), stores the photo,
    marks the row `ship_qr_state='shipping'`, and enqueues. `ship_via_app` still re-checks the code
    against Yahoo *before* the irreversible `POST /shipcode`.
    It deliberately reuses Mercari's **`todos.shipping_qr` task type** rather than adding a new
    one: the `ship_qr_state` reset on failure/cancel/restart (`worker.py`, `tasks_handler.py`) and
    the close-处理-dialog session guard (`_BROWSER_HOLDING_TASKS`) all key on that type, and a new
    type would have to re-register in every one of them — missing one leaves rows stuck in 发货中.
    `handle_shipping_qr` dispatches on the todo row's `platform` (read from the DB, not the
    payload) into `_run_yahoo_shipping_qr` / `_run_mercari_shipping_qr`.
    **「配送コード issued but 発送通知 failed」 is a task failure**, matching Mercari: the code is
    irreversible and the buyer hasn't been told, so a green "success" would bury it. The row goes
    back to 待发货 (`ship_qr_state='failed'`, photo kept) and the fix is the panel's 补发发货通知
    button, never a re-run (Yahoo rejects a second 発行).
  - **発送通知 success soft-deletes the todo** (`_finalize_shipped_todo`: `is_delete=1` +
    `shipped_finalized=1`), same as Mercari's `finalize_post_shipping`. Yahoo returns the full todo
    list each sync and the shipped `ooesh` disappears from it, so absence-based soft-delete would
    get there eventually — but not until the next sync, leaving a finished trade sitting in 待发货.
    `shipped_finalized=1` is what stops a sync that ran before Yahoo's list caught up from writing
    it back with `is_delete=0` (see `_upsert_todo_row`). The manual 补发 endpoint finalizes too.
  - **The QR payload is not the material code.** It reads
    `PYP:01/JT2603CAAAAAA00645638626DH62WS;` — Yahoo wants only the 30 chars in the middle.
    `parse_material_code` applies the app's own regex verbatim
    (`^PYP:[0-9]{2}/([0-9a-zA-Z]{30});$`, APK `he/o1.java`) and takes group 1; sending the whole
    string gets a flat rejection with no hint why. It is idempotent, so an already-extracted code
    passes through unchanged. Yahoo also answers a malformed code with **HTTP 400, not
    `status: NG`** — `check_material_code` folds a 400 into `NG`.
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
- **Category**: both platforms are driven by a **button-position array** — see 商品类型映射 below.
  Yahoo's tree is unrelated to Mercari's and must be drilled to a leaf; positions are relative to the
  **full tree**, so `select_category` always clicks 「他のカテゴリから選ぶ」 first (the sheet opens on a
  「カテゴリはこちらですか」 recommendation list whose length varies with the 商品名). Missing positions →
  the listing is rejected up front with a clear 400.
  **The sheet's `li` list is not the option list.** Each level is preceded by a breadcrumb trail
  (「カテゴリ一覧」 + every level already chosen), rendered as `li` just like the categories, so a
  naive `querySelectorAll('li')[pos-1]` is off by *depth* — and the offset grows one row per level,
  which is why a position array counted off the visible buttons walks correctly for a level or two
  and then silently lands on a breadcrumb row. `el.click()` on a breadcrumb `li` is a no-op (its
  handler sits on an inner element), so the level doesn't even change and the error surfaces only
  at the last position. `_CATEGORY_NTH_JS` drops the leading rows matching
  `CATEGORY_NON_OPTION_TEXTS` + the walked path — a *prefix* scan, not a global filter, so a child
  sharing an ancestor's name survives. Enumeration and clicking go through that same function, so
  the 「当前可选（按位置顺序）」 list in an error **is** the position numbering.
- **Category catalog**: a hand-maintained catalog of Yahoo leaf categories lives in table
  `yahoo_category_mappings` (id + 3 levels + leaf name + full path), served by
  `use_web/system/yahoo_category_mappings/` with server-side pagination/search because the tree is
  large. **Backend-only now** — the frontend page was removed, so nothing in the UI reads it, and
  the 商品类型映射 page never did (positions, not names, drive the automation). (Auto-scraping
  Yahoo's `/api/v1/categories/{id}/children` was tried and dropped: the endpoint returns
  intermittent 500s under any sustained crawl, so the collected tree came out badly truncated.)
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
suspend / resume; todos sync / bulk-review / bulk-confirm-ship / shipping-QR /
confirm-cancellation / send-message / send-reaction; the account
card's 同步数据 (`account.sync_data`); and 回国模式 (`system.homecoming`, see below).
**Batch revise is not a separate type** — the frontend
submits N `on_sale.revise` tasks, so closing the page no longer aborts halfway.

**The ゆうパケットポスト 扫码照片 never leaves this server.** Both platforms decode it with
zxing-cpp **at enqueue time** and carry the decoded text in `payload.qr_text`; the photo is only
kept as evidence while the row is 发货中/失败. Yahoo turns that text into the material code
(`parse_material_code`); Mercari feeds it to its own scanner page through
`wait_shipping/qr_inject.py`, in two layers, both fed by the same text:
(1) a **`BarcodeDetector` stub** installed alongside `_FAKE_CAMERA_JS` — *before* page scripts run,
via `add_init_script` + `evaluate`, because the scanner feature-detects on mount. Windows Chromium
has no native `BarcodeDetector`, so this is an addition, not an override, and whether メルカリ
actually uses it is **unverified** — `window.__qrInjectDetectCalls` is reported back as
`scan.detect_calls` precisely to settle that. Its `detect()` must resolve `[]` (never throw) before
a result is set, or the page treats it as a camera fault and ends the scan.
(2) fallback: the same text **re-encoded** into a clean QR (`qr_photo.encode_qr_data_url`) and
pushed through the existing virtual camera — deterministic where a photo could be blurred or
glared. `scan.via` records which layer won. `MERCARI_QR_INJECT_RESULT=0` disables layer 1.
Tasks queued before `qr_text` existed still fall back to feeding the original photo.
`todo_items.ship_qr_text` keeps the decoded text **even on success**, when the photo is deleted —
it is then the only local record of which code shipped.

**Anything that runs inside the todo 处理 dialog's `__todo` browser session must be registered
in `_BROWSER_HOLDING_TASKS`** (`todos_sync/actions.py::close_detail_browser`) — the frontend
closes that dialog right after enqueueing, and the close call would otherwise pull the session out
from under the pending task. The flip side: those endpoints all pass `suppress_idle_close=True`
(they were written for a multi-request HTTP flow), so with the frontend's close suppressed the
handler has to close the session itself once it's done — see `handlers/todos.py::_close_todo_browser`.
`todos.send_reaction` additionally dedups per `todo_id` for **correctness**, not just anti-double-click:
`reaction_index` counts "buyer messages with no reaction yet", so a second queued reaction would be
computed against a list the first one is about to shift.

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
  **`use_mercari/auto_relist.py` (售出即补挂) submits `inventory.listing` tasks rather than calling
  `post_to_market` itself**, precisely so its over-listing guard is this same DB-persisted
  reservation. It used to keep its own in-process dict (`_unsynced_relists`, now deleted) that
  recorded a relist only *after* the automation returned — a restart in the window between posting
  and the on-sale sync binding it lost the count and the next sale relisted the same item again.
  Anything else that wants to list must go through the queue for the same reason; there is no
  second ledger to keep in sync.
- Ordering: since the worker is FIFO, a sync task submitted after listings naturally waits for them.
  `mercari_auto_fetch_loop` additionally defers while listing tasks are queued (max 30 min).
- On restart, `running` tasks are marked failed but their listing reservations are **kept**
  (released only by the TTL sweep) — a hard crash cannot tell whether 出品する was already
  clicked, and browser automation is never auto-retried.

### 回国模式 (`src/homecoming.py`)

System 配置页的一个开关：开启后把**全部在售商品**逐件暂停出售，并在开启期间禁止任何上架；
关闭后只把**本模式暂停的那些**恢复出售。

- **"只恢复自己暂停的"落在数据库上**：暂停成功即写 `on_sale_items.homecoming_suspended=1`，
  关闭时只处理带标记的行。开启前就已是 `stop` 的商品从不打标，因此永远不会被误恢复。
  同步的 upsert (`upsert_on_sale_item_row`) 只写它自己带来的字段，不会重置这一列。
- **上架闸门只有两个开关位**，覆盖全部路径：`task_queue.submit_task`（入队时，抛
  `ValueError` → 400）与 `post_to_market`（执行时，400）。`auto_relist` 另在
  `run_auto_relist_for_orders` 开头直接返回——否则每笔售出都要写一条 error 级系统日志。
- 批量执行是**一条** `system.homecoming` 任务（不是 N 条 `on_sale.suspend`），因为限速必须由
  同一个循环控制。商品按账号分组：**组间并发**（各账号的浏览器/串行队列本就互不相干，
  `account_serial_queue` 的锁是 per-queue-key 的），**组内逐件**，每件之间随机等待
  `HOMECOMING_ITEM_DELAY_MIN_SEC` ~ `..._MAX_SEC`（默认 30/90 秒）——限速按账号计，因为被平台
  盯上的是单账号的连续快速操作。sleep 同时是取消点。注意整条任务会长时间占住全局单 worker。
- 两个方向都**幂等**：目标集合每次按当前 DB 状态重算，中途失败后再 PUT 一次同样的 `enable`
  就只处理剩下的（系统配置页的「重试」按钮）。开关先写后入队，入队失败即回滚开关。

### 一键修改发货时效 (`src/bulk_shipping_duration.py`)

系统配置页的另一个整批操作：把「平台 / 账号」范围内**全部**在售商品的 発送までの日数 改成
同一个值。和在售页的批量修改是同一件事的两个尺度（那里一次最多勾 10 件）。执行体是任务队列的
**一条** `system.shipping_duration` 任务，理由与回国模式相同——限速循环必须由同一个循环控制。

- **不含第二份平台分支**：单件走 `revise_on_sale_item`，它已按 `shop_accounts.platform` 分派
  煤炉 / 雅虎，并把煤炉的 `1/2/3` 映射成雅虎枚举。分组 / 并发 / 随机等待与回国模式同构
  （`BULK_SHIPPING_DURATION_ITEM_DELAY_MIN_SEC` ~ `..._MAX_SEC`，默认 30/90 秒，按账号计）。
- **范围含 `status='stop'`**：两个平台的编辑页在暂停出售状态下同样能改该字段，漏掉它们会让
  「一键」名不副实。拍卖商品**一起改**（与在售页批量改价禁选拍卖的口径不同，那条限制是为改价）。
- **幂等靠本地 `shipping_duration_id`**：目标集合每次只取「本地时效 ≠ 目标」的行，所以修改成功后
  必须回写本地——煤炉在 `revise_order._update_local_on_sale_item`，雅虎在
  `yahoo_item/units/item_edit.py`（原先只回写 名称/说明/价格，时效缺失，会导致每轮重跑同一批
  雅虎商品）。`shipping_from_area_id` 在雅虎侧仍未回写，改发货地区时同样会重跑。
- 件数由 `preview()` 纯 SQL 算（`pending` 含从未同步过详情、时效为空的行），前端改筛选即刷新；
  `pending=0` 时 POST 不入队直接返回。

### Auxiliary Subsystems

Three self-contained features that are easy to miss because nothing else depends on them:

- **Image search** (`use_web/inventory/image_search/`) — CLIP ViT-B/32 vision encoder, int8-quantized
  ONNX, CPU-only. The ~88MB weight file is **not in the repo**: it is downloaded on first use into
  `backend/models/` (HuggingFace, with an hf-mirror fallback for CN networks). The model is a lazy
  singleton, so not using image search costs nothing. `MODEL_NAME` is stored on each row in
  `image_embeddings` — changing the model automatically invalidates and rebuilds old vectors. A
  background thread reconciles the index at startup (`IMAGE_SEARCH_AUTO_INDEX=0` disables).
- **AI listing text** (`ai/deepseek_client.py`) — OpenAI-compatible chat completion that returns
  strict JSON `{"title", "body"}` in **Japanese**, capped at 40 / 900 chars to match the inventory
  form. API key, model, and base URL live in the `[config]` table (`ConfigEntryModel`), not in env
  vars. The default `deepseek-chat` is text-only; sending the main product image requires switching
  to a vision-capable model in the system settings page.
- **mercari-proxy** (`mercari_proxy/`) — a **Node** reverse proxy (`server.js`, derived from
  github.com/Gosoki/mercari-proxy) run as a managed subprocess on its own HTTPS port (default 9610).
  Its purpose is a genuine secure context, which Mercari's DPoP requires.
  `register_injection` pushes an account's cookies into the Node process's memory behind a one-shot
  token; the user then hits `/__boot?token=…` to have them written into their own browser.
  **It serves both marketplaces, so the upstream is per-request state, not a process constant.**
  A browser cannot be handed a cookie for a domain we don't own, so Yahoo has to land through the
  same same-origin reverse proxy as Mercari — only the upstream and the domain-rewrite regex differ.
  `server.js::SITES` holds one entry per marketplace (`host` + `reSrc`); `/__boot` writes the chosen
  key into the `__mp_site` cookie and every later request reads it back via `siteOf(req)`, because a
  root-relative `/item/xxx` carries nothing else to say which marketplace it belongs to. An unknown
  `site` on `/__inject` is a **400, never a fallback** — silently defaulting would post Yahoo cookies
  at Mercari and surface as "injected N cookies" with no login and no error. `/__boot` also expires
  every cookie already in the browser before writing the new set: leftovers from the previous account
  or marketplace otherwise compose a half-old session, and would ride along to the other upstream.
  `Secure` is attached iff the proxy is on https — without it the browser silently discards
  `__Secure-`/`__Host-` prefixed cookies, and with it (on an http fallback) it discards all of them.
  **Binding and access control are two separate things, and they must stay consistent** — the Cookie
  注入 button builds its boot URL from `window.location.hostname`, so a user browsing the SPA from
  another machine hits the proxy at the server's LAN IP. It therefore binds `0.0.0.0` and does the
  filtering in `server.js::isAllowedClient`: loopback + RFC1918/link-local/IPv6-ULA pass, **public
  sources 403** (`MERCARI_PROXY_ALLOW_LAN=0` narrows it back to this machine only). `/__inject` stays
  loopback-only on top of its `x-internal-secret`. Binding to loopback while the frontend points at a
  LAN IP was the original bug: the tab just failed to connect, with nothing in any log.
  **Binding `0.0.0.0` costs a startup check that a loopback bind gave for free.** Windows lets
  `0.0.0.0:P` coexist with an existing `127.0.0.1:P`, and routes each connection to the most specific
  bind — so a stale mercari-proxy (backend killed without `stop_proxy`) keeps loopback while the new
  process gets the LAN, and neither errors. `register_injection` goes to loopback but `/__boot` comes
  from the LAN, so the cookies land in one process's memory and the boot token is looked up in the
  other's: "injected N cookies" followed by 链接已失效 or a logged-out page. The old `EADDRINUSE`
  check can't see this (nothing exits), so `start_proxy` now handshakes `/__ping` and compares the
  answering **pid** against the process it just spawned, aborting with both pids named when they
  differ. Never assume a listening port belongs to the process you just started.
  The self-signed cert already carries every local IPv4 in its SAN (`cert.py::_local_ips`), but it is
  generated **once** — if the host's IP later changes the browser shows a name-mismatch interstitial
  that has to be clicked through, or delete `backend/data/mercari_proxy/cert.pem`+`key.pem` to
  regenerate. Accessing over a **public** hostname (nginx/domain) is not supported by this feature.

## Environment Variables

**Backend**:
- `DB_BACKEND`: Database backend — `sqlite` (default) or `mysql`. The database layer is dialect-abstracted (`src/db_manage/dialects/`); all call sites write SQLite-style SQL (`?` placeholders, `[identifier]` brackets) and the MySQL dialect translates at execution time. Switching backends requires no call-site changes. **Backend selection precedence: the UI/`system.db` setting > this env var > default `sqlite`.** The active backend is normally managed from the UI (see below), which persists it to `backend/system.db`.
- `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` / `MYSQL_POOL_SIZE`: MySQL 8.0+ connection fallback settings (used when not configured via the UI; requires `PyMySQL`). The target database is auto-created on startup when privileges allow. Migrate existing SQLite data with `python -m tools.sqlite_to_mysql` (see that script's header).

**Database management UI**: System 管理 → 系统设置 (`/system/config`, view `views/system/SystemConfig`)
lets the user choose SQLite/MySQL, test the MySQL connection, and switch backends. Switching migrates all data from the current backend to the target (`src/db_manage/migrate.py`), persists the choice + connection params to the always-SQLite bootstrap store `backend/system.db` (`src/db_manage/db_settings.py`), then auto-restarts the backend. In MySQL mode, `system.db` (SQLite) retains only this bootstrap config; all business data lives in MySQL.
- `JWT_SECRET`: Signing key (change in production)
- `JWT_EXPIRE_HOURS`: Token validity in hours. **Default `0` = never expires** — see Authentication Flow.
- `SSL_MITM_AUTO_START`: Set to `0` to disable mitmproxy (default: 1)
- `INTERACTIVE_BROWSER_AUTO_START`: Set to `0` to disable headed browser auto-start at boot (default: 0)
- `WEB_DRIVE_AUTOMATION_HEADLESS`: When enabled, all automation browsers (data fetch / startup pre-warm / MITM listing/delete/revise / mercari MITM capture) launch truly headless (silent, never shown in the foreground). Does NOT affect the manual "Open Browser" button on `/mercari-accounts` (always headed). **Default: 1 (headless).** Set to `0` to launch them headed+minimized for debugging.
- `WEB_DRIVE_MITM_MINIMIZED`: Set to `0` to keep MITM automation windows in the foreground; otherwise they are minimized to the taskbar. Default: 1. Has no effect when automation is headless (the default).
- `TASK_LISTING_RESERVATION_TTL_SEC`: How long a listing's 可上架 reservation may stay unclaimed before the task queue force-releases it and logs a warning (default 21600 = 6h). See "Task Queue" above.
- `MERCARI_ENABLE_DOCS`: Set to `1` to expose `/docs`, `/redoc`, `/openapi.json` (default: off).
- `CORS_ORIGINS`: Comma-separated allowed origins. Unset → `*` with credentials **disabled**; set → those origins with credentials enabled.
- `MERCARI_HOST` / `MERCARI_PORT`: uvicorn bind (defaults `0.0.0.0`, and `9601` in dev / `9600` when frozen).
- `MERCARI_FORWARDED_ALLOW_IPS` (default `127.0.0.1`): which peers may set `X-Forwarded-*`. uvicorn runs
  with `proxy_headers=True` and **never serves TLS itself** — HTTPS is nginx's job. There are no
  `MERCARI_SSL_*` / `MERCARI_FORCE_HTTP` variables; the frozen build no longer generates a self-signed cert.
- `MERCARI_AUTO_FETCH` / `MERCARI_AUTO_FETCH_TICK_SEC` / `MERCARI_AUTO_FETCH_INITIAL_DELAY_SEC`: Background sync loop toggle & cadence (first run is deliberately delayed ~180s to avoid contending with startup).
- `MERCARI_PROXY_AUTO_START` / `MERCARI_PROXY_PORT` / `MERCARI_PROXY_BIND_HOST` (default `0.0.0.0`) / `MERCARI_PROXY_ALLOW_LAN` (set `0` = this machine only) / `MERCARI_PROXY_UPSTREAM` / `MERCARI_PROXY_CERT_DIR`: Node reverse proxy (see Auxiliary Subsystems).
- `IMAGE_SEARCH_AUTO_INDEX` / `IMAGE_SEARCH_MODEL_URL` / `IMAGE_SEARCH_THREADS`: CLIP image-search indexing.
- `MEMORY_RECYCLE_AUTO` / `MEMORY_RECYCLE_INTERVAL_SEC` / `MEMORY_RECYCLE_MIN_RSS_MB` / `MEMORY_RECYCLE_INITIAL_DELAY_SEC`: Periodic RSS trimming (`memory_recycle.py`) — this app runs for days with a browser attached.
- `PUBLIC_RATE_LIMIT` / `PUBLIC_RATE_LIMIT_BURST` (120) / `PUBLIC_RATE_LIMIT_RPS` (20): per-IP token
  bucket on the two **unauthenticated** image endpoints (`/inventory/image-thumb`,
  `/mercari-image`). Both make the server do real work (decode + write / outbound fetch + write)
  and the server binds `0.0.0.0` with `CORS: *`. Set `PUBLIC_RATE_LIMIT=0` to disable.
  It is a small in-process bucket — real abuse protection belongs at the reverse proxy.
  **A token is spent inside the handler, only on a cache miss** — not as a router dependency,
  which runs too early to know. A cache hit just returns a file that already sits under
  `backend/imges/`, and that whole directory is mounted at `/imges` with no auth and no limit,
  so charging for it protects nothing while making the inventory **card view** (30 images per
  batch) look like abuse. Anything that adds a public endpoint doing real work must call
  `check_public_rate_limit(request)` itself, at the point where the work begins.
- `MAINTENANCE_AUTO`: Set to `0` to disable the **startup-only** cleanup pass (`maintenance.py`).
  Nothing else in this codebase reclaims anything, so without it `system_logs` (~270 rows/day),
  terminal `task_queue` rows, `detail_json` on soft-deleted todos, and the `_thumbs` /
  `_mercari_cache` image directories grow without bound. Retention/caps:
  `MAINTENANCE_SYSTEM_LOG_DAYS` (90) / `MAINTENANCE_TASK_QUEUE_DAYS` (30) /
  `MAINTENANCE_TODO_DETAIL_DAYS` (30) / `MAINTENANCE_THUMBS_MAX_MB` (512) /
  `MAINTENANCE_CDN_CACHE_MAX_MB` (256). Set any to `0` to skip that item. It runs once per boot in
  a thread (deleting files is blocking IO and must not delay `mark_ready`), never touches
  pending/running task rows, and swallows every error — cleanup must never block startup.
- `TEST_DATABASE_NAMES`: Extra comma-separated MySQL names to treat as test DBs. See Database Safety.
- `DB_DESTRUCTIVE_SCHEMA_SYNC`: Set to `0` to also skip the drop-unknown-tables / drop-undeclared-columns
  startup passes on a **test** database (they are already skipped everywhere else). See Database Safety.
- `TXDETAIL_PRECACHE_MAX_PER_RUN`: How many transaction details the post-sync precache may fetch in one
  run (default 20). Each one is a full browser page load holding the account's serial queue, so an
  unbounded backlog would block it for minutes; the rest carries over to the next tick. A todo that
  fails `PRECACHE_MAX_FAILURES` (3) times in a row leaves the candidate set entirely — without that,
  a permanently unfetchable todo is retried on *every* tick forever. Manual 刷新抓取 still works, and
  a successful fetch resets the counter.
- `MERCARI_QR_INJECT_RESULT`: Set to `0` to skip the `BarcodeDetector` result-injection layer on
  メルカリ's QR scanner page and go straight to pushing the re-encoded code. Kill switch for a hook
  into a third-party page that cannot be tested from here. See Task Queue above.
- `HOMECOMING_ITEM_DELAY_MIN_SEC` / `HOMECOMING_ITEM_DELAY_MAX_SEC` (default 30 / 90): random wait
  between two items **of the same account** in a 回国模式 batch; different accounts run in parallel
  and are not paced against each other. See 回国模式 above.
- `BULK_SHIPPING_DURATION_ITEM_DELAY_MIN_SEC` / `..._MAX_SEC` (default 30 / 90): the same per-account
  pacing for the 一键修改发货时效 batch. See 一键修改发货时效 above.
- `WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC` / `WEB_DRIVE_PROFILE_RELEASE_DELAY_SEC` / `WEB_DRIVE_PROFILES_DIR` / `WEB_DRIVE_LAUNCH_RETRY_DELAYS_SEC` / `MERCARI_BROWSER_TASK_TIMEOUT_SEC`: Playwright session lifetime, profile storage and retry tuning.
- `WEB_DRIVE_FORCE_HEADED_DEBUG`: Force **every** automation browser headed. Overrides the `WEB_DRIVE_FORCE_HEADED_DEBUG` constant at the top of `main.py`.
- `SSL_MITM_LISTEN_PORT` / `SSL_MITM_AUTO_TRUST_WINDOWS` / `MERCARI_SSL_MITM_DIR`: mitmproxy port, cert trust and working directory.
- `MERCARI_WEBSIDE_DIST` / `MERCARI_NO_STATIC`: Override or disable SPA static hosting.

**Frontend** (`webside/.env.development`):
- `MERCARI_DEV_PUBLIC_ORIGIN`: Set when nginx serves the dev server over https (e.g. `https://host`).
  **Only its scheme and port are read** — the hostname matches nothing. `wss` + that port are derived
  from it; without it an https page's `ws://` HMR socket is blocked as mixed content.
- `MERCARI_DEV_HMR_CLIENT_PORT`: Manual override for the HMR client port

## Accessing the Application

**Development**:
- Frontend: http://localhost:9600
- Backend API: http://localhost:9601
- OpenAPI docs: **disabled by default** — `/docs`, `/redoc` and `/openapi.json` return 404 unless
  `MERCARI_ENABLE_DOCS=1` (they would otherwise expose every route to an unauthenticated LAN).
  Note `start.bat` still prints a `/docs` URL; that message is stale.
- Health check: http://localhost:9601/mercariV2/health (legacy alias: `/api/health`).
  Both return **503 while starting up** and only `200 ok` once `mark_ready()` fires.

**Ports differ between dev and packaged builds**: uvicorn listens on **9601 in development** but
defaults to **9600 when frozen** (the .exe serves the API and the built SPA together, and there is
no Vite to collide with). Override with `MERCARI_PORT` / `MERCARI_HOST`.

**Network Access**: Vite and uvicorn are both bound to `0.0.0.0` — LAN access via `https://<your-ip>:9600`.

## Adding a New API Route

1. Create `backend/src/use_web/<page>/API.py` exposing `router`, with handlers in
   `backend/src/use_web/<page>/units/*.py` (keep `API.py` to routing + request models)
2. Register it in `backend/src/use_web/API.py` with
   `router.include_router(x_router, prefix="/<page>", tags=["<page>"], dependencies=_AUTH)`.
   Omit `dependencies=_AUTH` **only** for a deliberately public `public_router`.
3. Do **not** touch `main.py` — it only mounts the `/mercariV2` root router.
4. Frontend: add `webside/src/api/<page>.js`, re-export it from `api/index.js`, add the route in
   `webside/src/router/index.js`, and add strings to **all three** `i18n/locales/` files.

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
| Disable heavy startup features | `SSL_MITM_AUTO_START=0 MERCARI_PROXY_AUTO_START=0 IMAGE_SEARCH_AUTO_INDEX=0 MERCARI_AUTO_FETCH=0 python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601` |
| Syntax-check backend edits | `cd backend && python -m compileall -q src main.py` |
| Find over-length files | `find backend/src -name "*.py" -exec wc -l {} + \| sort -rn \| awk '$1>500'` |
| SQLite → MySQL migration | `cd backend && python -m tools.sqlite_to_mysql` |
| Package Windows .exe | `pyinstaller.bat` (edit `VERSION` / `BUNDLE_OCR` at the top first) |

**There is no test suite, linter, or formatter in this repo** — no pytest/ruff/eslint config, and
`npm` exposes only `dev` / `build` / `preview`. Do not invent a `npm test` or `pytest` command.
Verify backend changes with `python -m compileall` (already allow-listed in `.claude/settings.json`)
and frontend changes with `npm run build`; behavioral changes must be exercised against a running
instance. The two `backend/tools/test_*.py` files are standalone scripts, not a test framework.
`start.bat` assumes a conda env named `mercari` and runs `python main.py` (not uvicorn directly).
---

# Working Style

Behavioral guidelines to reduce common LLM coding mistakes.

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
