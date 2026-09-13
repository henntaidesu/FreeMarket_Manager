// ============================================================
// Node 反代（煤炉 / 雅虎）—— 零依赖单文件 (Node 18+，建议 20/24)
//   node server.js           # 由后端 runner 托管，独立 HTTPS 端口、根挂载（默认 9610）
//
// 基础改造（融入 mercari 系统，源自 github.com/Gosoki/mercari-proxy）：
//   1) /__inject（内部）：后端把账号 Cookie + 目标站点以一次性 token 暂存到本进程内存，
//      需 x-internal-secret 头匹配 MERCARI_PROXY_INTERNAL_SECRET。
//   2) <BASE>/__boot?token=xxx：用户本地浏览器打开此地址，本服务把对应 Cookie
//      通过 Set-Cookie 写到代理域名下，然后 302 跳到 <BASE>/ ——于是已登录态注入完成。
//   3) BASE_PATH：可选子路径前缀（默认空=根挂载）。根挂载时 SPA 导航/刷新/前进后退
//      均正常，是该项目的原始设计与本系统采用的部署方式。
//   4) 多站点：上游**不是**进程级常量。/__boot 把选中的站点写进 __mp_site Cookie，
//      之后每个请求按该 Cookie 决定上游与域名改写规则（见 SITES）。
//   5) 注入会话：/__boot 同时下发一张 HMAC 签名的会话票据（__mp_sess），其余所有路径
//      没票即 403。绝对过期、不续期，最长 1 小时。经 nginx 以独立域名对外发布时，这是
//      唯一挡住「开放反向代理」的东西——按来源地址判断的 isAllowedClient 在反代背后恒真。
// ============================================================
const http = require("http");
const tls = require("tls");
const crypto = require("crypto");
const { Readable } = require("stream");

const PORT = Number(process.env.PORT) || 9610;
const BIND_HOST = process.env.BIND_HOST || "127.0.0.1";

// 挂载基础路径（无尾斜杠）。默认空 = 根路径（与原版行为一致）。
const BASE = (process.env.BASE_PATH || "").replace(/\/+$/, "");

// 内部注入密钥（后端调用 /__inject 时校验）；为空则不校验（仅本机可达时可接受）。
const INTERNAL_SECRET = process.env.MERCARI_PROXY_INTERNAL_SECRET || "";

// ---------------- 站点注册表 ----------------
// 反代存在的意义是「用我们自己的源，写别人域名的登录态」——浏览器不可能从 9600 端口给
// jp.mercari.com 或 yahoo.co.jp 写 Cookie。所以雅虎必须和煤炉走同一条路，只是上游不同。
//   host  : 根相对路径（非 /__p/）的默认上游
//   reSrc : 哪些域名要被改写成走代理（含各自 CDN）；同时下发给页面内的运行时劫持脚本
const SITES = {
  // 日本站 jp.mercari.com / 美区 www.mercari.com，由 UPSTREAM 覆盖
  mercari: {
    host: process.env.UPSTREAM || "jp.mercari.com",
    reSrc: "(^|\\.)(mercari\\.com|mercari\\.jp|mercdn\\.net|mercari-shops\\.com)$",
  },
  // 公开页 paypayfleamarket / 登录态 sec 域 / login.yahoo.co.jp / 静态资源 s.yimg.jp
  yahoo: {
    host: "paypayfleamarket.yahoo.co.jp",
    reSrc: "(^|\\.)(yahoo\\.co\\.jp|yimg\\.jp|yahooapis\\.jp|paypay\\.ne\\.jp)$",
  },
};
for (const [key, s] of Object.entries(SITES)) {
  s.key = key;
  s.re = new RegExp(s.reSrc, "i");
}

const DEFAULT_SITE = "mercari";
//: 记录本次注入选中的站点。必须是 Cookie 而不是进程常量——同一个代理端口要轮流服务
//: 煤炉和雅虎，而根相对请求（/item/xxx）里没有任何信息能推断出该发给哪个上游。
const SITE_COOKIE = "__mp_site";

function siteOf(req) {
  return SITES[parseCookies(req)[SITE_COOKIE]] || SITES[DEFAULT_SITE];
}

// 针对性 JS 文本替换：干掉硬编码 host 检查 / 强制跳转等。默认空，按需补。
const JS_PATCHES = [];

