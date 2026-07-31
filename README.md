# FreeMarket Manager

前后端分离的本地 Web 应用，对接日本 Mercari（煤炉）账号，集 **订单同步 / 在售商品管理 / 本地库存与仓库 / 包材成本 / 待办与通知 / 一键发货** 于一体。后端通过 Playwright + mitmproxy 进行账号会话保活与请求嗅探，前端为支持中 / 日 / 英三语的 SPA。适合个人或小团队在本机或内网部署使用。

> 截图中的敏感信息（订单号、买家、金额等）已做打码处理，仅用于展示界面。

## 界面展示

### 订单管理

收益统计卡片（订单笔数 / 金额 / 手续费 / 快递费 / 包材 / 净收益）+ 订单明细表，行可展开查看出库与包材信息。

![订单管理](image/2.png)

### 库存管理

商品维度库存总览，支持 **条码入库 / 无码入库 / 图片搜索 / 组合商品**，按仓库货架、游戏分类、商品类型多维筛选。

![库存管理](image/3.png)

### 待办事项

聚合 **待发货 / 待回复** 事项，支持从煤炉同步、一键确认发送、一键好评。

![待办事项](image/1.png)

### 交易详情与消息交流

单笔交易内查看商品信息，并与买家进行站内消息交流（含默认话术回复）。

![交易详情](image/4.png)

### 一键发货

按商品尺寸选择 ゆうパケット / ゆうパック 等发货方式（含运费对照），并生成便利店（Loppi）发货二维码。

<p align="center">
  <img src="image/5.png" width="49%" alt="发货尺寸选择" />
  <img src="image/6.png" width="49%" alt="便利店发货二维码" />
</p>

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3、Vite、Vue Router、Pinia、Element Plus、vue-i18n、Axios、ZXing（条码） |
| 后端 | Python 3.11+、FastAPI、Uvicorn |
| 数据库 | SQLite（默认，`backend/mercariDB.db`，WAL 模式）/ MySQL 8.0+；自建 ORM 与方言抽象层，可在系统页切换 |
| 认证 | JWT（Bearer Token，默认 12 小时） |
| 浏览器自动化 | Playwright（Edge / Chromium） |
| 请求嗅探 | mitmproxy（默认随后端启动，可关闭） |
| OCR / 视觉 | EasyOCR、OpenCV、Pillow |
| 图片存储 | 本地目录 `backend/imges/`（前端通过 `/imges` 代理访问） |

> 推荐 Python **3.11+**，Node.js **18+**。仓库内 `start.bat` 默认使用 conda 环境 `mercari`。

## 主要功能

前端路由全部位于 [webside/src/router/index.js](webside/src/router/index.js)，对应后端蓝图见 [backend/src/use_web/API.py](backend/src/use_web/API.py)。

| 页面 | 路径 | 说明 |
|------|------|------|
| 控制台 | `/dashboard` | 概览与快捷入口 |
| 库存管理 | `/inventory` | 商品维度库存，支持条码 / 无码入库、图片搜索、组合商品 |
| 订单管理 | `/orders` | 煤炉订单同步、收益统计、出库行与包材管理 |
| 在售商品 | `/on-sale-items` | 在售商品同步与查看 |
| 待办事项 | `/todos` | 待发货 / 待回复聚合，一键确认发送 / 一键好评 |
| 煤炉通知 | `/notifications` | 同步煤炉站内通知（消息中心） |
| 煤炉账号 | `/mercari-accounts` | 账号、请求头（JSON）、卖家 ID、自动同步间隔、暂停时段等 |
| 备忘录 | `/memos` | 内置备忘 / 便签 |
| 表格管理 | `/gotion` | 自定义表格数据管理 |
| 系统总览 | `/system` | 用户管理与系统设置 |
| 库存记录 | `/system/transactions` | 出入库流水 |
| 库存包材 | `/system/cost-records` | 包材库存 |
| 包材使用记录 | `/system/cost-expenses` | 每单包材消耗 |
| 仓库管理 | `/system/warehouses` | 仓库与货架位 |
| 游戏分类 | `/system/categories` | 主数据维护 |
| 商品类型映射 | `/system/product-type-category-mappings` | Mercari 品类与本地商品类型映射 |
| 话术表 | `/system/talk-scripts` | 买家消息默认回复话术 |
| 系统日志 | `/system/system-logs` | 后端运行日志查看 |
| 数据库管理 | `/system/database` | SQLite / MySQL 切换、连接测试与数据迁移 |

