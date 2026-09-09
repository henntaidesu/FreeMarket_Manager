# -*- coding: utf-8 -*-
"""图片存储门面：对上层保持 ``/imges/<文件名>`` 不变，对下决定字节落在本地盘还是图床。

**这里是整个图床对接唯一需要感知「后端是谁」的地方。** 上层二十多处
``startswith('/imges/')`` 判断、七个业务列里存的路径字符串、前端五个页面的取图逻辑，
一律不变——它们看到的始终是那个逻辑路径。哪张图实际在哪，由 ``image_assets`` 映射表回答
（见 ``db_manage/models/system/image_asset.py`` 的设计说明）。

**写入失败降级为本地。** 保存路径永远先落本地盘，再尝试上传图床；上传失败就把本地那份
留着、不写映射行，这张图照样能正常显示。图床临时不可用不该让用户的「保存商品」整个失败，
而遗留在本地的那些图，下次跑迁移（迁移是可重复的对账，不是一次性动作）会自动补上去。
"""
import base64
import io
import logging
import mimetypes
import os
import re
import uuid
from typing import Optional

from fastapi import UploadFile, HTTPException
from PIL import Image
from starlette.concurrency import run_in_threadpool

from src.app_paths import backend_root_str
from src.image_hosting import assets as image_assets
from src.image_hosting import settings as image_hosting_settings
from src.image_hosting.client import ImageHostingClient, ImageHostingError, public_url_for
from ._path_safety import resolve_within_imges

log = logging.getLogger(__name__)

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000


BASE64_IMAGE_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,", re.IGNORECASE)

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _backend_root() -> str:
    return backend_root_str()


def get_image_root() -> str:
    # 按需求使用 imges 目录名
    return os.path.join(_backend_root(), "imges")


def ensure_image_dir() -> str:
    root = get_image_root()
    os.makedirs(root, exist_ok=True)
    return root


def is_base64_image(value: Optional[str]) -> bool:
    if not value or not isinstance(value, str):
        return False
    return BASE64_IMAGE_RE.match(value.strip()) is not None


def _extension_from_data_url(data_url: str) -> str:
    m = BASE64_IMAGE_RE.match(data_url.strip())
    ext = (m.group(1).lower() if m else "jpg")
    if ext == "jpeg":
        return "jpg"
    return ext


def content_type_for(rel_path_or_name: str) -> str:
    """按扩展名给出 MIME 类型。

    先查上面那张小表，再回落到 ``mimetypes``：``/imges`` 以前是 StaticFiles 挂载，由它按
    扩展名猜类型；换成自己的路由后要是只认这五种，avif / bmp / ico 这些就会被当成
    ``application/octet-stream`` 送出去，浏览器直接下载而不是显示。
    """
    ext = rel_path_or_name.rsplit(".", 1)[-1].lower() if "." in rel_path_or_name else ""
    known = _CONTENT_TYPES.get(ext)
    if known:
        return known
    guessed, _ = mimetypes.guess_type(rel_path_or_name)
    return guessed or "application/octet-stream"


# ── 逻辑路径 ⇄ 本地文件 ────────────────────────────────────────────────── #


def local_abs_path(rel_path: Optional[str]) -> Optional[str]:
    """``/imges/xxx`` → 本地绝对路径；越界、非法或文件不存在时返回 None。"""
    if not rel_path or not isinstance(rel_path, str) or not rel_path.startswith("/imges/"):
        return None
    try:
        abs_path = resolve_within_imges(rel_path.strip(), get_image_root())
    except ValueError:
        return None
    return abs_path if os.path.isfile(abs_path) else None


def remote_mapping(rel_path: Optional[str]):
    """这张图在图床上的映射；None = 仍在本地。"""
    if not rel_path or not isinstance(rel_path, str) or not rel_path.startswith("/imges/"):
        return None
    return image_assets.lookup(rel_path.strip())