// 转发时要丢掉的 hop-by-hop / 会干扰的头
const DROP_REQ_HEADERS = new Set([
  "host", "connection", "keep-alive", "proxy-connection",
  "transfer-encoding", "upgrade", "accept-encoding", "content-length",
]);
const DROP_RESP_HEADERS = new Set([
  "content-encoding", "content-length", "transfer-encoding", "connection",
]);

// ---------------- 访问控制（第一层：谁能连上这个端口） ----------------
// 只看 TCP 对端地址：环回 + 私有网段放行，公网地址一律拒绝
// （MERCARI_PROXY_ALLOW_LAN=0 收回成仅本机）。用户常从局域网另一台机器访问管理系统，
// 此时浏览器的 boot 请求来自内网 IP 而非环回地址，只认 loopback 会直接 403。
//
// ⚠ 经 nginx 以独立域名对外发布后，对端恒为 nginx 的内网地址——这一层对公网访客
// **永远放行**，它不是、也无法是对外发布时的授权手段。那件事由下面的注入会话票据负责。
const ALLOW_LAN = process.env.MERCARI_PROXY_ALLOW_LAN !== "0";

function remoteAddr(req) {
  const a = (req.socket && req.socket.remoteAddress) || "";
  // Node 在双栈监听下把 IPv4 报成 IPv4-mapped IPv6（::ffff:192.168.1.5）
  return a.startsWith("::ffff:") ? a.slice(7) : a;
}

function isLoopbackAddr(a) {
  return a === "::1" || /^127\./.test(a);
}

// RFC1918 + 链路本地；IPv6 取 ULA(fc00::/7) 与链路本地(fe80::/10)。
function isPrivateAddr(a) {
  if (a.includes(":")) return /^(f[cd]|fe[89ab])/i.test(a);
  const p = a.split(".");
  if (p.length !== 4) return false;
  const n = p.map(Number);
  if (n.some((x) => !Number.isInteger(x) || x < 0 || x > 255)) return false;
  if (n[0] === 10) return true;
  if (n[0] === 172 && n[1] >= 16 && n[1] <= 31) return true;
  if (n[0] === 192 && n[1] === 168) return true;
  if (n[0] === 169 && n[1] === 254) return true;
  return false;
}

function isAllowedClient(req) {
  const a = remoteAddr(req);
  if (isLoopbackAddr(a)) return true;
  return ALLOW_LAN && isPrivateAddr(a);
}

// ---------------- 浏览器那一跳用的是什么协议 ----------------
// SCHEME 是「本进程自己有没有证书」决定的。TLS 由 nginx / cloudflared 终止时回源那跳
// 可能是明文，而 Cookie 的 Secure 标记必须按**浏览器看到的**协议来：页面是 https 而
// Cookie 没带 Secure，__Secure- / __Host- 前缀的那几条会被浏览器整条丢弃，表现为
// 「注入了 N 条但就是没登录」。伪造这个头只会弄坏伪造者自己的会话（多写或少写一个
// Secure），不构成对他人的降级，因此不必限定可信对端。
function reqScheme(req) {
  const p = String(req.headers["x-forwarded-proto"] || "").split(",")[0].trim().toLowerCase();
  return p === "https" || p === "http" ? p : SCHEME;
}

// ---------------- 访问控制（第二层：注入会话票据） ----------------
// 对外发布时这是**唯一**的授权凭据。/__boot 的一次性 token 只有登录了本系统的用户才拿得到，
// 用它换一张 HMAC 签名的票据；其余所有路径（含 /__p/ 与 /__pws__/ WebSocket）没票即 403。
// 票据**绝对过期**：不续期、不滑动，到点必须回系统重新点「Cookie 注入」。于是浏览器里那张
// 通往煤炉/雅虎登录态的门票，生命周期被硬性限制在一小时内。
// 签名密钥复用 INTERNAL_SECRET（由后端进程生成并下发），所以后端一重启全部票据即作废。
const SESSION_COOKIE = "__mp_sess";
const SESSION_TTL_MAX_SEC = 3600;
const SESSION_TTL_SEC = (() => {
  // 口径由 Python 侧 runner.session_ttl_sec() 决定并下发；这里的钳制是独立运行 server.js
  // 时的兜底。两处都只能往「更短」收，不存在放宽的可能，因此即使漂移也不会变得更松。
  const v = Number(process.env.MERCARI_PROXY_SESSION_TTL_SEC);
  return Number.isFinite(v) && v > 0 ? Math.min(v, SESSION_TTL_MAX_SEC) : SESSION_TTL_MAX_SEC;
})();
const SESSION_KEY = INTERNAL_SECRET || crypto.randomBytes(32).toString("hex");