## 目录结构（摘要）

```
mercari/
├── backend/
│   ├── main.py                       # FastAPI 入口（启动 MITM、自动同步、Playwright）
│   ├── requirements.txt
│   ├── mercariDB.db                  # 运行时 SQLite（业务数据）
│   ├── system.db                     # 引导配置（数据库后端选择等，恒为 SQLite）
│   ├── imges/                        # 商品 / 包材图片
│   └── src/
│       ├── API.py                    # /mercariV2 根路由
│       ├── auth.py                   # JWT 签发与校验
│       ├── app_paths.py              # 开发 / PyInstaller 路径
│       ├── mercari_auto_fetch_loop.py # 启动后周期性拉取
│       ├── system_service.py
│       ├── db_manage/                # 自建 ORM 层
│       │   ├── base_model.py
│       │   ├── database.py           # 连接池（单例，SQLite WAL）
│       │   ├── db_manager.py         # 表注册、初始化与迁移
│       │   ├── db_settings.py        # 后端选择与连接参数（写入 system.db）
│       │   ├── migrate.py            # SQLite ↔ MySQL 数据迁移
│       │   ├── dialects/             # 方言抽象（sqlite / mysql / 翻译层）
│       │   └── models/               # 各表模型（inventory / order / on_sale_item / …）
│       ├── use_web/                  # 前端页面对应的 REST 路由
│       │   ├── login/  inventory/  orders/  on_sale_items/
│       │   ├── mercari_accounts/  mercari_image/  notifications/
│       │   ├── todos/  product_types/  system/  web_drive/
│       │   └── image_storage.py
│       ├── use_mercari/              # 煤炉 API 调用 / 同步编排
│       ├── web_drive/                # Playwright 自动化（管理器、串行队列、MITM 会话）
│       └── ssl_mitm_proxy/           # mitmproxy 启停与抓包 addon
├── webside/
│   ├── package.json
│   ├── vite.config.js                # 9600 端口，HTTPS 自签名，/api 与 /imges 代理
│   └── src/
│       ├── api/                      # Axios 封装与 JWT 拦截器
│       ├── components/
│       ├── composables/  stores/  utils/  constants/
│       ├── i18n/locales/             # zh-CN / ja / en
│       ├── router/
│       └── views/                    # Dashboard、Inventory、Orders、… 及 system/*
├── image/                            # README 界面截图
├── start.bat                         # 一键拉起后端 + 前端
├── restart.bat
├── pyinstaller.bat                   # 后端 PyInstaller 打包
└── CLAUDE.md
```

## API 路径约定

后端 V2 路由统一挂在 **`/mercariV2`** 下，按「页面 / 模块」二级聚合：

```
/mercariV2/health
/mercariV2/src/use_web/<page>/<endpoint>     # 前端页面专用接口
/mercariV2/src/use_mercari/<module>/<endpoint> # 煤炉业务编排（需登录）
```

兼容性健康检查仍可访问：`/api/health`。完整接口列表见 `http://localhost:9601/docs`。

## 数据库后端（SQLite / MySQL）

默认使用 SQLite（`backend/mercariDB.db`，WAL 模式，开箱即用）。数据库层已做方言抽象（`src/db_manage/dialects/`），所有调用点均以 SQLite 风格 SQL（`?` 占位、`[标识符]` 方括号）编写，MySQL 方言在执行时翻译，切换后端**无需改动调用代码**。

