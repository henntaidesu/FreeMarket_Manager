<template>
  <div class="dfd-page">
    <header>
      <p class="eyebrow">System Design · Data Flow Diagram</p>
      <h1>FreeMarket Manager 数据流图（DFD）</h1>
      <p class="sub">全栈库存与订单管理系统，深度集成日本 Mercari 平台。本文档采用 Gane-Sarson 记法：第 0 层顶层图、第 1 层分解图、核心数据管道图，以及函数级调用链（DFD-3），并附数据存储与代码模块对照。</p>
      <div class="meta">
        <span class="chip">Vue 3 + Element Plus</span>
        <span class="chip">FastAPI :9601</span>
        <span class="chip">SQLite (WAL)</span>
        <span class="chip">Playwright + mitmproxy :8890</span>
        <span class="chip">2026-07-05</span>
      </div>
      <div class="callout">
        <strong>架构要点：</strong>系统<strong>不直连</strong> Mercari API。所有煤炉数据均经「Edge 自动化浏览器（克隆主 Profile 登录 Cookie）→ mitmproxy 截获 API 响应 → 原子落盘 JSON → <code>wait_mitm_capture</code> 轮询读回」这一条管道获取；DPoP 等鉴权头由浏览器前端自行生成，Python 侧不构造任何鉴权请求。详见 DFD-2。
      </div>
      <div class="legend">
        <span class="legend-item">
          <svg width="44" height="26" viewBox="0 0 44 26"><rect class="ent-box" x="2" y="2" width="40" height="22" rx="2"/></svg>
          外部实体
        </span>
        <span class="legend-item">
          <svg width="44" height="26" viewBox="0 0 44 26"><rect class="proc-box" x="2" y="2" width="40" height="22" rx="8"/></svg>
          处理过程
        </span>
        <span class="legend-item">
          <svg width="44" height="26" viewBox="0 0 44 26"><rect class="agent-box" x="2" y="2" width="40" height="22" rx="4"/></svg>
          浏览器实例
        </span>
        <span class="legend-item">
          <svg width="44" height="26" viewBox="0 0 44 26"><path class="store-shape" d="M42,2 L2,2 L2,24 L42,24"/><line class="store-div" x1="13" y1="2" x2="13" y2="24"/></svg>
          数据存储
        </span>
        <span class="legend-item">
          <svg width="52" height="26" viewBox="0 0 52 26"><defs><marker id="lgm" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="8" markerHeight="7" orient="auto"><path class="mk" d="M0,0 L10,4 L0,8 Z"/></marker></defs><path class="flow" d="M4,13 L44,13" marker-end="url(#lgm)"/></svg>
          数据流
        </span>
        <span class="legend-item">
          <svg width="52" height="26" viewBox="0 0 52 26"><defs><marker id="lgm2" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="8" markerHeight="7" orient="auto"><path class="mk" d="M0,0 L10,4 L0,8 Z"/></marker><marker id="lgm3" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="8" markerHeight="7" orient="auto-start-reverse"><path class="mk" d="M0,0 L10,4 L0,8 Z"/></marker></defs><path class="flow" d="M6,13 L44,13" marker-end="url(#lgm2)" marker-start="url(#lgm3)"/></svg>
          双向数据流（读 / 写、请求 / 响应）
        </span>
      </div>
      <div class="legend legend-io">
        <span class="legend-item"><span class="io-chip r">读 表名</span> 读 SQLite 表</span>
        <span class="legend-item"><span class="io-chip w">写 表名</span> 写 SQLite 表</span>
        <span class="legend-item"><span class="io-chip api">GET /items/…</span> 经 MITM 截获的 Mercari API</span>
        <span class="legend-item"><span class="io-chip ext">外部动作</span> 子进程 / 文件 / 页面操作</span>
      </div>
    </header>

    <!-- ================= Level 0 ================= -->
    <section>
      <h2><span class="no">DFD-0</span>顶层图（Context Diagram）</h2>
      <p class="desc">将整个系统视作单一处理过程，标出与两类外部实体之间的全部数据流：操作员通过 Web 前端使用系统；系统通过浏览器自动化与 MITM 截获同 Mercari 平台双向交换数据。</p>
      <div class="panel">
        <svg viewBox="0 0 1180 340" role="img" aria-label="第0层数据流图">
          <defs>
            <marker id="arr" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="8.5" markerHeight="7" orient="auto"><path class="mk" d="M0,0 L10,4 L0,8 Z"/></marker>
            <marker id="arrS" viewBox="0 0 10 8" refX="9" refY="4" markerWidth="8.5" markerHeight="7" orient="auto-start-reverse"><path class="mk" d="M0,0 L10,4 L0,8 Z"/></marker>
          </defs>

          <rect class="ent-box" x="50" y="125" width="150" height="90" rx="3"/>
          <text class="node-id id-ent" x="62" y="145">E1</text>
          <text class="node-name" x="125" y="172" text-anchor="middle">用户（操作员）</text>
          <text class="node-sub" x="125" y="194" text-anchor="middle">Web 浏览器 :9600</text>

          <rect class="proc-box" x="455" y="80" width="270" height="180" rx="16"/>
          <line x1="455" y1="112" x2="725" y2="112" class="proc-divider"/>
          <text class="node-id id-proc" x="470" y="101">P0</text>
          <text class="node-name" x="590" y="160" text-anchor="middle">FreeMarket Manager</text>
          <text class="node-name" x="590" y="182" text-anchor="middle">库存与订单管理系统</text>
          <text class="node-sub" x="590" y="212" text-anchor="middle">FastAPI · SQLite · Playwright</text>

          <rect class="ent-box" x="980" y="125" width="150" height="90" rx="3"/>
          <text class="node-id id-ent" x="992" y="145">E2</text>
          <text class="node-name" x="1055" y="172" text-anchor="middle">Mercari 平台</text>
          <text class="node-sub" x="1055" y="194" text-anchor="middle">API / 网页端</text>

          <path class="flow" d="M200,145 C290,145 360,118 455,118" marker-end="url(#arr)"/>
          <text class="lbl" x="325" y="112" text-anchor="middle">登录凭证 · 库存/订单操作 · 商品图片 · 出品指令</text>

          <path class="flow" d="M455,222 C360,222 290,196 200,196" marker-end="url(#arr)"/>
          <text class="lbl" x="325" y="238" text-anchor="middle">JWT 令牌 · 库存/订单清单 · 统计报表 · 通知</text>

          <path class="flow" d="M725,118 C820,118 890,145 980,145" marker-end="url(#arr)"/>
          <text class="lbl" x="855" y="112" text-anchor="middle">页面访问(带 Cookie) · 出品/改价/下架页面操作</text>

          <path class="flow" d="M980,196 C890,196 820,222 725,222" marker-end="url(#arr)"/>
          <text class="lbl" x="855" y="238" text-anchor="middle">订单 · 在售 · 待办 · 通知 JSON（MITM 截获）</text>
        </svg>
      </div>
    </section>

    <!-- ================= Level 1 ================= -->
    <section>
      <h2><span class="no">DFD-1</span>第 1 层分解图</h2>
      <p class="desc">将系统分解为 7 个处理过程与 7 个数据存储。左列过程面向操作员（Web 前端 API），右列过程面向 Mercari 平台（同步与浏览器自动化），中列为共享数据存储（SQLite 与图片文件系统）。</p>
      <div class="panel">
        <svg viewBox="0 0 1180 830" role="img" aria-label="第1层数据流图">

          <path class="flow" d="M85,300 L85,36 L880,36 L880,130" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="490" y="28" text-anchor="middle">订单查询 · 发货 / 出库处理（请求与结果）</text>

          <path class="flow" d="M85,480 L85,800 L880,800 L880,614" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="490" y="820" text-anchor="middle">出品 / 改价 / 下架指令（请求与结果）</text>

          <rect class="ent-box" x="20" y="300" width="130" height="180" rx="3"/>
          <text class="node-id id-ent" x="32" y="320">E1</text>
          <text class="node-name" x="85" y="382" text-anchor="middle">用户</text>
          <text class="node-name" x="85" y="403" text-anchor="middle">（操作员）</text>
          <text class="node-sub" x="85" y="428" text-anchor="middle">Web 前端</text>

          <rect class="ent-box" x="1030" y="300" width="130" height="180" rx="3"/>
          <text class="node-id id-ent" x="1042" y="320">E2</text>
          <text class="node-name" x="1095" y="382" text-anchor="middle">Mercari</text>
          <text class="node-name" x="1095" y="403" text-anchor="middle">平台</text>
          <text class="node-sub" x="1095" y="428" text-anchor="middle">API / 网页端</text>

          <g>
            <rect class="proc-box" x="210" y="60" width="180" height="84" rx="12"/>
            <line x1="210" y1="84" x2="390" y2="84" class="proc-divider thin"/>
            <text class="node-id id-proc" x="222" y="77">P1</text>
            <text class="node-name" x="300" y="110" text-anchor="middle">用户认证与授权</text>
            <text class="node-sub" x="300" y="130" text-anchor="middle">auth.py · JWT</text>
          </g>
          <g>
            <rect class="proc-box" x="210" y="230" width="180" height="84" rx="12"/>
            <line x1="210" y1="254" x2="390" y2="254" class="proc-divider thin"/>
            <text class="node-id id-proc" x="222" y="247">P2</text>
            <text class="node-name" x="300" y="280" text-anchor="middle">库存与仓库管理</text>
            <text class="node-sub" x="300" y="300" text-anchor="middle">use_web/inventory</text>
          </g>
          <g>
            <rect class="proc-box" x="210" y="400" width="180" height="84" rx="12"/>
            <line x1="210" y1="424" x2="390" y2="424" class="proc-divider thin"/>
            <text class="node-id id-proc" x="222" y="417">P3</text>
            <text class="node-name" x="300" y="450" text-anchor="middle">图片上传与水印处理</text>
            <text class="node-sub" x="300" y="470" text-anchor="middle">image_storage · _watermark</text>
          </g>
          <g>
            <rect class="proc-box" x="210" y="570" width="180" height="84" rx="12"/>
            <line x1="210" y1="594" x2="390" y2="594" class="proc-divider thin"/>
            <text class="node-id id-proc" x="222" y="587">P4</text>
            <text class="node-name" x="300" y="620" text-anchor="middle">辅助功能</text>
            <text class="node-sub" x="300" y="640" text-anchor="middle">memos · todos · notifications</text>
          </g>

          <g>
            <rect class="proc-box" x="790" y="130" width="180" height="84" rx="12"/>
            <line x1="790" y1="154" x2="970" y2="154" class="proc-divider thin"/>
            <text class="node-id id-proc" x="802" y="147">P5</text>
            <text class="node-name" x="880" y="180" text-anchor="middle">订单同步与管理</text>
            <text class="node-sub" x="880" y="200" text-anchor="middle">use_mercari/get_order</text>
          </g>
          <g>
            <rect class="proc-box" x="790" y="330" width="180" height="84" rx="12"/>
            <line x1="790" y1="354" x2="970" y2="354" class="proc-divider thin"/>
            <text class="node-id id-proc" x="802" y="347">P6</text>
            <text class="node-name" x="880" y="380" text-anchor="middle">在售商品同步</text>
            <text class="node-sub" x="880" y="400" text-anchor="middle">use_mercari/on_sale · sync</text>
          </g>
          <g>
            <rect class="proc-box" x="790" y="530" width="180" height="84" rx="12"/>
            <line x1="790" y1="554" x2="970" y2="554" class="proc-divider thin"/>
            <text class="node-id id-proc" x="802" y="547">P7</text>
            <text class="node-name" x="880" y="580" text-anchor="middle">出品 / 改价 / 下架自动化</text>
            <text class="node-sub" x="880" y="600" text-anchor="middle">web_drive · ssl_mitm_proxy</text>
          </g>

          <g>
            <path class="store-shape" d="M690,80 L490,80 L490,126 L690,126"/>
            <line class="store-div" x1="526" y1="80" x2="526" y2="126"/>
            <text class="node-id id-store" x="508" y="107" text-anchor="middle">D1</text>
            <text class="node-name" x="540" y="100">users 用户</text>
            <text class="node-sub" x="540" y="118">SQLite · pbkdf2 口令</text>
          </g>
          <g>
            <path class="store-shape" d="M690,190 L490,190 L490,236 L690,236"/>
            <line class="store-div" x1="526" y1="190" x2="526" y2="236"/>
            <text class="node-id id-store" x="508" y="217" text-anchor="middle">D2</text>
            <text class="node-name" x="540" y="210">inventory 库存</text>
            <text class="node-sub" x="540" y="228">warehouses · transactions</text>
          </g>
          <g>
            <path class="store-shape" d="M690,300 L490,300 L490,346 L690,346"/>
            <line class="store-div" x1="526" y1="300" x2="526" y2="346"/>
            <text class="node-id id-store" x="508" y="327" text-anchor="middle">D3</text>
            <text class="node-name" x="540" y="320">orders 订单</text>
            <text class="node-sub" x="540" y="338">outbound_lines · cost_*</text>
          </g>
          <g>
            <path class="store-shape" d="M690,410 L490,410 L490,456 L690,456"/>
            <line class="store-div" x1="526" y1="410" x2="526" y2="456"/>
            <text class="node-id id-store" x="508" y="437" text-anchor="middle">D4</text>
            <text class="node-name" x="540" y="430">on_sale_items 在售</text>
            <text class="node-sub" x="540" y="448">Mercari 在售商品记录</text>
          </g>
          <g>
            <path class="store-shape" d="M690,520 L490,520 L490,566 L690,566"/>
            <line class="store-div" x1="526" y1="520" x2="526" y2="566"/>
            <text class="node-id id-store" x="508" y="547" text-anchor="middle">D5</text>
            <text class="node-name" x="540" y="540">mercari_accounts</text>
            <text class="node-sub" x="540" y="558">开关 · seller_id · 抓取间隔</text>
          </g>
          <g>
            <path class="store-shape" d="M690,630 L490,630 L490,676 L690,676"/>
            <line class="store-div" x1="526" y1="630" x2="526" y2="676"/>
            <text class="node-id id-store" x="508" y="657" text-anchor="middle">D6</text>
            <text class="node-name" x="540" y="650">imges/ 图片文件</text>
            <text class="node-sub" x="540" y="668">本地文件系统</text>
          </g>
          <g>
            <path class="store-shape" d="M690,720 L490,720 L490,766 L690,766"/>
            <line class="store-div" x1="526" y1="720" x2="526" y2="766"/>
            <text class="node-id id-store" x="508" y="747" text-anchor="middle">D7</text>
            <text class="node-name" x="540" y="740">辅助数据</text>
            <text class="node-sub" x="540" y="758">memos · todos · notifications</text>
          </g>

          <path class="flow" d="M150,310 C185,310 175,94 210,94" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="88" text-anchor="end">登录凭证</text>
          <path class="flow" d="M210,118 C175,118 185,332 150,332" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="133" text-anchor="end">JWT 令牌</text>

          <path class="flow" d="M150,354 C185,354 175,258 210,258" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="252" text-anchor="end">库存 / 出入库操作</text>
          <path class="flow" d="M210,286 C175,286 185,376 150,376" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="301" text-anchor="end">库存清单 · 统计</text>

          <path class="flow" d="M150,398 C185,398 175,428 210,428" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="422" text-anchor="end">商品图片</text>
          <path class="flow" d="M210,456 C175,456 185,420 150,420" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="471" text-anchor="end">图片 URL</text>

          <path class="flow" d="M150,442 C185,442 175,598 210,598" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="592" text-anchor="end">备忘 / 待办录入</text>
          <path class="flow" d="M210,626 C175,626 185,464 150,464" marker-end="url(#arr)"/>
          <text class="lbl" x="204" y="641" text-anchor="end">通知 · 提醒</text>

          <path class="flow" d="M390,102 L490,102" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="440" y="95" text-anchor="middle">用户记录</text>

          <path class="flow" d="M390,272 C435,272 450,213 490,213" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="443" y="238" text-anchor="middle">库存记录</text>

          <path class="flow" d="M390,442 C445,442 440,653 490,653" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="438" y="548" text-anchor="middle">图片文件 存 / 取</text>

          <path class="flow" d="M390,612 C445,612 440,743 490,743" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="438" y="690" text-anchor="middle">备忘 / 待办 / 通知</text>

          <path class="flow" d="M790,150 C748,150 740,220 690,220" marker-end="url(#arr)"/>
          <text class="lbl" x="742" y="172" text-anchor="middle">库存核销</text>

          <path class="flow" d="M790,172 C745,172 740,316 690,316" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="742" y="252" text-anchor="middle">订单记录 写入 / 查询</text>

          <path class="flow" d="M690,530 C745,530 748,198 790,198" marker-end="url(#arr)"/>
          <text class="lbl" x="782" y="217" text-anchor="end">账号 · seller_id</text>

          <path class="flow" d="M790,358 C748,358 745,426 690,426" marker-end="url(#arr)" marker-start="url(#arrS)"/>
          <text class="lbl" x="742" y="384" text-anchor="middle">在售商品记录</text>

          <path class="flow" d="M690,543 C745,543 748,386 790,386" marker-end="url(#arr)"/>
          <text class="lbl" x="782" y="404" text-anchor="end">账号 · seller_id</text>

          <path class="flow" d="M790,542 C748,542 745,440 690,440" marker-end="url(#arr)"/>
          <text class="lbl" x="742" y="480" text-anchor="middle">在售记录更新</text>

          <path class="flow" d="M690,556 C742,556 748,558 790,558" marker-end="url(#arr)"/>
          <text class="lbl" x="740" y="551" text-anchor="middle">账号 · seller_id</text>

          <path class="flow" d="M690,646 C742,646 748,574 790,574" marker-end="url(#arr)"/>
          <text class="lbl" x="742" y="628" text-anchor="middle">水印图片</text>

          <path class="flow" d="M690,206 C752,206 752,590 790,590" marker-end="url(#arr)"/>
          <text class="lbl" x="766" y="618" text-anchor="middle">商品资料</text>

          <path class="flow" d="M1030,330 C1000,330 1006,158 970,158" marker-end="url(#arr)"/>
          <text class="lbl" x="1024" y="323" text-anchor="end">订单/交易 JSON（MITM）</text>
          <path class="flow" d="M970,186 C1006,186 1000,352 1030,352" marker-end="url(#arr)"/>
          <text class="lbl" x="1024" y="369" text-anchor="end">打开交易页（浏览器）</text>

          <path class="flow" d="M1030,378 C1004,378 1002,362 970,362" marker-end="url(#arr)"/>
          <text class="lbl" x="1024" y="395" text-anchor="end">在售列表 JSON（MITM）</text>
          <path class="flow" d="M970,390 C1002,390 1004,400 1030,400" marker-end="url(#arr)"/>
          <text class="lbl" x="1024" y="418" text-anchor="end">打开在售列表页</text>

          <path class="flow" d="M970,558 C1006,558 1000,424 1030,424" marker-end="url(#arr)"/>
          <text class="lbl" x="1024" y="448" text-anchor="end">页面操作（Playwright）</text>
          <path class="flow" d="M1030,446 C1000,446 1006,586 970,586" marker-end="url(#arr)"/>
          <text class="lbl" x="1024" y="473" text-anchor="end">操作结果 · 页面响应</text>
        </svg>
      </div>
      <p class="note">控制流说明：P5 / P6 及待办、通知同步由后台任务 <code>mercari_auto_fetch_loop</code>（初始延迟 180s，tick 60s，各账号各项独立间隔，默认 30 分钟）定时触发。登录态不存于数据库：由用户在有头主浏览器 Profile 中手动登录维持，自动化时按需只读克隆 Cookie（见 DFD-2）。同账号所有自动化经 <code>account_serial_queue</code> 串行执行。</p>
    </section>

    <!-- ================= DFD-2 核心数据管道 ================= -->
    <section>
      <h2><span class="no">DFD-2</span>核心数据管道：浏览器 + MITM 截获</h2>
      <p class="desc">P5/P6/P7 及待办、通知同步全部复用这一条管道。mitmproxy 的 addon 与后端进程之间通过磁盘 JSON 文件解耦：addon 跑在 mitmdump 子进程内截获 <code>api.mercari.jp</code> 的响应并原子落盘，后端轮询读回。</p>
      <div class="panel">
        <svg viewBox="0 0 1180 660" role="img" aria-label="MITM 数据获取管道">

          <!-- A 主 Profile -->
          <rect class="agent-box" x="40" y="40" width="250" height="100" rx="6"/>
          <text class="node-name" x="165" y="78" text-anchor="middle">主浏览器 Profile</text>
          <text class="node-sub" x="165" y="98" text-anchor="middle">mercari_{id} · 有头 Edge</text>
          <text class="node-sub" x="165" y="116" text-anchor="middle">用户手动登录，维持 Cookie</text>

          <!-- B 自动化浏览器 -->
          <rect class="agent-box" x="40" y="300" width="250" height="130" rx="6"/>
          <text class="node-name" x="165" y="336" text-anchor="middle">自动化 Edge Profile</text>
          <text class="node-sub" x="165" y="358" text-anchor="middle">__sync 同步/改价/下架</text>
          <text class="node-sub" x="165" y="376" text-anchor="middle">__listing 出品 · __todo 待办</text>
          <text class="node-sub" x="165" y="400" text-anchor="middle">无头 · 经代理启动</text>

          <!-- A→B cookie 克隆 -->
          <path class="flow" d="M165,140 L165,300" marker-end="url(#arr)"/>
          <text class="lbl" x="176" y="212">clone_main_profile_cookies</text>
          <text class="lbl" x="176" y="228">mitm_session.py:278 · 只读克隆 Cookie</text>

          <!-- C mitmproxy -->
          <rect class="proc-box" x="390" y="300" width="260" height="130" rx="12"/>
          <line x1="390" y1="330" x2="650" y2="330" class="proc-divider thin"/>
          <text class="node-id id-proc" x="402" y="321">代理</text>
          <text class="node-name" x="520" y="360" text-anchor="middle">mitmproxy :8890</text>
          <text class="node-sub" x="520" y="382" text-anchor="middle">mitmdump 子进程 runner.py:115</text>
          <text class="node-sub" x="520" y="400" text-anchor="middle">mitm_addon · MercariCapture</text>

          <!-- D Mercari -->
          <rect class="ent-box" x="900" y="40" width="240" height="110" rx="3"/>
          <text class="node-id id-ent" x="912" y="60">E2</text>
          <text class="node-name" x="1020" y="92" text-anchor="middle">Mercari 平台</text>
          <text class="node-sub" x="1020" y="114" text-anchor="middle">api.mercari.jp · jp.mercari.com</text>

          <!-- B→C / C→B -->
          <path class="flow" d="M290,345 L390,345" marker-end="url(#arr)"/>
          <text class="lbl" x="340" y="337" text-anchor="middle">HTTPS 请求</text>
          <path class="flow" d="M390,398 L290,398" marker-end="url(#arr)"/>
          <text class="lbl" x="340" y="415" text-anchor="middle">页面 / 响应</text>

          <!-- C→D / D→C -->
          <path class="flow" d="M650,330 C790,330 900,210 990,150" marker-end="url(#arr)"/>
          <text class="lbl" x="815" y="255" text-anchor="middle">转发请求（Cookie / DPoP 由浏览器自带）</text>
          <path class="flow" d="M935,150 C830,240 770,368 650,368" marker-end="url(#arr)"/>
          <text class="lbl" x="790" y="330" text-anchor="middle">响应 JSON</text>

          <!-- F JSON 落盘 -->
          <path class="store-shape" d="M1000,470 L720,470 L720,540 L1000,540"/>
          <line class="store-div" x1="758" y1="470" x2="758" y2="540"/>
          <text class="node-id id-store" x="739" y="509" text-anchor="middle">F</text>
          <text class="node-name" x="772" y="498">~/.mercari/ssl_mitm/*.json</text>
          <text class="node-sub" x="772" y="520">按 seller_id / item_id 分文件 · capture_config</text>

          <!-- C→F 落盘 -->
          <path class="flow" d="M600,430 C660,430 660,505 720,505" marker-end="url(#arr)"/>
          <text class="lbl" x="648" y="472" text-anchor="middle">MercariCapture.response</text>
          <text class="lbl" x="648" y="488" text-anchor="middle">仅 200 · 原子落盘</text>

          <!-- G 业务同步代码 -->
          <rect class="proc-box" x="390" y="520" width="260" height="110" rx="12"/>
          <line x1="390" y1="548" x2="650" y2="548" class="proc-divider thin"/>
          <text class="node-id id-proc" x="402" y="540">核心封装</text>
          <text class="node-name" x="520" y="576" text-anchor="middle">mitm_automation_browser</text>
          <text class="node-name" x="520" y="596" text-anchor="middle">wait_mitm_capture</text>
          <text class="node-sub" x="520" y="616" text-anchor="middle">mitm_session.py:341 / 443</text>

          <!-- F→G 轮询读取 -->
          <path class="flow" d="M720,528 C690,528 686,568 650,568" marker-end="url(#arr)"/>
          <text class="lbl" x="700" y="562" text-anchor="middle">轮询 read_*_response</text>

          <!-- G→B 控制 -->
          <path class="flow" d="M440,520 C440,470 165,486 165,430" marker-end="url(#arr)"/>
          <text class="lbl" x="300" y="472" text-anchor="middle">打开页面 · 周期 reload_active_tab 重触发 API</text>

          <!-- H SQLite -->
          <path class="store-shape" d="M300,540 L40,540 L40,610 L300,610"/>
          <line class="store-div" x1="78" y1="540" x2="78" y2="610"/>
          <text class="node-id id-store" x="59" y="579" text-anchor="middle">DB</text>
          <text class="node-name" x="92" y="570">SQLite mercariDB.db</text>
          <text class="node-sub" x="92" y="592">orders · on_sale_items · todo_items …</text>

          <!-- G→H -->
          <path class="flow" d="M390,588 C350,588 340,575 300,575" marker-end="url(#arr)"/>
          <text class="lbl" x="345" y="568" text-anchor="middle">解析后写入</text>
        </svg>
      </div>
      <p class="note">会话生命周期：<code>mitm_automation_browser</code>（异步上下文）复用存活的 <code>__sync</code> 会话，仅 <code>reload_active_tab</code> 导航目标页；退出时<strong>不关浏览器</strong>，由 <code>account_serial_queue._delayed_close_browser</code>（account_serial_queue.py:97）在队列空闲 10s 后延迟关闭。出品用的 <code>listing_automation_browser</code> 相反——fresh 启动、用完立即 <code>close_session(force=True)</code>。若页面跳转到登录页，<code>_detect_login_redirect_and_disable</code>（mitm_session.py:198）停用账号并抛 <code>MercariLoginRequiredError</code>。</p>
    </section>

    <!-- ================= DFD-3 函数级调用链 ================= -->
    <section>
      <h2><span class="no">DFD-3</span>函数级调用链</h2>
      <p class="desc">每条链从入口（FastAPI 路由 / 后台循环）出发，展开到 DB 模型方法或 MITM 截获的 Mercari API 为止。节点后标注 <code>文件:行号</code> 与数据读写。</p>

      <div v-for="c in chains" :key="c.id" class="chain-block">
        <h3><span class="no">{{ c.id }}</span>{{ c.title }}</h3>
        <p v-if="c.desc" class="desc">{{ c.desc }}</p>
        <div class="panel chain-panel">
          <CallTree :nodes="c.tree" :root="true" />
        </div>
      </div>
    </section>

    <!-- ================= 数据存储对照 ================= -->
    <section>
      <h2><span class="no">附录 A</span>数据存储对照表</h2>
      <p class="desc">全部结构化数据位于单一 SQLite 数据库 <code>backend/mercariDB.db</code>（WAL 模式），图片以文件形式存放。</p>
      <div class="panel panel-table">
        <table>
          <thead><tr><th>编号</th><th>存储名</th><th>内容</th><th>实际存储</th></tr></thead>
          <tbody>
            <tr><td><span class="tag d">D1</span></td><td>用户</td><td>账号、pbkdf2 密码散列、权限</td><td><code>users</code></td></tr>
            <tr><td><span class="tag d">D2</span></td><td>库存</td><td>商品、条码/SKU、价格、数量、仓库货架、出入库流水</td><td><code>inventory</code> · <code>warehouses</code> · <code>transactions</code> · <code>product_types</code></td></tr>
            <tr><td><span class="tag d">D3</span></td><td>订单</td><td>Mercari 订单、出库行项目、包材成本</td><td><code>orders</code> · <code>order_outbound_lines</code> · <code>cost_records</code> · <code>cost_expenses</code></td></tr>
            <tr><td><span class="tag d">D4</span></td><td>在售商品</td><td>从 Mercari 同步的在售商品记录、期望价 offer</td><td><code>on_sale_items</code> · <code>desired_price_offers</code></td></tr>
            <tr><td><span class="tag d">D5</span></td><td>Mercari 账号</td><td>账号配置、开关、seller_id、抓取间隔与节流时间戳（登录态在浏览器 Profile，不入库）</td><td><code>mercari_accounts</code></td></tr>
            <tr><td><span class="tag d">D6</span></td><td>图片文件</td><td>商品原图、缩略图缓存、煤炉图片缓存；水印图为出品时临时生成</td><td><code>backend/imges/</code>（文件系统）</td></tr>
            <tr><td><span class="tag d">D7</span></td><td>辅助数据</td><td>备忘、待办、通知、交易消息、话术、Gotion 表格、系统日志</td><td><code>memos</code> · <code>todo_items</code> · <code>notifications</code> · <code>transaction_messages</code> · <code>talk_scripts</code> · <code>gotion_*</code> · <code>system_logs</code></td></tr>
            <tr><td><span class="tag d">F</span></td><td>MITM 截获文件</td><td>mitm_addon 落盘的 API 响应 JSON（进程间解耦介质）</td><td><code>~/.mercari/ssl_mitm/*.json</code></td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ================= 处理过程对照 ================= -->
    <section>
      <h2><span class="no">附录 B</span>处理过程对照表</h2>
      <p class="desc">各处理过程对应的后端代码模块（均位于 <code>backend/src/</code> 下），API 前缀为 <code>/mercariV2/src/</code>。</p>
      <div class="panel panel-table">
        <table>
          <thead><tr><th>编号</th><th>处理过程</th><th>职责</th><th>代码模块</th></tr></thead>
          <tbody>
            <tr><td><span class="tag p">P1</span></td><td>用户认证与授权</td><td>登录校验、签发/验证 JWT（HS256，默认 168 小时）</td><td><code>auth.py</code> · <code>use_web/login</code></td></tr>
            <tr><td><span class="tag p">P2</span></td><td>库存与仓库管理</td><td>商品 CRUD、条码/SKU、组合/拆分、出入库流水与级联</td><td><code>use_web/inventory</code> · <code>use_mercari/inventory_counters.py</code></td></tr>
            <tr><td><span class="tag p">P3</span></td><td>图片上传与水印处理</td><td>图片落盘、EXIF 方向修正、出品水印、煤炉图片代理缓存</td><td><code>use_web/image_storage.py</code> · <code>web_drive/listing/…/_watermark.py</code></td></tr>
            <tr><td><span class="tag p">P4</span></td><td>辅助功能</td><td>备忘、待办、通知、话术、Gotion 表格</td><td><code>use_web/memos</code> · <code>use_web/todos</code> · <code>use_web/notifications</code> 等</td></tr>
            <tr><td><span class="tag p">P5</span></td><td>订单同步与管理</td><td>增量/全量拉取订单与交易详情、发货出库、库存核销</td><td><code>use_mercari/get_order</code> · <code>use_mercari/sync</code></td></tr>
            <tr><td><span class="tag p">P6</span></td><td>在售商品同步</td><td>增量同步在售商品，解析描述中的管理编号密文并回绑库存</td><td><code>use_mercari/on_sale</code> · <code>mgmt_id_cipher.py</code></td></tr>
            <tr><td><span class="tag p">P7</span></td><td>出品 / 改价 / 下架自动化</td><td>Playwright 驱动 Edge + MITM，执行出品、改价、下架、暂停/恢复、自动补挂</td><td><code>web_drive/</code> · <code>ssl_mitm_proxy/</code> · <code>use_mercari/auto_relist.py</code></td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer>FreeMarket Manager · DFD v2.0（含函数级调用链） · 依据 backend/src 实际代码结构绘制 · 2026-07-05</footer>
  </div>
</template>

<script setup>
import CallTree from './CallTree.vue'

// io 类型:r=读表 w=写表 api=经 MITM 截获的 Mercari API ext=外部动作(子进程/文件/页面)
const chains = [
  {
    id: 'C1',
    title: '系统启动与关闭（lifecycle）',
    desc: '由 main.py:50 注册;全部步骤完成后 mark_ready(),健康检查才由 503 转 ok。',
    tree: [
      { tag: '启动', fn: '_on_startup', loc: 'lifecycle.py:33', children: [
        { fn: 'start_mitm_proxy', loc: 'ssl_mitm_proxy/runner.py:115', note: 'mitmdump 子进程,监听 :8890;frozen 时 backend.exe 自调充当 mitmdump', io: [{ t: 'ext', x: '子进程' }] },
        { fn: 'start_proxy', loc: 'mercari_proxy', note: 'Node 反向代理(前端 Cookie 注入用,与自动化链路无关)' },
        { fn: 'init_database', loc: 'db_manage/db_manager.py:680', children: [
          { fn: 'initialize_database', loc: 'db_manager.py:579', note: '表重命名/字段迁移 → 25 个模型 ensure_table_exists → 后置迁移', io: [{ t: 'w', x: '全部表 DDL' }] }
        ] },
        { fn: 'start_indexer', loc: 'inventory/image_search', note: 'CLIP 图片索引线程(IMAGE_SEARCH_AUTO_INDEX 时)' },
        { tag: '循环', fn: 'mercari_auto_fetch_loop', loc: 'mercari_auto_fetch_loop.py:306', note: 'asyncio.create_task,首跑延迟 180s → 见 C2' },
        { fn: 'memory_recycle_loop', loc: 'memory_recycle.py:67', note: 'gc.collect + Windows 工作集裁剪(可选)' },
        { fn: 'startup_interactive_browsers_for_all_active_accounts', loc: 'interactive_browser.py:62', note: '为 active 账号打开有头主浏览器(默认关闭)' },
        { fn: 'mark_ready', loc: 'readiness.py:14', note: '就绪标记的唯一设置点' }
      ] },
      { tag: '关闭', fn: '_on_shutdown', loc: 'lifecycle.py:106', children: [
        { fn: 'shutdown_queue / shutdown_serial_executors', loc: 'account_serial_queue.py:193 / 211', note: '取消延迟关闭任务、清空队列注册表' },
        { fn: 'get_web_drive_manager().shutdown', loc: 'manager/_mixin_lifecycle.py:176', note: '关闭全部 Edge 会话' },
        { fn: 'stop_mitm_proxy / stop_proxy', loc: 'runner.py:194' }
      ] }
    ]
  },
  {
    id: 'C2',
    title: '定时抓取循环（mercari_auto_fetch_loop）',
    desc: 'tick 60s;每账号每项独立间隔(默认 30 分钟)与节流时间戳,固定顺序 order_list → on_sale → todos → notifications。',
    tree: [
      { tag: '循环', fn: 'mercari_auto_fetch_loop', loc: 'mercari_auto_fetch_loop.py:306', children: [
        { fn: 'run_mercari_auto_fetch_tick', loc: ':204', children: [
          { fn: 'MercariAccountModel.find_all', note: 'is_open=1 且 status=active', io: [{ t: 'r', x: 'mercari_accounts' }] },
          { fn: '_due_tasks / _account_in_pause_window', loc: ':121 / :89', note: '按 auto_fetch_<key>_interval 与 last_at 判到期;暂停窗内跳过' },
          { fn: 'sync_lock_try_begin("auto")', loc: 'sync/sync_lock.py:41', note: '用户手动同步进行中则本轮跳过' },
          { fn: '_run_auto_fetch_for_account', loc: ':134', note: '在该账号串行队列内按固定顺序执行到期项', children: [
            { fn: 'sync_new_data', loc: 'sync/sync_data.py:156', note: 'order_list 项 → 见 C3' },
            { fn: 'sync_on_sale_items_from_mercari', loc: 'on_sale_items_sync/sync.py:136', note: 'on_sale 项 → 见 C5' },
            { fn: 'sync_todos_with_details', loc: 'todolist_sync.py:283', note: 'todos 项 → 见 C6' },
            { fn: 'sync_notifications_from_mercari', loc: 'notification_sync.py:258', note: 'notifications 项 → 见 C6' }
          ] },
          { fn: '_mark_task_last_at', loc: ':191', note: '仅更新真正成功的项;失败项下个 tick 重试', io: [{ t: 'w', x: 'mercari_accounts' }, { t: 'w', x: 'system_logs' }] }
        ] }
      ] }
    ]
  },
  {
    id: 'C3',
    title: 'P5 · 订单增量同步（sync_new_data）',
    desc: '入口:POST /use_mercari/sync-new-data(订单页「更新列表」)或 C2 定时触发。',
    tree: [
      { tag: 'POST', fn: 'api_sync_new_data', loc: 'use_mercari/API.py:57', children: [
        { fn: 'resolve_enabled_account_ids', loc: 'sync/sync_data.py:42', io: [{ t: 'r', x: 'mercari_accounts' }] },
        { fn: 'begin_or_conflict', loc: 'sync/sync_lock.py:54', note: '进程内全局同步锁' },
        { fn: 'run_mercari_serial_async → sync_new_data', loc: 'sync/sync_data.py:156', note: '每账号入串行队列', children: [
          { fn: '_resolve_account_and_seller', loc: ':54', io: [{ t: 'r', x: 'mercari_accounts' }] },
          { fn: 'fetch_open_order_items', loc: 'get_order_list.py:165', children: [
            { fn: '_fetch_trading_list_via_browser_impl', loc: ':50', children: [
              { fn: 'mitm_automation_browser + wait_mitm_capture', loc: 'mitm_session.py:341 / 443', io: [{ t: 'api', x: 'GET /items/get_items?status=trading' }] }
            ] }
          ] },
          { fn: '_item_to_order_data → _upsert_order', loc: 'get_order_list.py:108 / 131', note: '按 order_no 去重后插入/更新', io: [{ t: 'w', x: 'orders' }] },
          { fn: 'apply_item_info_to_order', loc: 'get_order_info.py:378', note: '每条新订单补交易详情', children: [
            { fn: 'fetch_item_info → _fetch_item_info_via_browser_impl', loc: ':211 / :103', io: [{ t: 'api', x: 'GET /transaction_evidences/get' }] },
            { fn: 'extract_order_info_fields', loc: ':231', note: '手续费 / 净收益 / 运费计算' },
            { fn: 'deduct_packaging_total_from_order_net_income', loc: 'use_web/system/cost_expenses', io: [{ t: 'r', x: 'cost_expenses' }] },
            { fn: 'OrderModel.save', io: [{ t: 'w', x: 'orders' }] },
            { fn: 'sync_outbound_lines_for_order', loc: 'outbound_sync.py:79', io: [{ t: 'w', x: 'order_outbound_lines' }] }
          ] },
          { fn: '_mark_order_cancelled', loc: 'get_order_info.py:353', note: '截获到取引取消拦截页时', children: [
            { fn: 'restock_order_holding_lines + refresh_inventory_pending_outbound_qty', loc: 'orders_outbound/lines.py:26 · outbound_sync.py:13', note: '回吐占用', io: [{ t: 'w', x: 'inventory' }, { t: 'w', x: 'order_outbound_lines' }] }
          ] },
          { fn: 'run_auto_relist_for_orders', loc: 'auto_relist.py:92', note: '有新售出时自动补挂 → 见 C9' }
        ] }
      ] }
    ]
  },
  {
    id: 'C4',
    title: 'P5 · 历史全量同步与批量状态刷新',
    tree: [
      { tag: 'POST', fn: 'sync_orders', loc: 'use_mercari/API.py:197', note: '/sync-orders「获取历史数据」;已有数据则拒绝', children: [
        { fn: 'sync_open_orders', loc: 'sync/sync_data.py:112', children: [
          { fn: 'OrderModel.count(data_user)', note: '预检:该账号已有订单则中止', io: [{ t: 'r', x: 'orders' }] },
          { fn: 'fetch_and_sync_open_orders', loc: 'get_order_list.py:184', io: [{ t: 'api', x: 'GET /items/get_items?status=trading' }, { t: 'w', x: 'orders' }] },
          { fn: 'fetch_and_sync_history_orders', loc: 'get_history_list.py:94', children: [
            { fn: 'fetch_history_order_items → _fetch_sold_out_list_via_browser_impl', loc: ':75 / :37', io: [{ t: 'api', x: 'GET /items/get_items?status=sold_out' }] },
            { fn: '_upsert_order + apply_item_info_to_order', note: '同 C3', io: [{ t: 'w', x: 'orders' }] }
          ] }
        ] }
      ] },
      { tag: 'POST', fn: 'api_batch_refresh_info', loc: 'use_mercari/API.py:123', note: '/batch-refresh-info「更新状态」', children: [
        { fn: 'batch_refresh_orders_info', loc: 'sync/sync_data.py:292', children: [
          { fn: 'OrderModel.find_for_batch_info_refresh', note: '未完成且 data_user 非空', io: [{ t: 'r', x: 'orders' }] },
          { fn: '逐单 apply_item_info_to_order', loc: 'get_order_info.py:378', note: '同 C3 的详情补全', io: [{ t: 'api', x: 'GET /transaction_evidences/get' }, { t: 'w', x: 'orders' }] }
        ] }
      ] }
    ]
  },
  {
    id: 'C5',
    title: 'P6 · 在售商品同步与库存回绑',
    desc: '入口:POST /use_web/on-sale-items/sync 或 C2 定时触发;下架操作(C8)完成后也复用同一同步。',
    tree: [
      { fn: 'sync_on_sale_items_from_mercari', loc: 'on_sale_items_sync/sync.py:136', children: [
        { fn: '_resolve_account_and_seller', loc: 'sync_data.py:54', io: [{ t: 'r', x: 'mercari_accounts' }] },
        { fn: 'mitm_automation_browser → capture_on_sale_list_via_mitm_session', loc: 'on_sale_list.py:310', children: [
          { fn: '_expand_on_sale_listings_until_end', loc: ':191', note: '滚动 +「もっと見る」翻页,截获合并各页', io: [{ t: 'api', x: 'GET /items/get_items?status=on_sale,stop' }] }
        ] },
        { fn: 'apply_on_sale_list_sync', loc: 'sync.py:16', children: [
          { fn: 'mercari_list_item_to_row → upsert_on_sale_item_row', loc: 'row_mapping.py', io: [{ t: 'w', x: 'on_sale_items' }] },
          { fn: '消失商品软删 is_delete=1', io: [{ t: 'w', x: 'on_sale_items' }] },
          { fn: 'reconcile_listing_counts', loc: 'inventory_counters.py:368', note: '库存在售对账', children: [
            { fn: '_adjust_on_sale', loc: ':269', io: [{ t: 'w', x: 'inventory.on_sale_quantity' }] },
            { fn: 'recompute_listable_quantity', loc: ':75', io: [{ t: 'w', x: 'inventory.listable_quantity' }] },
            { fn: 'consume_unsynced_relists', loc: 'auto_relist.py:63', note: '核销自动补挂台账' }
          ] }
        ] },
        { fn: 'auto_fetch_details_for_inserted_items', loc: 'auto_fetch.py:69', note: '仅对新增 item 拉详情', children: [
          { fn: 'fetch_mercari_item_get_in_browser_session', loc: 'mercari_item_get.py:77', io: [{ t: 'api', x: 'GET /items/get?id=…' }] },
          { fn: 'detail_sync_inventory_from_item_get_response', loc: 'detail_sync.py:14', children: [
            { fn: 'parse_listing_description_tokens_with_quantity / decode_mgmt_id_cipher', loc: 'mgmt_id_cipher.py:65', note: '解析描述末行管理番号暗号', io: [{ t: 'r', x: 'config(mgmt_cipher_mode)' }] },
            { fn: 'resolve_inventory_id_from_listing_description', loc: 'description_mgmt_ids/*', note: '暗号/条码/组合标题三路匹配', io: [{ t: 'r', x: 'inventory' }] },
            { fn: '绑定 inventory.mercari_item_id', io: [{ t: 'w', x: 'inventory' }, { t: 'w', x: 'on_sale_items.listing_description' }] }
          ] }
        ] }
      ] }
    ]
  },
  {
    id: 'C6',
    title: 'P4 · 待办与通知同步',
    tree: [
      { fn: 'sync_todos_with_details', loc: 'get_to_du_list/todolist_sync.py:283', children: [
        { fn: 'sync_todos_from_mercari → capture_todolist_via_mitm_session', loc: ':237 · todolist_capture.py:32', io: [{ t: 'api', x: 'GET /services/todolist/v1/list' }], children: [
          { fn: 'apply_todolist_sync', loc: ':142', note: 'UPSERT(account_id,uuid) + 软删', io: [{ t: 'w', x: 'todo_items' }] }
        ] },
        { fn: 'precache_uncached_todo_details', loc: 'transaction_detail/precache.py:24', children: [
          { fn: 'fetch_transaction_detail', loc: 'detail.py:26', note: '专用 __todo Profile', io: [{ t: 'api', x: 'GET /shipping/get_info' }, { t: 'api', x: 'GET /transaction_messages/get_messages' }], children: [
            { fn: 'replace_order_messages', loc: '_messages_store.py', io: [{ t: 'w', x: 'transaction_messages' }] },
            { fn: '_persist_transaction_detail / _persist_awaiting_feedback', loc: '_cache.py', io: [{ t: 'w', x: 'todo_items.detail_json' }] }
          ] }
        ] },
        { fn: 'fetch_and_store_shipping_durations', loc: 'shipping_duration.py:62', note: '公开商品页 SSR DOM 读「発送までの日数」,无登录无 MITM', io: [{ t: 'ext', x: 'jp.mercari.com/item/{id}' }, { t: 'w', x: 'todo_items' }] },
        { fn: '_link_sync_on_new_wait_shipping', loc: ':330', note: '有新待发货时联动 → C5 + C3' }
      ] },
      { fn: 'sync_notifications_from_mercari', loc: 'get_notifications/…/notification_sync.py:258', io: [{ t: 'api', x: 'GET /services/notification/v1/list' }], children: [
        { fn: 'apply_notifications_sync → _upsert_notification_row', loc: ':195 / :173', note: 'UPSERT,不覆盖 is_read', io: [{ t: 'w', x: 'notifications' }] }
      ] }
    ]
  },
  {
    id: 'C7',
    title: 'P7 · 出品（post_to_market）',
    desc: '独立 __listing Profile,fresh 启动、用完即关;全局出品锁保证同一时刻仅一个出品。不读 MITM 响应,成败由页面文案判定。',
    tree: [
      { tag: 'POST', fn: 'post_to_market (handler)', loc: 'web_drive_handler/listing.py:87', note: '/use_web/web-drive/listing/post-to-market', children: [
        { fn: '_get_category_positions', loc: ':49', io: [{ t: 'r', x: 'product_type_category_mappings' }] },
        { fn: 'run_mercari_serial_async + hold_listing_lock', loc: ':169 · listing_lock.py:42', note: '账号队列 → 全局出品锁(auto_relist 走 background_caller 直取锁防死锁)' },
        { fn: '_do_post = post_to_market (业务)', loc: 'post_to_macket/post.py:18', children: [
          { fn: 'apply_watermark_to_images', loc: '_watermark.py:139', children: [
            { fn: '_watermark_one', loc: ':240', note: 'ImageOps.exif_transpose 摆正 → 水印瓦片(头像+账号名+日期)旋转 45° 贴右下 → 临时 jpg,不改原图', io: [{ t: 'r', x: 'mercari_accounts' }, { t: 'ext', x: 'imges/ 原图' }] }
          ] },
          { fn: 'listing_automation_browser', loc: 'listing_session.py:37', note: 'fresh __listing 会话', children: [
            { fn: 'start_mitm_proxy → mgr.open_session → clone_main_profile_cookies', loc: 'runner.py:115 · _mixin_sessions.py:128 · mitm_session.py:278', io: [{ t: 'ext', x: 'Edge 无头(经代理)' }] }
          ] },
          { fn: 'Playwright 表单自动化', note: '传图 expect_file_chooser :183 → 标题 _react_set_input :214 → 类目/成色 → 描述 _react_set_textarea :300 → 配送 → 价格 _set_sale_type_and_price :381', io: [{ t: 'ext', x: '出品页 DOM' }] },
          { fn: '点击「出品する」→ 等「出品が完了しました」', loc: 'post.py:410 / 462', note: '失败标记 submit_uncertain' },
          { fn: 'finally: mgr.close_session(force=True)', loc: 'listing_session.py:94' }
        ] }
      ] }
    ]
  },
  {
    id: 'C8',
    title: 'P7 · 改价 / 下架 / 暂停 / 恢复',
    desc: '共用 __sync Profile 与账号串行队列。改价/暂停/恢复提交后直接写回本地库;只有下架依赖 MITM 回读做在售对账。',
    tree: [
      { tag: 'POST', fn: 'revise_on_sale_item', loc: 'items.py:104', note: '/on-sale/revise-item', children: [
        { fn: 'revise_mercari_item', loc: 'revise/units/revise_order.py:181', children: [
          { fn: 'mitm_automation_browser(编辑页)', loc: 'mitm_session.py:341', io: [{ t: 'ext', x: 'sell/edit 页' }] },
          { fn: '_fill_price_value / _fill_value / _select_option_value', loc: ':75 / :66 / :92', note: '价格/标题/描述/配送三下拉' },
          { fn: '点击「変更する」→ _update_local_on_sale_item', loc: ':324 / :129', io: [{ t: 'w', x: 'on_sale_items' }] }
        ] }
      ] },
      { tag: 'POST', fn: 'delete_on_sale_item', loc: 'items.py:25', note: '/on-sale/delete-item', children: [
        { fn: 'delete_mercari_item', loc: 'delete/units/delete_order.py:104', children: [
          { fn: 'mitm_automation_browser(编辑页) → 点「この商品を削除する」→ 确认弹窗', loc: ':196 / :59', io: [{ t: 'ext', x: 'sell/edit 页' }] },
          { fn: 'sync_on_sale_from_listings_browser_page', loc: 'on_sale_list.py:389', note: '删除后跳出品一覧,复用会话截获列表回读', children: [
            { fn: 'wait_mitm_capture(read_on_sale_list_response)', loc: 'mitm_session.py:443', io: [{ t: 'api', x: 'GET /items/get_items?status=on_sale,stop' }] },
            { fn: 'apply_on_sale_list_sync + reconcile_listing_counts', note: '在售 −1 / 库存 +1 对账 → 同 C5', io: [{ t: 'w', x: 'on_sale_items' }, { t: 'w', x: 'inventory' }] }
          ] }
        ] }
      ] },
      { tag: 'POST', fn: 'suspend_mercari_item / resume_mercari_item', loc: 'suspend_order.py:53 / resume_order.py:53', note: '与改价同构:点 suspend-button / activate-button 后直接改本地状态', io: [{ t: 'w', x: 'on_sale_items.status' }] }
    ]
  },
  {
    id: 'C9',
    title: 'P7 · 售出后自动补挂（auto_relist）',
    desc: '由 C3 检测到新售出订单时触发;按库存余量重新出品同款。',
    tree: [
      { fn: 'run_auto_relist_for_orders', loc: 'auto_relist.py:92', children: [
        { fn: '_account_relist_enabled', loc: ':81', io: [{ t: 'r', x: 'mercari_accounts.auto_fetch_relist' }] },
        { fn: '_relist_for_order', loc: ':212', note: '乐观占用 auto_relisted=1 防重复', io: [{ t: 'r', x: 'orders' }, { t: 'w', x: 'orders.auto_relisted' }] , children: [
          { fn: '_inventory_ids_for_order', loc: ':164', io: [{ t: 'r', x: 'order_outbound_lines' }] },
          { fn: '_relist_single_inventory', loc: ':261', children: [
            { fn: 'InventoryModel.find_by_id', note: '校验余量/在售/待出库', io: [{ t: 'r', x: 'inventory' }] },
            { fn: '_build_relist_description → encode_mgmt_id', loc: 'mgmt_id_cipher.py:47', note: '描述末行嵌入管理番号暗号' },
            { fn: 'post_to_market(background_caller=True)', loc: 'listing.py:162', note: '复用 C7 出品链(直取全局出品锁)' },
            { fn: '_note_relist_posted + SystemLogModel.add', loc: ':56', note: '进程内台账,等 C5 对账核销', io: [{ t: 'w', x: 'system_logs' }] }
          ] }
        ] }
      ] }
    ]
  },
  {
    id: 'C10',
    title: 'P2 · 库存出入库与组合级联',
    tree: [
      { tag: 'POST', fn: 'stock_in_inventory', loc: 'inventory_stock.py:15', note: '条码入库', children: [
        { fn: 'BEGIN IMMEDIATE → UPDATE quantity+ → listable_quantity 重算', loc: ':25 / :31', note: '重算表达式来自 inventory_counters._listable_sql_expr', io: [{ t: 'w', x: 'inventory' }] },
        { fn: 'INSERT transactions(type=in)', loc: ':36', io: [{ t: 'w', x: 'transactions' }] }
      ] },
      { tag: 'POST', fn: 'stock_out_inventory', loc: 'inventory_stock.py:58', children: [
        { fn: 'UPDATE quantity− + INSERT transactions(type=out)', io: [{ t: 'w', x: 'inventory' }, { t: 'w', x: 'transactions' }] },
        { fn: 'cascade_combined_child_deduction', loc: 'inventory_counters.py:142', note: '组合商品出库级联扣减来源子商品', io: [{ t: 'w', x: 'inventory' }, { t: 'w', x: 'transactions' }] }
      ] },
      { tag: 'POST', fn: 'stock_out_order_outbound_line', loc: 'orders_outbound/lines.py:341', note: '订单出库行发货', children: [
        { fn: '原子条件 UPDATE(防超卖) → INSERT transactions → 级联扣减', loc: ':395', io: [{ t: 'w', x: 'inventory' }, { t: 'w', x: 'transactions' }, { t: 'w', x: 'order_outbound_lines' }] }
      ] },
      { tag: 'POST', fn: 'create_inventory', loc: 'inventory_crud.py:31', children: [
        { fn: '_resolve_paths_for_create → save_base64_image', loc: 'inventory_images.py:104 · image_storage.py:44', io: [{ t: 'ext', x: '写 imges/' }] },
        { fn: 'INSERT inventory → _enqueue_image_index', loc: ':41 / :88', note: 'CLIP 图搜索引', io: [{ t: 'w', x: 'inventory' }] }
      ] }
    ]
  },
  {
    id: 'C11',
    title: 'P1 · 登录认证与请求校验',
    tree: [
      { tag: 'POST', fn: 'login', loc: 'login_handler.py:50', note: '/use_web/login(公开路由)', children: [
        { fn: 'SELECT users WHERE username=?', loc: ':56', io: [{ t: 'r', x: 'users' }] },
        { fn: '_hash_password(pbkdf2_hmac sha256) 比对', loc: ':23' },
        { fn: 'UPDATE users.last_login_at', loc: ':75', io: [{ t: 'w', x: 'users' }] },
        { fn: 'create_access_token', loc: 'auth.py:16', note: 'HS256,JWT_EXPIRE_HOURS 默认 168h' }
      ] },
      { tag: '依赖', fn: 'require_auth', loc: 'auth.py:37', note: 'Depends 注入 use_web/use_mercari 全部受保护路由(15 个文件)', children: [
        { fn: 'verify_access_token', loc: ':27', note: 'jwt.decode;过期/无效 → 401' }
      ] },
      { tag: '启动', fn: 'startup_seed_user → _ensure_default_admin', loc: 'login/API.py:19 · login_handler.py:29', note: '无用户时播种 admin/admin', io: [{ t: 'w', x: 'users' }] }
    ]
  },
  {
    id: 'C12',
    title: 'DB 访问层（所有业务读写的公共下游）',
    desc: '业务 handler → 模型类方法 → DatabaseManager 单例。无连接池:每次操作新建 sqlite3 连接(WAL);事务经 thread-local 复用同一连接。',
    tree: [
      { fn: '业务代码', note: '如 MemoModel.find_all(memos_handler.py:151)、script.save()(talk_scripts_handler.py:93)', children: [
        { fn: 'BaseModel.find_by_id / find_all / count / delete_all', loc: 'base_model.py:166 / 184 / 205 / 83', children: [
          { fn: 'DatabaseManager.execute_query', loc: 'database.py:91' }
        ] },
        { fn: 'BaseModel.save', loc: 'base_model.py:62', note: '新记录 _insert,否则 _update(仅变化字段)', children: [
          { fn: '_insert → execute_insert(回填自增主键)', loc: ':114 · database.py:107' },
          { fn: '_update → execute_update', loc: ':137 · database.py:98' }
        ] },
        { fn: 'DatabaseManager.transaction()', loc: 'database.py:46', note: 'BEGIN IMMEDIATE,thread-local 连接,支持嵌套;出入库等多表写用它' },
        { fn: 'DatabaseManager.get_connection', loc: 'database.py:50', note: '每次 sqlite3.connect(timeout=30s),WAL / synchronous=NORMAL / foreign_keys=ON' }
      ] },
      { tag: '启动', fn: 'init_database → initialize_database', loc: 'db_manager.py:680 / 579', note: '幂等;迁移 + 25 模型 ensure_table_exists(base_model.py:243,自动增删列)' }
    ]
  }
]
</script>

<style scoped>
/* 全站固定深色主题（main.js 启动时给 html 加 dark 类），色板直接取深色值 */
.dfd-page {
  --bg: #12151a;
  --surface: #1a1f26;
  --ink: #e6eaf0;
  --muted: #9aa4b2;
  --faint: #6b7583;
  --border: #2b323c;
  --line: #8b95a3;
  --proc-fill: #222d4d;
  --proc-stroke: #7d96f5;
  --proc-ink: #a8baff;
  --ent-fill: #362d1a;
  --ent-stroke: #d9a84e;
  --ent-ink: #e8c078;
  --store-fill: #16332c;
  --store-stroke: #4fbfa4;
  --store-ink: #7fd8c2;
  --agent-fill: #2c2440;
  --agent-stroke: #a78bfa;
  --mono: ui-monospace, "Cascadia Code", Consolas, "Courier New", monospace;

  background: var(--bg);
  color: var(--ink);
  line-height: 1.65;
  padding: 28px 24px 56px;
  border-radius: 8px;
}
.eyebrow {
  font-size: 12px; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--muted); font-family: var(--mono); margin: 0 0 10px;
}
h1 { font-size: 28px; font-weight: 700; margin: 0 0 6px; }
.sub { color: var(--muted); margin: 0 0 8px; max-width: 68ch; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 0; }
.chip {
  font-family: var(--mono); font-size: 12px; color: var(--muted);
  border: 1px solid var(--border); border-radius: 4px; padding: 2px 9px;
  background: var(--surface);
}
.callout {
  margin-top: 18px; padding: 12px 16px; max-width: 90ch;
  background: var(--surface); border: 1px solid var(--proc-stroke);
  border-radius: 8px; font-size: 13.5px; color: var(--muted);
}
.callout strong { color: var(--ink); }
section { margin-top: 40px; }
h2 { font-size: 20px; margin: 0 0 4px; }
h2 .no, h3 .no { font-family: var(--mono); color: var(--proc-stroke); font-size: 15px; margin-right: 10px; }
h3 { font-size: 16px; margin: 26px 0 4px; }
h3 .no { font-size: 13px; }
.desc { color: var(--muted); margin: 0 0 14px; max-width: 80ch; font-size: 14.5px; }
.panel {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 18px; overflow-x: auto;
}
.panel svg { display: block; min-width: 900px; width: 100%; height: auto; }
.panel-table { padding: 6px 4px; }
.chain-panel { padding: 14px 18px; }
.chain-block { margin-top: 6px; }