function signSession(expSec, siteKey) {
  const body = `${expSec}.${siteKey}`;
  return `${body}.${crypto.createHmac("sha256", SESSION_KEY).update(body).digest("base64url")}`;
}

function verifySession(req) {
  const raw = parseCookies(req)[SESSION_COOKIE] || "";
  const i = raw.lastIndexOf(".");
  if (i <= 0) return null;
  const body = raw.slice(0, i);
  const sig = Buffer.from(raw.slice(i + 1));
  const want = Buffer.from(
    crypto.createHmac("sha256", SESSION_KEY).update(body).digest("base64url")
  );
  // timingSafeEqual 长度不等时会抛，先挡掉
  if (sig.length !== want.length || !crypto.timingSafeEqual(sig, want)) return null;
  // 过期时间是签进票据里的，改浏览器那份 Cookie 的 Max-Age 没有意义
  const exp = Number(body.slice(0, body.indexOf(".")));
  if (!Number.isFinite(exp) || exp * 1000 <= Date.now()) return null;
  return { exp };
}

function denySession(res) {
  const mins = Math.max(1, Math.round(SESSION_TTL_SEC / 60));
  res.writeHead(403, {
    "content-type": "text/html; charset=utf-8",
    "cache-control": "no-store",
    "x-robots-tag": "noindex, nofollow",
  });
  res.end(
    '<meta charset="utf-8"><h3>注入会话不存在或已过期</h3>' +
      `<p>会话最长 ${mins} 分钟，且不会自动续期。` +
      "请回到系统的「店铺账号」页重新点击「Cookie 注入」。</p>"
  );
}

// 自有 Cookie 不能跟着发给上游：__mp_sess 是本代理的授权票据，交给煤炉/雅虎毫无必要；
// __mp_site 也只是本进程用来选上游的路由标记。
function stripOwnCookies(raw) {
  return String(raw || "")
    .split(";")
    .filter((p) => {
      const eq = p.indexOf("=");
      const n = (eq === -1 ? p : p.slice(0, eq)).trim();
      return n !== SESSION_COOKIE && n !== SITE_COOKIE;
    })
    .join(";")
    .trim();
}

// ---------------- Cookie 注入暂存（一次性 token） ----------------
const injectionStore = new Map(); // token -> { cookies: [{name,value,httpOnly}], site, expires: ms }

function pruneInjections() {
  const now = Date.now();
  for (const [k, v] of injectionStore) {
    if (!v || v.expires <= now) injectionStore.delete(k);
  }
}