- **在界面切换**：系统管理 → 数据库管理（`/system/database`）可选择 SQLite / MySQL、测试 MySQL 连接、执行切换。切换会把当前后端的数据整体迁移到目标后端（`src/db_manage/migrate.py`），并将选择与连接参数持久化到引导库 `backend/system.db`，随后自动重启后端。
- **后端选择优先级**：界面 / `system.db` 设置 > `DB_BACKEND` 环境变量 > 默认 `sqlite`。
- **MySQL 模式**：`system.db`（SQLite）仅保留引导配置，所有业务数据存于 MySQL；目标库在启动时按权限自动创建（需 `PyMySQL`）。
- **命令行迁移**：`python -m tools.sqlite_to_mysql`（详见脚本头部说明）。

## 环境变量

### 后端

| 变量 | 默认 | 说明 |
|------|------|------|
| `DB_BACKEND` | `sqlite` | 数据库后端：`sqlite` 或 `mysql`；界面 / `system.db` 设置优先级更高 |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` / `MYSQL_POOL_SIZE` | — | MySQL 连接回退设置（未通过界面配置时使用，需 `PyMySQL`） |
| `JWT_SECRET` | `CHANGE_ME_IN_PRODUCTION` | JWT 签名密钥，**生产环境必改** |
| `JWT_EXPIRE_HOURS` | `12` | Token 有效小时数 |
| `SSL_MITM_AUTO_START` | `1` | 设为 `0` 可关闭 mitmproxy 自启 |
| `INTERACTIVE_BROWSER_AUTO_START` | `0` | 设为 `1` 则启动时为所有启用账号打开有头浏览器 |
| `WEB_DRIVE_AUTOMATION_HEADLESS` | `1` | 所有自动化浏览器以 headless 运行；设 `0` 则有头 + 最小化用于调试；不影响账号页「打开浏览器」按钮 |
| `WEB_DRIVE_MITM_MINIMIZED` | `1` | MITM 自动化窗口最小化到任务栏；设 `0` 保持前台；headless 时无效 |
| `MERCARI_WEBSIDE_DIST` | — | 自定义前端构建产物目录（用于 FastAPI 内嵌挂载 SPA） |
| `MERCARI_NO_STATIC` | — | 设为 `1` 时后端不挂载 `webside/dist` |

### 前端（`webside/.env.development`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `MERCARI_DEV_HTTP` | `0` | 设为 `1` 改用纯 HTTP 启动 |
| `MERCARI_DEV_PUBLIC_HOST` | — | 远程 / 自定义域名访问时的 HMR WebSocket 主机 |
| `MERCARI_DEV_HMR_CLIENT_PORT` | `9600` | HMR 客户端端口 |

## 快速开始

### 一键启动（Windows）

仓库根目录执行：

```powershell
start.bat
```

该脚本会激活 conda 环境 `mercari`，启动后端 Uvicorn，并在 `webside` 目录执行 `npm install && npm run dev`。

### 一键启动（Mac / Linux）

仓库根目录执行：

```bash
chmod +x start.sh   # 仅首次需要
./start.sh
```

优先使用 conda 环境 `mercari`；没有 conda 时自动创建 `backend/.venv` 并安装 `backend/requirements.txt`。如需浏览器自动化功能，另行执行 `python -m playwright install msedge` 安装 Edge。

### 手动 — 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601
```

首次启动会自动建库并创建默认管理员（仅当 `users` 表为空时）：

- 用户名：`admin`
- 密码：`admin`

> 登录后请立即在「系统总览」修改密码，并设置强随机的 `JWT_SECRET`。

如不需要 mitmproxy / 自动浏览器，可禁用重型启动项以加速：

```powershell
$env:SSL_MITM_AUTO_START="0"; $env:INTERACTIVE_BROWSER_AUTO_START="0"; python -m uvicorn main:app --reload --host 0.0.0.0 --port 9601
```

### 手动 — 前端

```powershell
cd webside
npm install
npm run dev
```

开发服务器默认 **https://localhost:9600**（自签名证书，浏览器警告点「高级 → 继续访问」即可）。需要纯 HTTP：