def public_image_url(rel_path: Optional[str], width: Optional[int] = None) -> Optional[str]:
    """浏览器可直连的图床 URL；返回 None 表示这张图仍该由本服务从本地盘提供。

    带 ``width`` 时用图床的缩略图端点：列表页一屏三十张图，让浏览器直接从图床取小图，
    既不占本服务的带宽，也不必先把原图整张拉回本地再缩放。
    """
    mapping = remote_mapping(rel_path)
    if not mapping:
        return None
    if width:
        return public_url_for(mapping["remote_slug"], mapping["remote_name"], width)
    return mapping["remote_url"] or public_url_for(mapping["remote_slug"], mapping["remote_name"])


def image_exists(rel_path: Optional[str]) -> bool:
    """这张图现在还取得到吗（本地文件在，或者已登记在图床上）。

    别用 ``os.path.exists`` 代替它：图片搬到图床后本地文件已经删掉，用存在性判断来决定
    「要不要重新下载一遍」的地方会全部误判成「不在了」。
    """
    if remote_mapping(rel_path):
        return True
    return local_abs_path(rel_path) is not None


def read_image_bytes(rel_path: Optional[str]) -> Optional[bytes]:
    """读回图片字节，本地/图床都能读。返回 None = 这张图取不到。

    图片搜索建索引、AI 出品、生成水印图这些**要真正看到像素**的功能都走这里；图片搬到
    图床之后，本地已经没有可 open() 的文件了。
    """
    mapping = remote_mapping(rel_path)
    if mapping:
        try:
            return ImageHostingClient().fetch_bytes(
                mapping["remote_url"] or public_url_for(mapping["remote_slug"], mapping["remote_name"])
            )
        except ImageHostingError as exc:
            log.warning("从图床读取 %s 失败：%s", rel_path, exc)
            return None
    abs_path = local_abs_path(rel_path)
    if not abs_path:
        return None
    try:
        with open(abs_path, "rb") as f:
            return f.read()
    except OSError as exc:
        log.warning("读取本地图片 %s 失败：%s", rel_path, exc)
        return None


# ── 写入 ──────────────────────────────────────────────────────────────── #


def _write_local(filename: str, content: bytes) -> str:
    ensure_image_dir()
    abs_path = os.path.join(get_image_root(), filename)
    with open(abs_path, "wb") as f:
        f.write(content)
    return abs_path


def upload_existing_to_host(rel_path: str, content: Optional[bytes] = None) -> bool:
    """把一张已有的图片推到图床并登记映射；成功后删掉本地那份。

    迁移和「新图上传后转存」共用这一段——两者做的是同一件事，差别只在谁来触发。
    ``external_key`` 用逻辑路径本身：图床侧据此幂等，迁移中断重跑不会产生第二份文件。
    """
    if content is None:
        abs_path = local_abs_path(rel_path)
        if not abs_path:
            return False
        with open(abs_path, "rb") as f:
            content = f.read()
    filename = rel_path.split("/imges/", 1)[1].strip("/")
    payload = ImageHostingClient().upload(
        filename=filename,
        content=content,
        content_type=content_type_for(filename),
        external_key=rel_path,
    )
    image_assets.record_remote(
        rel_path,
        slug=payload.get("project") or "",
        stored_name=payload["stored_name"],
        url=payload["url"],
        size=payload.get("size") or len(content),
        sha256=payload.get("sha256"),
    )
    # 映射写成功之后才删本地：顺序反过来的话，中间崩一次就既没有本地文件也没有映射行。
    abs_path = local_abs_path(rel_path)
    if abs_path:
        try:
            os.remove(abs_path)
        except OSError as exc:
            log.warning("图床转存成功但本地副本删除失败 %s：%s", rel_path, exc)
    return True


def _persist(filename: str, content: bytes, local_only: bool = False) -> str:
    """落盘并返回逻辑路径；当前后端是图床时再转存上去（失败则留在本地）。

    ``local_only`` 用于**短命的工作文件**（例如发货扫码那张照片：落盘、解码、任务跑完就删）。
    这类文件送上图床是纯粹的浪费，而且调用方是按绝对路径直接 open() 它们的——转存会把本地
    副本删掉，那些 open() 当场就失败。
    """
    _write_local(filename, content)
    rel_path = f"/imges/{filename}"
    if local_only or not image_hosting_settings.remote_enabled():
        return rel_path
    try:
        upload_existing_to_host(rel_path, content)
    except ImageHostingError as exc:
        # 有意只记日志不抛：图床临时不可用不该让「保存商品」整个失败。这张图留在本地
        # 照常可用，下次跑迁移会把它补传上去。
        log.warning("图片 %s 转存图床失败，暂留本地：%s", rel_path, exc)
    return rel_path