const handler = async (req, res) => {
  try {
    if (!isAllowedClient(req)) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      return res.end(
        `forbidden: 仅允许本机与局域网访问（来源 ${remoteAddr(req) || "unknown"}）`
      );
    }
    const PROXY_HOST = req.headers.host || `localhost:${PORT}`;
    const reqUrl = new URL(req.url, `http://${PROXY_HOST}`);
    const path = reqUrl.pathname;

    // 1) CORS 预检
    if (req.method === "OPTIONS") {
      res.writeHead(204, corsHeaders(req));
      return res.end();
    }

    // 2) 身份探针：让 runner 确认「127.0.0.1 上应答的确实是我刚拉起的那个进程」。
    //    旧版本没有这个路由，会把 /__ping 当普通路径转发给上游，于是返回的不是这段 JSON——
    //    这正是 runner 用来识别残留进程的依据。
    if (path === "/__ping") {
      if (!isLoopbackAddr(remoteAddr(req)) ||
          (INTERNAL_SECRET && req.headers["x-internal-secret"] !== INTERNAL_SECRET)) {
        res.writeHead(403, { "content-type": "text/plain" });
        return res.end("forbidden");
      }
      res.writeHead(200, { "content-type": "application/json" });
      return res.end(JSON.stringify({ ok: true, proxy: "mercari-proxy", pid: process.pid }));
    }

    // 3) 内部注入端点（后端 → 本进程，不经 BASE 前缀；浏览器经 Vite 只能到 BASE 下，触达不到）
    if (path === "/__inject") return handleInject(req, res);

    // 4) Cookie 注入引导页：写 Cookie 后跳转进代理站
    if (path === `${BASE}/__boot`) return handleBoot(req, res, reqUrl, PROXY_HOST);

    // 5) 授权闸门：除上面几个自有端点外，一切都要一张有效的注入会话票据。
    //    对外发布时这是唯一挡住「开放反向代理」的东西——isAllowedClient 在 nginx 背后恒真。
    if (!verifySession(req)) return denySession(res);

    // 6) 解析上游目标（先剥离 BASE 前缀）；上游站点由 __mp_site Cookie 决定
    const site = siteOf(req);
    // 只有恰好等于 BASE、或落在 BASE/ 之下，才剥前缀。光用 startsWith 会把 /mpfoo 切成
    // "foo"，进而拼出 https://jp.mercari.comfoo 这种畸形上游地址。
    let rel =
      BASE && (path === BASE || path.startsWith(BASE + "/")) ? path.slice(BASE.length) : path;
    if (rel === "") rel = "/";
    const { upstreamHost, upstreamPath } = resolveTarget(rel, site);
    const upstreamUrl = `https://${upstreamHost}${upstreamPath}${reqUrl.search}`;

    // 7) 组装转发请求头（DPoP / Authorization / Cookie 透传，自有 Cookie 除外）
    const fwd = {};
    for (const [k, v] of Object.entries(req.headers)) {
      const lk = k.toLowerCase();
      if (DROP_REQ_HEADERS.has(lk)) continue;
      if (lk.startsWith("cf-") || lk.startsWith("x-forwarded-") || lk === "x-real-ip") continue;
      if (lk === "cookie") {
        const c = stripOwnCookies(v);
        if (c) fwd[k] = c;
        continue;
      }
      fwd[k] = v;
    }
    if (fwd["origin"]) fwd["origin"] = `https://${site.host}`;
    if (fwd["referer"]) {
      fwd["referer"] = fwd["referer"]
        .split(PROXY_HOST).join(site.host)
        .replace(new RegExp(`^https?://${escapeReg(site.host)}${escapeReg(BASE)}/__p/[^/]+/`), "https://" + site.host + "/");
    }

    // 8) body
    const hasBody = !["GET", "HEAD"].includes(req.method);
    const body = hasBody ? await readBody(req) : undefined;

    const resp = await fetch(upstreamUrl, {
      method: req.method,
      headers: fwd,
      body,
      redirect: "manual",
    });

    // 9) 处理响应头
    const outHeaders = {};
    for (const [k, v] of resp.headers) {
      if (k.toLowerCase() === "set-cookie") continue;
      if (DROP_RESP_HEADERS.has(k.toLowerCase())) continue;
      outHeaders[k] = v;
    }
    stripSecurityHeaders(outHeaders);
    applyCors(outHeaders, req);
    // 这个域名对外可达，但它是一条通往账号登录态的隧道，不该被任何搜索引擎收录。
    outHeaders["x-robots-tag"] = "noindex, nofollow";
    const cookies = rewriteSetCookie(resp, reqScheme(req));
    if (cookies.length) outHeaders["set-cookie"] = cookies;
    rewriteLocation(outHeaders, upstreamHost, PROXY_HOST, site);

    const ctype = (resp.headers.get("content-type") || "").toLowerCase();

    // 10) HTML：注入运行时劫持脚本 + 改写绝对 URL 属性
    if (ctype.includes("text/html")) {
      let html = await resp.text();
      html = injectAndRewriteHtml(html, PROXY_HOST, site);
      res.writeHead(resp.status, outHeaders);
      return res.end(html);
    }

    // 11) JS：仅当配置了补丁时才改（默认不动，保住 DPoP htu）
    const isJs = ctype.includes("javascript") || new URL(upstreamUrl).pathname.endsWith(".js");
    if (JS_PATCHES.length && isJs) {
      let text = await resp.text();
      for (const p of JS_PATCHES) text = text.split(p.from).join(p.to);
      res.writeHead(resp.status, outHeaders);
      return res.end(text);
    }

    // 12) 其它原样透传（流式）
    res.writeHead(resp.status, outHeaders);
    if (resp.body) Readable.fromWeb(resp.body).pipe(res);
    else res.end();
  } catch (e) {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end("proxy error: " + (e && e.message ? e.message : String(e)));
  }
};