```powershell
$env:MERCARI_DEV_HTTP="1"; npm run dev
```

`/api`、`/imges` 由 Vite 反向代理到后端 `http://localhost:9601`。

### 访问

| 说明 | 地址 |
|------|------|
| 前端（HTTPS） | https://localhost:9600 |
| 前端（HTTP） | http://localhost:9600（仅当 `MERCARI_DEV_HTTP=1`） |
| 后端健康检查 | http://localhost:9601/api/health 或 `/mercariV2/health` |
| OpenAPI / Swagger | http://localhost:9601/docs |

Vite 与 Uvicorn 均监听 `0.0.0.0`，局域网内其他设备可用 `https://<本机IP>:9600` 访问。

## 煤炉对接说明

1. 在前端 **煤炉账号** 页新建账号，填写卖家 ID、自动同步间隔、可选的暂停时段等。
2. 「打开浏览器」按钮会通过 Playwright 启动一个属于该账号的 Edge 实例（持久化 profile 在 `backend/data/web_drive_profiles/mercari_<id>/`）；首次需手动登录煤炉以获取 cookies。
3. 后端通过 mitmproxy 拦截该会话的请求，自动写回该账号的请求头（保存在 `mercari_accounts.value` 字段，JSON 格式）。
4. 设置完成后，`mercari_auto_fetch_loop` 会按账号配置的间隔自动拉取订单、在售商品、通知等数据；也可在前端手动触发同步 / 校验。
5. 同步失败时优先查看 Uvicorn 控制台日志与接口返回的 `detail`。

> 调用官方或非官方接口可能受 Mercari 条款与风控影响，请自行评估合规与账号安全风险。

## 生产部署

### 前端构建

```powershell
cd webside
npm run build
```

产物输出至 `webside/dist`。后端会在启动时自动挂载该目录为 SPA 静态文件（可用 `MERCARI_WEBSIDE_DIST` 自定义路径，或 `MERCARI_NO_STATIC=1` 关闭）。

### 后端打包

仓库提供 `pyinstaller.bat` 用于将后端打包为单一可执行文件（含 EasyOCR 等较重依赖，体积较大；首次打包前请确保 Playwright 浏览器已安装：`playwright install msedge`）。

## 添加新功能

### 新增 API 路由

1. 在 `backend/src/use_web/<page>/API.py` 中定义 `router = APIRouter()`，并实现具体端点。
2. 在 [backend/src/use_web/API.py](backend/src/use_web/API.py) 中 `include_router(...)` 注册，可选附加 `dependencies=_AUTH` 启用认证。
3. 前端在 [webside/src/api](webside/src/api) 增加对应封装，并在 [webside/src/router/index.js](webside/src/router/index.js) 中加路由。

### 新增数据表

1. 在 `backend/src/db_manage/models/` 新建模型，继承 `BaseModel`，实现 `get_table_name()` / `get_fields()`，可选 `get_indexes()`。
2. 在 [backend/src/db_manage/db_manager.py](backend/src/db_manage/db_manager.py) 中注册；后端启动时 `init_database()` 会自动建表与执行迁移。

## 依赖与注意事项

- `requirements.txt` 中含 **EasyOCR**、**Playwright**、**mitmproxy** 等较重依赖，首次安装会下载模型与浏览器二进制；不需要 OCR / 浏览器自动化时可裁剪依赖并禁用对应路由。
- Playwright 在 Windows 上默认使用 Edge；如使用其他浏览器，请先 `playwright install <browser>`。
- mitmproxy 首次运行需信任其根证书；Windows 用户可参考 [backend/src/ssl_mitm_proxy/windows_trust.py](backend/src/ssl_mitm_proxy/windows_trust.py)。
- 数据库文件位于 `backend/mercariDB.db`，建议定期备份；WAL 模式下还有 `.db-wal` / `.db-shm` 伴生文件。使用 MySQL 时，业务数据在 MySQL，`backend/system.db` 仅存引导配置。
