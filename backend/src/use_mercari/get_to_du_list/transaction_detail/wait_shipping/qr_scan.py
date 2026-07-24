# -*- coding: utf-8 -*-
"""wait-shipping: QR scan entry + remote camera inject/push"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict
from ....sync.sync_progress import set_sync_progress
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.paths import mercari_todo_key

log = logging.getLogger(__name__)


# ゆうパケットポスト / ゆうパケットポストmini 完了後、交易ページに出る「2次元コードを読み取る」
# （这是“调用摄像头扫描”的入口，仅 ゆうパケットポスト系 使用）
_SCAN_QR_BUTTON_TEXT = "2次元コードを読み取る"

# /qr_code_scanner 上の撮影開始ボタン（カメラ無効時は disabled）
_SCAN_START_BUTTON_TEXT = "QRコードをスキャンする"

# 読み取り成功後の交易ページ上の発送確定 UI
_SCAN_OK_TEXT = "読み取りが正しく完了しました"

#: 喂图等待煤炉读出的超时（秒）。静态照片能读就是一两秒的事；读不出再等也没用，
#: 与其让任务挂在那里，不如尽快失败让用户重拍。
SCAN_TIMEOUT_SEC = 10.0

# ─── 远程摄像头注入 ───────────────────────────────────────────────
# 服务器没有摄像头：在 QR スキャナページに入る前に、navigator.mediaDevices の
# getUserMedia / enumerateDevices を差し替え、canvas.captureStream() を「カメラ」として返す。
# 客户端（管理 UI を開いているユーザー端末）のカメラ映像を window.__pushCameraFrame(dataUrl,w,h)
# で逐次この canvas に描画 → スキャナはあたかもローカルカメラがあるかのように QR を読み取る。
_FAKE_CAMERA_JS = r"""
(() => {
  try {
    if (window.__remoteCamInstalled) return true;
    window.__remoteCamInstalled = true;
    var canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 480;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    var stream = null;
    window.__remoteCamCanvas = canvas;
    window.__pushCameraFrame = function (dataUrl, w, h) {
      try {
        if (!dataUrl) return false;
        var img = new Image();
        img.onload = function () {
          try {
            if (w && h && (canvas.width !== w || canvas.height !== h)) {
              canvas.width = w; canvas.height = h;
            }
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          } catch (e) {}
        };
        img.src = dataUrl;
        return true;
      } catch (e) { return false; }
    };
    function getStream() {
      if (!stream) { stream = canvas.captureStream(30); }
      return stream;
    }
    if (!navigator.mediaDevices) { try { navigator.mediaDevices = {}; } catch (e) {} }
    var md = navigator.mediaDevices;
    if (md) {
      var origGUM = md.getUserMedia ? md.getUserMedia.bind(md) : null;
      md.getUserMedia = function (constraints) {
        if (constraints && constraints.video) {
          try { return Promise.resolve(getStream()); } catch (e) { return Promise.reject(e); }
        }
        return origGUM ? origGUM(constraints) : Promise.reject(new Error('no media'));
      };
      var origEnum = md.enumerateDevices ? md.enumerateDevices.bind(md) : null;
      md.enumerateDevices = function () {
        var fake = { deviceId: 'remote-virtual-cam', kind: 'videoinput', label: 'Remote Camera', groupId: 'remote' };
        fake.toJSON = function () { return this; };
        if (origEnum) {
          return origEnum().then(function (list) {
            var others = (list || []).filter(function (d) { return d.kind !== 'videoinput'; });
            return [fake].concat(others);
          }).catch(function () { return [fake]; });
        }
        return Promise.resolve([fake]);
      };
    }
    return true;
  } catch (e) { return false; }
})();
"""

async def _click_scan_qr_and_open_scanner(
    page: Any,
    *,
    item_id: str,
    report,
) -> bool:
    """交易ページに戻った後「2次元コードを読み取る」を押して /qr_code_scanner へ遷移。

    成功で True。ボタンが無い（既に発送済み等）場合は False を返す。
    """
    # 完了する後、交易ページ /transaction/{item_id} に戻るのを待つ
    try:
        await page.wait_for_url("**/transaction/*", timeout=10000)
    except Exception:
        log.warning("[shipping] 完了後に交易ページへ戻る遷移を観測できず (URL: %s)", page.url)
    # SPA 再描画待ち
    await asyncio.sleep(0.6)

    # 远程摄像头注入：服务器无摄像头 → 把「客户端推送的帧」当作本地摄像头喂给 QR スキャナ。
    # ・add_init_script: ハードナビゲーション（新ドキュメント）に効く
    # ・evaluate: SPA ソフトナビ（同一ドキュメント内でルート遷移）に効く
    # スキャナページがマウント時に enumerateDevices を見るため、遷移「前」に仕込む。
    try:
        await page.add_init_script(_FAKE_CAMERA_JS)
    except Exception as exc:
        log.debug("[qrcam] add_init_script 失敗: %s", exc)
    try:
        await page.evaluate(_FAKE_CAMERA_JS)
    except Exception as exc:
        log.debug("[qrcam] evaluate 注入失敗: %s", exc)

    report("click_scan_qr", "正在点击「2次元コードを読み取る」…")
    scan_btn = page.get_by_role("button", name=_SCAN_QR_BUTTON_TEXT)
    try:
        await scan_btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        scan_btn = page.locator(f'button:has-text("{_SCAN_QR_BUTTON_TEXT}")')
        try:
            await scan_btn.first.wait_for(state="visible", timeout=4000)
        except Exception:
            log.warning(
                "[shipping] 「%s」ボタンが見つからず (URL: %s)",
                _SCAN_QR_BUTTON_TEXT,
                page.url,
            )
            return False
    await scan_btn.first.click()
    log.info("[shipping] 已点击「%s」", _SCAN_QR_BUTTON_TEXT)
    try:
        await page.wait_for_url("**/qr_code_scanner*", timeout=8000)
    except Exception:
        log.warning("[shipping] /qr_code_scanner への遷移を観測できず (URL: %s)", page.url)

    # スキャナ到達後：念のため再注入（ソフトナビ後でも window に効くよう）し、
    # 撮影開始ボタン「QRコードをスキャンする」が有効なら押してカメラを起動させる。
    await asyncio.sleep(0.6)
    try:
        await page.evaluate(_FAKE_CAMERA_JS)
    except Exception:
        pass
    try:
        start_btn = page.get_by_role("button", name=_SCAN_START_BUTTON_TEXT)
        if await start_btn.count() == 0:
            start_btn = page.locator(f'button:has-text("{_SCAN_START_BUTTON_TEXT}")')
        if await start_btn.count() > 0:
            b = start_btn.first
            if await b.is_visible() and await b.is_enabled():
                await b.click()
                log.info("[qrcam] 已点击「%s」启动摄像头", _SCAN_START_BUTTON_TEXT)
    except Exception as exc:
        log.debug("[qrcam] 開始ボタン押下スキップ: %s", exc)
    return True

async def push_remote_camera_frame(
    todo_id: int,
    *,
    frame: str = "",
    width: int = 0,
    height: int = 0,
) -> Dict[str, Any]:
    """客户端摄像头帧 → 注入到有头浏览器的「虚拟摄像头」canvas（QR スキャナ用）。

    返回值同时携带扫描状态，供前端判断是否停止推流：
      - ``on_scanner``: 仍在 /qr_code_scanner（继续推流）
      - ``done``: 已离开扫描页回到 /transaction/（读取成功）
      - ``pushed``: 本帧是否成功写入页面 canvas
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    url = ""
    try:
        url = (page.url or "").strip()
    except Exception:
        url = ""
    on_scanner = "/qr_code_scanner" in url
    done = (not on_scanner) and "/transaction/" in url

    pushed = False
    if frame and on_scanner:
        try:
            pushed = bool(
                await page.evaluate(
                    "(a) => (typeof window.__pushCameraFrame === 'function')"
                    " ? window.__pushCameraFrame(a.f, a.w, a.h) : false",
                    {"f": frame, "w": int(width or 0), "h": int(height or 0)},
                )
            )
        except Exception as exc:
            log.debug("[qrcam] フレーム注入失敗: %s", exc)

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "on_scanner": on_scanner,
        "done": done,
        "url": url,
        "pushed": pushed,
    }