// ---------------- 内部注入 / 引导 ----------------
async function handleInject(req, res) {
  // 端口现在对局域网可达，但这个端点只由后端从 127.0.0.1 调用，没有任何理由跟着暴露出去。
  if (!isLoopbackAddr(remoteAddr(req))) {
    res.writeHead(403, { "content-type": "text/plain" });
    return res.end("forbidden: loopback only");
  }
  if (req.method !== "POST") {
    res.writeHead(405, { "content-type": "text/plain" });
    return res.end("method not allowed");
  }
  if (INTERNAL_SECRET && req.headers["x-internal-secret"] !== INTERNAL_SECRET) {
    res.writeHead(403, { "content-type": "text/plain" });
    return res.end("forbidden");
  }
  let raw;
  try {
    raw = await readBody(req);
  } catch {
    raw = undefined;
  }
  let payload;
  try {
    payload = JSON.parse((raw && raw.toString("utf-8")) || "{}");
  } catch {
    res.writeHead(400, { "content-type": "text/plain" });
    return res.end("bad json");
  }
  const token = String(payload.token || "");
  const cookies = Array.isArray(payload.cookies) ? payload.cookies : [];
  const ttlSec = Number(payload.ttl_sec) > 0 ? Number(payload.ttl_sec) : 120;
  const site = String(payload.site || "");
  if (!token || !cookies.length) {
    res.writeHead(400, { "content-type": "text/plain" });
    return res.end("missing token or cookies");
  }
  // 站点未知就直接拒绝，不要退回默认：那会把雅虎账号的 Cookie 注到煤炉上游去，
  // 用户只看到「注入成功但没登录」，而两边都没有任何报错。
  if (site && !SITES[site]) {
    res.writeHead(400, { "content-type": "text/plain" });
    return res.end(`unknown site: ${site}`);
  }
  pruneInjections();
  injectionStore.set(token, {
    cookies,
    site: site || DEFAULT_SITE,
    expires: Date.now() + ttlSec * 1000,
  });
  res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify({ ok: true, count: cookies.length }));
}

function handleBoot(req, res, reqUrl, proxyHost) {
  pruneInjections();
  const token = reqUrl.searchParams.get("token") || "";
  const entry = token ? injectionStore.get(token) : null;
  if (!entry) {
    res.writeHead(400, { "content-type": "text/html; charset=utf-8" });
    return res.end("<h3>注入链接已失效或已被使用，请在系统里重新点击「Cookie 注入」。</h3>");
  }
  injectionStore.delete(token); // 一次性
  const cookiePath = BASE || "/";
  const siteKey = SITES[entry.site] ? entry.site : DEFAULT_SITE;
  // https 下必须带 Secure：__Secure- / __Host- 前缀的 Cookie 缺了它会被浏览器整条丢弃，
  // 于是「注入了 N 条」但关键那条根本没落地。http 回退时不能加，否则一条都写不进去。
  const secure = reqScheme(req) === "https" ? "; Secure" : "";
  // 导出的 profile Cookie 里理论上不会有同名的，真有的话会在下面把刚写的票据/路由位
  // 覆盖掉（签名伪造不了，所以后果是会话当场失效），不如在这里就摘干净。
  const injected = entry.cookies.filter(
    (c) => c.name !== SESSION_COOKIE && c.name !== SITE_COOKIE
  );
  const fresh = new Set(injected.map((c) => c.name));

  // 先清掉浏览器里残留的旧 Cookie。它们属于上一次注入的账号（甚至上一个市集），
  // 留着只会拼出一个半新半旧的会话——换账号注入后仍显示旧账号就是这么来的，
  // 也避免把煤炉的登录态随请求发到雅虎上游去。
  const setCookies = [];
  for (const name of Object.keys(parseCookies(req))) {
    if (fresh.has(name) || name === SITE_COOKIE || name === SESSION_COOKIE) continue;
    setCookies.push(`${name}=; Path=${cookiePath}; Max-Age=0`);
  }
  setCookies.push(`${SITE_COOKIE}=${siteKey}; Path=${cookiePath}; SameSite=Lax${secure}`);
  // 注入会话票据。Max-Age 只是让浏览器到点自己扔掉，真正说了算的是签进票据里的 exp。
  const sessExp = Math.floor(Date.now() / 1000) + SESSION_TTL_SEC;
  setCookies.push(
    `${SESSION_COOKIE}=${signSession(sessExp, siteKey)}; Path=${cookiePath}` +
      `; Max-Age=${SESSION_TTL_SEC}; HttpOnly; SameSite=Lax${secure}`
  );
  for (const c of injected) {
    let s = `${c.name}=${c.value}; Path=${cookiePath}; SameSite=Lax${secure}`;
    if (c.httpOnly) s += "; HttpOnly";
    setCookies.push(s);
  }
  res.writeHead(302, {
    "set-cookie": setCookies,
    location: `${BASE}/`,
    "cache-control": "no-store",
    // token 走 query string（用户浏览器要直接导航过来，没法用 POST 交接）。它是一次性的
    // ——上面 injectionStore.delete 已经把它作废了——但在被使用前的 TTL 窗口内，这个 URL
    // 会留在浏览器历史里。no-referrer 保证它至少不会随后续请求的 Referer 头外泄出去。
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex, nofollow",
    "content-type": "text/plain; charset=utf-8",
  });
  res.end("cookie injected, redirecting...");
}