/* ---- SVG 节点样式 ---- */
svg text { font-family: inherit; }
.ent-box { fill: var(--ent-fill); stroke: var(--ent-stroke); stroke-width: 1.6; }
.proc-box { fill: var(--proc-fill); stroke: var(--proc-stroke); stroke-width: 1.6; }
.agent-box { fill: var(--agent-fill); stroke: var(--agent-stroke); stroke-width: 1.6; }
.proc-divider { stroke: var(--proc-stroke); stroke-width: 1.2; }
.proc-divider.thin { stroke-width: 1; }
.store-shape { fill: var(--store-fill); stroke: var(--store-stroke); stroke-width: 1.6; }
.store-div { stroke: var(--store-stroke); stroke-width: 1.2; }
.node-id { font-family: var(--mono); font-size: 11px; font-weight: 600; }
.id-ent { fill: var(--ent-ink); }
.id-proc { fill: var(--proc-ink); }
.id-store { fill: var(--store-ink); }
.node-name { font-size: 14px; font-weight: 600; fill: var(--ink); }
.node-sub { font-size: 10.5px; fill: var(--muted); font-family: var(--mono); }
.flow { fill: none; stroke: var(--line); stroke-width: 1.4; }
.mk { fill: var(--line); }
.lbl {
  font-size: 12px; fill: var(--muted);
  paint-order: stroke; stroke: var(--surface); stroke-width: 5px; stroke-linejoin: round;
}