def save_base64_image(
    data_url: str, prefix: str = "product", max_bytes: int = 25 * 1024 * 1024,
    local_only: bool = False,
) -> str:
    """保存 data:image/...;base64,... ，返回可访问路径 /imges/xxx.ext"""
    ext = _extension_from_data_url(data_url)
    base64_data = data_url.split(",", 1)[1]
    image_bytes = base64.b64decode(base64_data)
    if len(image_bytes) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"图片不能超过{mb}MB")
    return _persist(f"{prefix}_{uuid.uuid4().hex}.{ext}", image_bytes, local_only=local_only)


async def save_upload_image(
    file: UploadFile, prefix: str = "file", max_bytes: int = 25 * 1024 * 1024
) -> str:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(content) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"图片不能超过{mb}MB")
    # 不信任客户端 Content-Type/文件名，实际校验字节是否为合法图片
    try:
        Image.open(io.BytesIO(content)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="请上传有效的图片文件")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        ext = "jpg"
    if ext == "jpeg":
        ext = "jpg"
    # _persist 里的上传是同步阻塞的网络调用；在 async 端点里直接跑会卡住事件循环，
    # 让同一时刻其它所有请求陪着一起等一次图床往返。
    return await run_in_threadpool(_persist, f"{prefix}_{uuid.uuid4().hex}.{ext}", content)


def save_image_bytes(content: bytes, ext: str = "png", prefix: str = "img") -> str:
    """保存原始图片字节，返回可访问路径 /imges/xxx.ext。"""
    e = (ext or "png").lower().lstrip(".")
    if e == "jpeg":
        e = "jpg"
    if e not in {"jpg", "png", "webp", "gif"}:
        e = "png"
    return _persist(f"{prefix}_{uuid.uuid4().hex}.{e}", content)


def duplicate_image(rel_path: Optional[str], prefix: str = "inv_split") -> Optional[str]:
    """复制一张图片，返回新的逻辑路径；取不到源图时原样返回入参。

    拆分库存 / 订单转库存都要复制图片，避免两条记录共享同一个文件——删其中一条会把另一条
    的图也删掉。本地后端下这是一次 copy，图床后端下是「下载再上传」。
    """
    if not rel_path or not isinstance(rel_path, str) or not rel_path.startswith("/imges/"):
        return rel_path
    filename = rel_path.split("/imges/", 1)[1].strip("/")
    if not filename:
        return rel_path
    content = read_image_bytes(rel_path)
    if content is None:
        return rel_path
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    try:
        return save_image_bytes(content, ext=ext, prefix=prefix)
    except Exception as exc:  # noqa: BLE001
        log.warning("复制图片 %s 失败：%s", rel_path, exc)
        return rel_path


def delete_image_file(path_or_url: Optional[str]) -> None:
    if not path_or_url or not isinstance(path_or_url, str):
        return
    val = path_or_url.strip()
    if not val.startswith("/imges/"):
        return
    mapping = remote_mapping(val)
    if mapping:
        try:
            ImageHostingClient().delete(mapping["remote_name"])
        except ImageHostingError as exc:
            # 远程删不掉就保留映射行：删了行而远程文件还在，那张图就再没有任何记录指向它，
            # 永远清不掉了。保留下来至少还能重试。
            log.warning("删除图床图片 %s 失败：%s", val, exc)
            return
        image_assets.forget(val)
    # realpath 包含性校验：拦截 ..、Windows 盘符、UNC 等越界写法，越界即拒绝删除
    abs_path = local_abs_path(val)
    if abs_path:
        os.remove(abs_path)