// http 还是 https：设了 TLS_CERT/TLS_KEY 就走 https
const TLS_CERT = process.env.TLS_CERT;
const TLS_KEY = process.env.TLS_KEY;
const SCHEME = TLS_CERT && TLS_KEY ? "https" : "http";
let server;
if (SCHEME === "https") {
  const https = require("https");
  const fs = require("fs");
  server = https.createServer(
    { cert: fs.readFileSync(TLS_CERT), key: fs.readFileSync(TLS_KEY) },
    handler
  );
} else {
  server = http.createServer(handler);
}

// ---------------- WebSocket 代理：<BASE>/__pws__/<host>/<path> ----------------
server.on("upgrade", (req, clientSock, head) => {
  if (!isAllowedClient(req)) return clientSock.destroy();
  // WebSocket 同样要票：漏掉这里就等于给未授权访客留了一条绕开 HTTP 闸门的通道。
  if (!verifySession(req)) return clientSock.destroy();
  const wsPath =
    BASE && (req.url === BASE || req.url.startsWith(BASE + "/"))
      ? req.url.slice(BASE.length)
      : req.url;
  const m = wsPath.match(/^\/__pws__\/([^/]+)(\/.*)?$/);
  if (!m) return clientSock.destroy();
  const host = m[1];
  const path = m[2] || "/";
  const upstream = tls.connect(443, host, { servername: host }, () => {
    const lines = [`GET ${path} HTTP/1.1`, `Host: ${host}`];
    for (const [k, v] of Object.entries(req.headers)) {
      const lk = k.toLowerCase();
      if (lk === "host") continue;
      if (lk === "origin") { lines.push(`Origin: https://${siteOf(req).host}`); continue; }
      lines.push(`${k}: ${v}`);
    }
    upstream.write(lines.join("\r\n") + "\r\n\r\n");
    if (head && head.length) upstream.write(head);
    clientSock.pipe(upstream);
    upstream.pipe(clientSock);
  });
  upstream.on("error", () => clientSock.destroy());
  clientSock.on("error", () => upstream.destroy());
});

// ---------------- 路由 ----------------
// /__p/<host>/<path...> => https://<host>/<path...>；其它走当前站点上游（rel 已剥离 BASE）
function resolveTarget(rel, site) {
  const m = rel.match(/^\/__p\/([^/]+)(\/.*)?$/);
  if (m) return { upstreamHost: m[1], upstreamPath: m[2] || "/" };
  return { upstreamHost: site.host, upstreamPath: rel };
}