async def feed_photo_until_scanned(
    todo_id: int,
    photo: str,
    *,
    timeout_sec: float = SCAN_TIMEOUT_SEC,
    interval_sec: float = 0.4,
    progress_job_id: str = "",
) -> Dict[str, Any]:
    """把**一张**照片反复喂给煤炉的 QR スキャナ，直到它读出二维码（或超时）。

    与逐帧推流的区别：客户端只拍一次，之后不需要保持页面打开。虚拟摄像头 canvas 每隔
    ``interval_sec`` 重绘同一张图，扫描器把它当作静止画面的实时视频流去解码——
    它内部按帧轮询解码，因此静止画同样能读出。

    读取成功的判定沿用既有口径：页面离开 ``/qr_code_scanner`` 回到 ``/transaction/``。

    :returns: ``{done, elapsed_sec, pushes, url}``；``done=False`` 表示超时未读出。
    """
    def report(step: str, label: str) -> None:
        if progress_job_id:
            try:
                set_sync_progress(progress_job_id, step, label)
            except Exception:
                pass

    loop = asyncio.get_running_loop()
    started = loop.time()
    pushes = 0
    last_url = ""
    while loop.time() - started < timeout_sec:
        res = await push_remote_camera_frame(
            int(todo_id), frame=photo, width=0, height=0
        )
        last_url = str(res.get("url") or "")
        if res.get("pushed"):
            pushes += 1
        if res.get("done"):
            elapsed = loop.time() - started
            log.info(
                "[qrphoto] todo=%s 二维码已被读取（耗时 %.1fs，推送 %d 次）",
                todo_id, elapsed, pushes,
            )
            report("qr_scanned", "二维码已读取，正在获取发货信息…")
            return {"done": True, "elapsed_sec": round(elapsed, 1), "pushes": pushes, "url": last_url}
        if not res.get("on_scanner") and not res.get("done"):
            # 既不在扫描页也没回到交易页：页面被关掉或跳去了别处，再等也没意义
            log.warning("[qrphoto] todo=%s 已离开扫描页且未完成（URL=%s）", todo_id, last_url)
            break
        elapsed = loop.time() - started
        report("qr_feeding", f"正在识别二维码…（已用时 {int(elapsed)}s）")
        await asyncio.sleep(interval_sec)

    elapsed = loop.time() - started
    log.warning(
        "[qrphoto] todo=%s 未能读出二维码（耗时 %.1fs，推送 %d 次，URL=%s）",
        todo_id, elapsed, pushes, last_url,
    )
    return {"done": False, "elapsed_sec": round(elapsed, 1), "pushes": pushes, "url": last_url}