/* ---- 图例 ---- */
.legend { display: flex; flex-wrap: wrap; gap: 22px; align-items: center; margin-top: 16px; }
.legend-io { gap: 18px; margin-top: 10px; }
.legend-item { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--muted); }
.legend-item svg { display: block; }
.io-chip {
  font-family: var(--mono); font-size: 10.5px;
  border: 1px solid; border-radius: 3px; padding: 0 6px;
}
.io-chip.r { color: var(--store-ink); border-color: var(--store-stroke); }
.io-chip.w { color: #f0a35c; border-color: #a06a30; }
.io-chip.api { color: var(--proc-ink); border-color: var(--proc-stroke); }
.io-chip.ext { color: var(--muted); border-color: var(--border); }

/* ---- 表格 ---- */
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 12.5px; letter-spacing: 0.04em; white-space: nowrap; }
td:first-child, th:first-child { white-space: nowrap; }
tbody tr:last-child td { border-bottom: none; }
code {
  font-family: var(--mono); font-size: 12.5px;
  background: var(--bg); border: 1px solid var(--border);
  border-radius: 4px; padding: 1px 6px;
}
.tag { font-family: var(--mono); font-weight: 700; font-size: 12.5px; }
.tag.p { color: var(--proc-ink); }
.tag.d { color: var(--store-ink); }
.note {
  margin-top: 14px; font-size: 13.5px; color: var(--muted);
  border-left: 3px solid var(--proc-stroke); padding: 2px 0 2px 14px; max-width: 88ch;
}
.note strong { color: var(--ink); }
footer { margin-top: 48px; color: var(--faint); font-size: 12.5px; font-family: var(--mono); }
</style>