function toProxyUrl(absUrl, proxyHost, site) {
  try {
    const u = new URL(absUrl);
    if (u.hostname === proxyHost) return absUrl;
    if (!site.re.test(u.hostname)) return absUrl;
    // 协议相对 //host<BASE>/__p/...，让浏览器按当前页面协议解析，避免 mixed-content。
    return `//${proxyHost}${BASE}/__p/${u.hostname}${u.pathname}${u.search}`;
  } catch {
    return absUrl;
  }
}

// ---------------- 头处理 ----------------
function stripSecurityHeaders(h) {
  for (const k of Object.keys(h)) {
    const lk = k.toLowerCase();
    if ([
      "content-security-policy", "content-security-policy-report-only", "x-frame-options",
      "cross-origin-opener-policy", "cross-origin-embedder-policy", "cross-origin-resource-policy",
      "report-to", "nel",
    ].includes(lk)) delete h[k];
  }
}

// 只回显**本代理自己的源**，其余一律不发 CORS 头。页面里指向上游域名的请求都已被改写成
// 同源，跨源放行没有任何用处；而反射任意 Origin 再配上 allow-credentials，等于把一个带着
// 煤炉/雅虎登录态的源开放给全网读取（SameSite=Lax 只挡住一部分，不是可以依赖的边界）。
function corsOrigin(req) {
  const o = req.headers["origin"];
  return o && o === `${reqScheme(req)}://${req.headers.host || ""}` ? o : "";
}
function corsHeaders(req) {
  const o = corsOrigin(req);
  if (!o) return {};
  return {
    "access-control-allow-origin": o,
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET,POST,PUT,DELETE,PATCH,OPTIONS",
    "access-control-allow-headers": req.headers["access-control-request-headers"] || "*",
    "access-control-max-age": "86400",
  };
}
function applyCors(h, req) {
  const o = corsOrigin(req);
  if (!o) return;
  h["access-control-allow-origin"] = o;
  h["access-control-allow-credentials"] = "true";
  h["access-control-expose-headers"] = "*";
}

// 去掉 Domain，下放 SameSite；BASE 非空时把 Path 收敛到 BASE，避免 Cookie 外溢到 SPA。
function rewriteSetCookie(resp, scheme) {
  const cookies = typeof resp.headers.getSetCookie === "function" ? resp.headers.getSetCookie() : [];
  return cookies
    // 上游无权改写本代理自己的状态位：__mp_sess 是授权票据，__mp_site 决定后续根相对
    // 请求发往哪个市集。签名伪造不了，但放任覆盖会让会话平白失效、或把请求指向另一个上游。
    .filter((c) => {
      const eq = c.indexOf("=");
      const n = (eq === -1 ? c : c.slice(0, eq)).trim();
      return n !== SESSION_COOKIE && n !== SITE_COOKIE;
    })
    .map((c) => {
    let out = c.replace(/;\s*Domain=[^;]+/i, "");
    // 只有**浏览器那一跳**退回 http 时才需要摘掉 Secure；https 下摘了反而会让浏览器整条
    // 丢弃 __Secure- / __Host- 前缀的 Cookie（前缀语义强制要求 Secure），登录态随即失效。
    if (scheme !== "https") out = out.replace(/;\s*Secure/i, "");
    out = out.replace(/;\s*SameSite=None/i, "; SameSite=Lax");
    if (BASE) {
      if (/;\s*Path=[^;]*/i.test(out)) out = out.replace(/;\s*Path=[^;]*/i, `; Path=${BASE}`);
      else out += `; Path=${BASE}`;
    }
    return out;
  });
}

function rewriteLocation(h, upstreamHost, proxyHost, site) {
  const key = Object.keys(h).find((k) => k.toLowerCase() === "location");
  if (!key) return;
  const loc = h[key];
  let abs = loc;
  if (loc.startsWith("//")) abs = "https:" + loc;
  else if (loc.startsWith("/")) abs = `https://${upstreamHost}${loc}`;
  h[key] = toProxyUrl(abs, proxyHost, site);
}

