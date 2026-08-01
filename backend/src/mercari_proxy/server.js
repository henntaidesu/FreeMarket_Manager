// ============================================================
// Node 反代煤炉 (Mercari) —— 零依赖单文件 (Node 18+，建议 20/24)
//   node server.js           # 由后端 runner 托管，独立 HTTPS 端口、根挂载（默认 9610）
//
// 基础改造（融入 mercari 系统，源自 github.com/Gosoki/mercari-proxy）：
//   1) /__inject（内部）：后端把账号 Cookie 以一次性 token 暂存到本进程内存，
//      需 x-internal-secret 头匹配 MERCARI_PROXY_INTERNAL_SECRET。
//   2) <BASE>/__boot?token=xxx：用户本地浏览器打开此地址，本服务把对应 Cookie
//      通过 Set-Cookie 写到代理域名下，然后 302 跳到 <BASE>/ ——于是已登录态注入完成。
//   3) BASE_PATH：可选子路径前缀（默认空=根挂载）。根挂载时 SPA 导航/刷新/前进后退
//      均正常，是该项目的原始设计与本系统采用的部署方式。
// ============================================================
const http = require("http");
const tls = require("tls");
const { Readable } = require("stream");

const PORT = Number(process.env.PORT) || 9610;
const BIND_HOST = process.env.BIND_HOST || "127.0.0.1";

// 挂载基础路径（无尾斜杠）。默认空 = 根路径（与原版行为一致）。
const BASE = (process.env.BASE_PATH || "").replace(/\/+$/, "");

// 内部注入密钥（后端调用 /__inject 时校验）；为空则不校验（仅本机可达时可接受）。
const INTERNAL_SECRET = process.env.MERCARI_PROXY_INTERNAL_SECRET || "";

// 默认上游（日本站 jp.mercari.com / 美区 www.mercari.com）
const DEFAULT_UPSTREAM = process.env.UPSTREAM || "jp.mercari.com";

// 需要代理的上游域名（按 hostname 匹配）；要加 CDN 就往这里加
const UPSTREAM_RE = /(^|\.)(mercari\.com|mercari\.jp|mercdn\.net|mercari-shops\.com)$/i;
const UPSTREAM_RE_SRC = "(^|\\.)(mercari\\.com|mercari\\.jp|mercdn\\.net|mercari-shops\\.com)$";

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

// 仅允许环回地址访问（含登录态注入，限制为本机）。
function isLoopback(req) {
  const a = (req.socket && req.socket.remoteAddress) || "";
  return a === "127.0.0.1" || a === "::1" || a === "::ffff:127.0.0.1";
}

// ---------------- Cookie 注入暂存（一次性 token） ----------------
const injectionStore = new Map(); // token -> { cookies: [{name,value,httpOnly}], expires: ms }

function pruneInjections() {
  const now = Date.now();
  for (const [k, v] of injectionStore) {
    if (!v || v.expires <= now) injectionStore.delete(k);
  }
}