async def capture_qr_scanner_frame(todo_id: int) -> Dict[str, Any]:
    """QR スキャナ（/qr_code_scanner）を開いている有頭ブラウザの現在タブを
    JPEG スクリーンショットで取得し、base64 で返す（管理 UI へミラー表示用）。

    返り値:
      - ``frame``: data URI 文字列（``data:image/jpeg;base64,...``）。取得不可なら None
      - ``on_scanner``: 現在 /qr_code_scanner 上にいるか
      - ``done``: スキャン完了（/qr_code_scanner を離れ /transaction/ に戻った）
      - ``url``: 現在 URL
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    url = ""
    try:
        url = (page.url or "").strip()
    except Exception:
        url = ""
    on_scanner = "/qr_code_scanner" in url
    # スキャナを開いた後にスキャナを離れて transaction に戻った＝読み取り成功とみなす
    done = (not on_scanner) and "/transaction/" in url

    frame = None
    try:
        import base64

        # 摄像头/取景框のみを切り出す（ページ全体・ヘッダ・余白は不要）。
        # 取れない時のみページ全体にフォールバック。
        shot = None
        for sel in ('[data-testid="qr-code-scanner-from-camera"]', "#video"):
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    shot = await loc.first.screenshot(type="jpeg", quality=55)
                    break
            except Exception:
                continue
        if shot is None:
            shot = await page.screenshot(type="jpeg", quality=55)
        frame = "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii")
    except Exception as exc:
        log.debug("[qrscan] スクリーンショット取得失敗: %s", exc)

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "frame": frame,
        "on_scanner": on_scanner,
        "done": done,
        "url": url,
    }