// ---------------- HTML 注入 + 属性改写 ----------------
function injectAndRewriteHtml(html, proxyHost, site) {
  html = html.replace(/\b(src|href)\s*=\s*("|')(.*?)\2/gi, (full, attr, q, val) => {
    let nv = val;
    if (/^https?:\/\//i.test(val)) nv = toProxyUrl(val, proxyHost, site);
    else if (val.startsWith("//")) nv = toProxyUrl("https:" + val, proxyHost, site);
    return `${attr}=${q}${nv}${q}`;
  });
  html = html.replace(/\bsrcset\s*=\s*("|')(.*?)\1/gi, (full, q, val) => {
    const nv = val.split(",").map((part) => {
      const seg = part.trim();
      const sp = seg.indexOf(" ");
      const url = sp === -1 ? seg : seg.slice(0, sp);
      const desc = sp === -1 ? "" : seg.slice(sp);
      let nu = url;
      if (/^https?:\/\//i.test(url)) nu = toProxyUrl(url, proxyHost, site);
      else if (url.startsWith("//")) nu = toProxyUrl("https:" + url, proxyHost, site);
      return nu + desc;
    }).join(", ");
    return `srcset=${q}${nv}${q}`;
  });
  const tag = `<script>${buildClientScript(proxyHost, site)}</script>`;
  const m = html.match(/<head[^>]*>/i);
  if (m) {
    const idx = m.index + m[0].length;
    return html.slice(0, idx) + tag + html.slice(idx);
  }
  return tag + html;
}

// ---------------- 注入页面的运行时劫持脚本 ----------------
function buildClientScript(proxyHost, site) {
  return `
(function(){
  var PROXY=${JSON.stringify(proxyHost)};
  var BASE=${JSON.stringify(BASE)};
  var RE=new RegExp(${JSON.stringify(site.reSrc)},"i");
  function toProxy(input){
    try{
      var u=new URL(input, location.href);
      if(u.hostname===PROXY) return input;
      if(!RE.test(u.hostname)) return input;
      if(u.protocol==="ws:"||u.protocol==="wss:")
        return (location.protocol==="https:"?"wss:":"ws:")+"//"+PROXY+BASE+"/__pws__/"+u.hostname+u.pathname+u.search;
      return location.protocol+"//"+PROXY+BASE+"/__p/"+u.hostname+u.pathname+u.search;
    }catch(e){ return input; }
  }
  var _fetch=window.fetch;
  window.fetch=function(input,init){
    try{
      if(typeof input==="string") input=toProxy(input);
      else if(input&&input.url) input=new Request(toProxy(input.url),input);
    }catch(e){}
    return _fetch.call(this,input,init);
  };
  var _open=XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open=function(m,url){ arguments[1]=toProxy(url); return _open.apply(this,arguments); };
  var _WS=window.WebSocket;
  window.WebSocket=function(url,p){ return new _WS(toProxy(url),p); };
  window.WebSocket.prototype=_WS.prototype;
  try{ ["CONNECTING","OPEN","CLOSING","CLOSED"].forEach(function(k){ window.WebSocket[k]=_WS[k]; }); }catch(e){}
  ["src","href"].forEach(function(prop){
    [HTMLScriptElement,HTMLImageElement,HTMLLinkElement,HTMLIFrameElement].forEach(function(K){
      if(!K) return;
      var d=Object.getOwnPropertyDescriptor(K.prototype,prop);
      if(!d||!d.set) return;
      Object.defineProperty(K.prototype,prop,{
        configurable:true, enumerable:d.enumerable,
        get:function(){ return d.get.call(this); },
        set:function(v){ d.set.call(this,toProxy(v)); }
      });
    });
  });
  var _setAttr=Element.prototype.setAttribute;
  Element.prototype.setAttribute=function(n,v){ if(n==="src"||n==="href") v=toProxy(v); return _setAttr.call(this,n,v); };
})();
`;
}

// ---------------- utils ----------------
function escapeReg(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseCookies(req) {
  const out = {};
  for (const part of (((req.headers && req.headers.cookie) || "").split(";"))) {
    const i = part.indexOf("=");
    if (i === -1) continue;
    out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(chunks.length ? Buffer.concat(chunks) : undefined));
    req.on("error", reject);
  });
}

server.listen(PORT, BIND_HOST, () => {
  console.log(`mercari-proxy (node) → ${SCHEME}://${BIND_HOST}:${PORT}${BASE || ""}`);
  const sites = Object.values(SITES).map((s) => `${s.key}=${s.host}`).join("  ");
  console.log(`站点: ${sites}  默认: ${DEFAULT_SITE}  BASE_PATH: ${BASE || "(none)"}`);
});