const handler = async (req, res) => {
  try {
    if (!isLoopback(req)) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      return res.end("forbidden: loopback only");
    }
    const PROXY_HOST = req.headers.host || `localhost:${PORT}`;
    const reqUrl = new URL(req.url, `http://${PROXY_HOST}`);
    const path = reqUrl.pathname;

    // 1) CORS 预检
    if (req.method === "OPTIONS") {
      res.writeHead(204, corsHeaders(req));
      return res.end();
    }

    // 2) 内部注入端点（后端 → 本进程，不经 BASE 前缀；浏览器经 Vite 只能到 BASE 下，触达不到）
    if (path === "/__inject") return handleInject(req, res);

    // 3) Cookie 注入引导页：写 Cookie 后跳转进代理站
    if (path === `${BASE}/__boot`) return handleBoot(req, res, reqUrl, PROXY_HOST);

    // 4) 解析上游目标（先剥离 BASE 前缀）
    let rel = BASE && path.startsWith(BASE) ? path.slice(BASE.length) : path;
    if (rel === "") rel = "/";
    const { upstreamHost, upstreamPath } = resolveTarget(rel);
    const upstreamUrl = `https://${upstreamHost}${upstreamPath}${reqUrl.search}`;

    // 5) 组装转发请求头（DPoP / Authorization / Cookie 原样透传）
    const fwd = {};
    for (const [k, v] of Object.entries(req.headers)) {
      const lk = k.toLowerCase();
      if (DROP_REQ_HEADERS.has(lk)) continue;
      if (lk.startsWith("cf-") || lk.startsWith("x-forwarded-") || lk === "x-real-ip") continue;
      fwd[k] = v;
    }
    const SITE = `https://${DEFAULT_UPSTREAM}`;
    if (fwd["origin"]) fwd["origin"] = SITE;
    if (fwd["referer"]) {
      fwd["referer"] = fwd["referer"]
        .split(PROXY_HOST).join(DEFAULT_UPSTREAM)
        .replace(new RegExp(`^https?://${DEFAULT_UPSTREAM}${escapeReg(BASE)}/__p/[^/]+/`), "https://" + DEFAULT_UPSTREAM + "/");
    }

    // 6) body
    const hasBody = !["GET", "HEAD"].includes(req.method);
    const body = hasBody ? await readBody(req) : undefined;

    const resp = await fetch(upstreamUrl, {
      method: req.method,
      headers: fwd,
      body,
      redirect: "manual",
    });

    // 7) 处理响应头
    const outHeaders = {};
    for (const [k, v] of resp.headers) {
      if (k.toLowerCase() === "set-cookie") continue;
      if (DROP_RESP_HEADERS.has(k.toLowerCase())) continue;
      outHeaders[k] = v;
    }
    stripSecurityHeaders(outHeaders);
    applyCors(outHeaders, req);
    const cookies = rewriteSetCookie(resp);
    if (cookies.length) outHeaders["set-cookie"] = cookies;
    rewriteLocation(outHeaders, upstreamHost, PROXY_HOST);

    const ctype = (resp.headers.get("content-type") || "").toLowerCase();

    // 8) HTML：注入运行时劫持脚本 + 改写绝对 URL 属性
    if (ctype.includes("text/html")) {
      let html = await resp.text();
      html = injectAndRewriteHtml(html, PROXY_HOST);
      res.writeHead(resp.status, outHeaders);
      return res.end(html);
    }

    // 9) JS：仅当配置了补丁时才改（默认不动，保住 DPoP htu）
    const isJs = ctype.includes("javascript") || new URL(upstreamUrl).pathname.endsWith(".js");
    if (JS_PATCHES.length && isJs) {
      let text = await resp.text();
      for (const p of JS_PATCHES) text = text.split(p.from).join(p.to);
      res.writeHead(resp.status, outHeaders);
      return res.end(text);
    }

    // 10) 其它原样透传（流式）
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
  if (!token || !cookies.length) {
    res.writeHead(400, { "content-type": "text/plain" });
    return res.end("missing token or cookies");
  }
  pruneInjections();
  injectionStore.set(token, { cookies, expires: Date.now() + ttlSec * 1000 });
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
  const setCookies = entry.cookies.map((c) => {
    let s = `${c.name}=${c.value}; Path=${cookiePath}; SameSite=Lax`;
    if (c.httpOnly) s += "; HttpOnly";
    return s;
  });
  res.writeHead(302, {
    "set-cookie": setCookies,
    location: `${BASE}/`,
    "cache-control": "no-store",
    // token 走 query string（用户浏览器要直接导航过来，没法用 POST 交接）。它是一次性的
    // ——上面 injectionStore.delete 已经把它作废了——但在被使用前的 TTL 窗口内，这个 URL
    // 会留在浏览器历史里。no-referrer 保证它至少不会随后续请求的 Referer 头外泄出去。
    "referrer-policy": "no-referrer",
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
  if (!isLoopback(req)) return clientSock.destroy();
  const wsPath = BASE && req.url.startsWith(BASE) ? req.url.slice(BASE.length) : req.url;
  const m = wsPath.match(/^\/__pws__\/([^/]+)(\/.*)?$/);
  if (!m) return clientSock.destroy();
  const host = m[1];
  const path = m[2] || "/";
  const upstream = tls.connect(443, host, { servername: host }, () => {
    const lines = [`GET ${path} HTTP/1.1`, `Host: ${host}`];
    for (const [k, v] of Object.entries(req.headers)) {
      const lk = k.toLowerCase();
      if (lk === "host") continue;
      if (lk === "origin") { lines.push(`Origin: https://${DEFAULT_UPSTREAM}`); continue; }
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
// /__p/<host>/<path...> => https://<host>/<path...>；其它走默认上游（rel 已剥离 BASE）
function resolveTarget(rel) {
  const m = rel.match(/^\/__p\/([^/]+)(\/.*)?$/);
  if (m) return { upstreamHost: m[1], upstreamPath: m[2] || "/" };
  return { upstreamHost: DEFAULT_UPSTREAM, upstreamPath: rel };
}

function toProxyUrl(absUrl, proxyHost) {
  try {
    const u = new URL(absUrl);
    if (u.hostname === proxyHost) return absUrl;
    if (!UPSTREAM_RE.test(u.hostname)) return absUrl;
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

function corsHeaders(req) {
  return {
    "access-control-allow-origin": req.headers["origin"] || "*",
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET,POST,PUT,DELETE,PATCH,OPTIONS",
    "access-control-allow-headers": req.headers["access-control-request-headers"] || "*",
    "access-control-max-age": "86400",
  };
}
function applyCors(h, req) {
  h["access-control-allow-origin"] = req.headers["origin"] || "*";
  h["access-control-allow-credentials"] = "true";
  h["access-control-expose-headers"] = "*";
}

// 去掉 Domain，下放 Secure/SameSite；BASE 非空时把 Path 收敛到 BASE，避免 Cookie 外溢到 SPA。
function rewriteSetCookie(resp) {
  const cookies = typeof resp.headers.getSetCookie === "function" ? resp.headers.getSetCookie() : [];
  return cookies.map((c) => {
    let out = c
      .replace(/;\s*Domain=[^;]+/i, "")
      .replace(/;\s*Secure/i, "")
      .replace(/;\s*SameSite=None/i, "; SameSite=Lax");
    if (BASE) {
      if (/;\s*Path=[^;]*/i.test(out)) out = out.replace(/;\s*Path=[^;]*/i, `; Path=${BASE}`);
      else out += `; Path=${BASE}`;
    }
    return out;
  });
}

function rewriteLocation(h, upstreamHost, proxyHost) {
  const key = Object.keys(h).find((k) => k.toLowerCase() === "location");
  if (!key) return;
  const loc = h[key];
  let abs = loc;
  if (loc.startsWith("//")) abs = "https:" + loc;
  else if (loc.startsWith("/")) abs = `https://${upstreamHost}${loc}`;
  h[key] = toProxyUrl(abs, proxyHost);
}

// ---------------- HTML 注入 + 属性改写 ----------------
function injectAndRewriteHtml(html, proxyHost) {
  html = html.replace(/\b(src|href)\s*=\s*("|')(.*?)\2/gi, (full, attr, q, val) => {
    let nv = val;
    if (/^https?:\/\//i.test(val)) nv = toProxyUrl(val, proxyHost);
    else if (val.startsWith("//")) nv = toProxyUrl("https:" + val, proxyHost);
    return `${attr}=${q}${nv}${q}`;
  });
  html = html.replace(/\bsrcset\s*=\s*("|')(.*?)\1/gi, (full, q, val) => {
    const nv = val.split(",").map((part) => {
      const seg = part.trim();
      const sp = seg.indexOf(" ");
      const url = sp === -1 ? seg : seg.slice(0, sp);
      const desc = sp === -1 ? "" : seg.slice(sp);
      let nu = url;
      if (/^https?:\/\//i.test(url)) nu = toProxyUrl(url, proxyHost);
      else if (url.startsWith("//")) nu = toProxyUrl("https:" + url, proxyHost);
      return nu + desc;
    }).join(", ");
    return `srcset=${q}${nv}${q}`;
  });
  const tag = `<script>${buildClientScript(proxyHost)}</script>`;
  const m = html.match(/<head[^>]*>/i);
  if (m) {
    const idx = m.index + m[0].length;
    return html.slice(0, idx) + tag + html.slice(idx);
  }
  return tag + html;
}

// ---------------- 注入页面的运行时劫持脚本 ----------------
function buildClientScript(proxyHost) {
  return `
(function(){
  var PROXY=${JSON.stringify(proxyHost)};
  var BASE=${JSON.stringify(BASE)};
  var RE=new RegExp(${JSON.stringify(UPSTREAM_RE_SRC)},"i");
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
  console.log(`默认上游: ${DEFAULT_UPSTREAM}  BASE_PATH: ${BASE || "(none)"}`);
});
