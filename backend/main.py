# 单文件打包后 backend.exe 自调用充当 mitmdump：带 MERCARI_RUN_MITMDUMP=1 启动时，
# 在加载任何业务模块前切换到 mitmdump 入口并退出（见 src/ssl_mitm_proxy/runner.py）。
import os as _os

if _os.environ.get("MERCARI_RUN_MITMDUMP") == "1":
    from src._mitmdump_entry import run_mitmdump

    run_mitmdump()

# 打包为 windowed（无 CMD 黑框）后默认没有 stdout/stderr：尽早分配一个隐藏的日志控制台，
# 让后续所有日志/print 有真实控制台可写；再打开运行窗口（log_window）把这些输出同步显示出来，
# 双击 exe 即可看到运行日志，点 X 询问「退出程序 / 收入任务栏」。仅 Windows 冻结态生效。
import sys as _sys

if getattr(_sys, "frozen", False) and _sys.platform == "win32":
    try:
        from src.console_win import setup_hidden_console

        setup_hidden_console()
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.log_window import start as _start_log_window

        _start_log_window()
    except Exception:  # noqa: BLE001
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.use_web.image_storage import ensure_image_dir
from src.API import router as v2_router
from src.image_route import register_image_routes
from src.lifecycle import register_lifecycle
from src.web_static import mount_spa, register_health

WEB_DRIVE_FORCE_HEADED_DEBUG = False
  # 强制启用 headed 模式以兼容部分环境（如 Windows 打包后）无法正常使用无头模式的情况  

# /docs、/openapi.json 默认关闭（避免向 LAN 未认证暴露完整路由/参数）；
# 需要时设 MERCARI_ENABLE_DOCS=1 开启。
_ENABLE_DOCS = (_os.environ.get("MERCARI_ENABLE_DOCS") or "").strip().lower() in ("1", "true", "yes")
app = FastAPI(
    title="FreeMarket Manager",
    version="2.0.0",
    docs_url="/docs" if _ENABLE_DOCS else None,
    redoc_url="/redoc" if _ENABLE_DOCS else None,
    openapi_url="/openapi.json" if _ENABLE_DOCS else None,
)

# CORS：认证走 Authorization Bearer（非 Cookie），故默认允许任意来源但**关闭凭证**，
# 消除 "通配 origin + allow_credentials" 的危险组合，同时不影响外网/LAN 访问。
# 如需锁定来源：设 CORS_ORIGINS="https://host:9600,https://ip:9600"（逗号分隔），此时启用凭证。
_cors_env = (_os.environ.get("CORS_ORIGINS") or "").strip()
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    _cors_allow_credentials = True
else:
    _cors_origins = ["*"]
    _cors_allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /imges 由 src/image_route.py 提供：它先查图片资产映射，落在图床上的跳转过去，
# 仍在本地的照旧读盘。这里仍先建目录——本地后端与各类缓存（缩略图、煤炉图片）都要用它。
ensure_image_dir()
register_image_routes(app)

# 注册 V2 根路由 → /mercariV2/src/...
app.include_router(v2_router, prefix="/mercariV2")

# 生命周期事件、兼容健康检查、前端 SPA 静态托管
register_lifecycle(app, force_headed_debug=WEB_DRIVE_FORCE_HEADED_DEBUG)
register_health(app)
mount_spa(app)  # 须最后挂载：根路径 "/" 会兜底其余未匹配路由


if __name__ == "__main__":
    from src.server import run

    run(app)
