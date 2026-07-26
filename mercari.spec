# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec —— 主程序 mercariManager.exe（FastAPI + uvicorn，同端口提供 API 与前端）。

输出单文件 mercariManager.exe（windowed 无控制台；启动即显示运行窗口，点 X 可选「退出程序 /
收入任务栏」，见 src/log_window.py + src/tray.py）。前端 webside/dist
打入 exe，main.py 冻结后优先从 exe 同级目录读取，缺失时回退打入的产物。

环境变量 BUNDLE_OCR=1 时额外打入 easyocr/torch（体积巨大）；默认不打，OCR 端点会优雅提示未安装。
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

BACKEND = os.path.join(os.path.abspath(os.getcwd()), "backend")

datas = []
binaries = []
hiddenimports = []


def add_pkg(name):
    """尽力收集一个包（数据/二进制/隐藏导入）；包不存在则跳过，不让构建失败。"""
    try:
        d, b, h = collect_all(name)
    except Exception as exc:  # noqa: BLE001
        print(f"[mercari.spec] 跳过 {name}: {exc}")
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)
    print(f"[mercari.spec] 已收集 {name}: {len(d)} datas / {len(b)} binaries")


# 动态导入 / 含数据文件 / 二进制扩展的依赖
for pkg in ("uvicorn", "mitmproxy", "mitmproxy_rs", "playwright", "zxingcpp",
            "cryptography", "PIL", "multipart", "pystray"):
    add_pkg(pkg)

# uvicorn[standard] 的可选协议实现
hiddenimports += [
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "websockets.legacy",
    "httptools",
]

# backend.exe 自调用充当 mitmdump 的入口（main.py 顶部守卫会导入并运行）
hiddenimports += [
    "mitmproxy.tools.main",
    "mitmproxy.tools.dump",
]

# 运行窗口 src/log_window.py 使用 tkinter（import 写在函数里），显式声明确保 tcl/tk 被打入
hiddenimports += ["tkinter"]

# 业务源码（backend/src）整体打入，覆盖函数内的延迟 import
hiddenimports += collect_submodules("src")
hiddenimports = list(dict.fromkeys(hiddenimports))  # 去重

# src 下可能存在的非 .py 配置/数据文件
try:
    datas += collect_data_files(
        "src",
        includes=["**/*.json", "**/*.txt", "**/*.ini", "**/*.yaml", "**/*.yml", "**/*.pem"],
    )
except Exception as exc:  # noqa: BLE001
    print(f"[mercari.spec] collect_data_files(src) 跳过: {exc}")

# mitm_addon.py 需以「磁盘文件」形式存在，供子进程 mitmdump -s <addon> 加载
datas.append((
    os.path.join(BACKEND, "src", "ssl_mitm_proxy", "mitm_addon.py"),
    os.path.join("src", "ssl_mitm_proxy"),
))

# mercari_proxy/server.js 由 `node server.js` 子进程加载，需以磁盘文件形式打入
# （server_js_path() 用 os.path.dirname(__file__)/server.js，冻结后即 _MEIPASS/src/mercari_proxy/）
datas.append((
    os.path.join(BACKEND, "src", "mercari_proxy", "server.js"),
    os.path.join("src", "mercari_proxy"),
))

# 前端构建产物 webside/dist 整体打入 exe（onefile 运行时解压到 _MEIPASS/webside；
# web_static.py 优先读 exe 同级 webside/，缺失时回退到此打入产物）
WEBSIDE_DIST = os.path.join(os.path.abspath(os.getcwd()), "webside", "dist")
if os.path.isdir(WEBSIDE_DIST):
    for _dp, _ds, _fs in os.walk(WEBSIDE_DIST):
        for _f in _fs:
            _full = os.path.join(_dp, _f)
            _rel = os.path.relpath(_dp, WEBSIDE_DIST)
            _dest = "webside" if _rel == "." else os.path.join("webside", _rel)
            datas.append((_full, _dest))
    print("[mercari.spec] 已打入前端 webside/dist -> webside")
else:
    print("[mercari.spec] 警告：未找到 webside/dist，前端未打入（请先 npm run build）")

# 托盘图标 png 打入 _MEIPASS/static（tray.py 运行时读取）；并由其生成 exe 图标 .ico。
ICON_PNG = os.path.join(os.path.abspath(os.getcwd()), "webside", "public", "static", "mercari.png")
icon_arg = None
if os.path.isfile(ICON_PNG):
    datas.append((ICON_PNG, "static"))
    try:
        from PIL import Image
        ICON_ICO = os.path.join(os.path.abspath(os.getcwd()), "build", "mercari.ico")
        os.makedirs(os.path.dirname(ICON_ICO), exist_ok=True)
        Image.open(ICON_PNG).save(
            ICON_ICO,
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        icon_arg = ICON_ICO
        print(f"[mercari.spec] 已生成 exe 图标 {ICON_ICO}")
    except Exception as exc:  # noqa: BLE001
        print(f"[mercari.spec] exe 图标生成失败（使用默认图标）: {exc}")
else:
    print("[mercari.spec] 警告：未找到托盘图标 png，跳过图标打入")

# 可选：打入 OCR（torch 体系，约 2GB，启动变慢）
if os.environ.get("BUNDLE_OCR", "0").strip() == "1":
    for pkg in ("easyocr", "torch", "torchvision", "cv2", "skimage",
                "scipy", "numpy", "shapely", "pyclipper"):
        add_pkg(pkg)


a = Analysis(
    [os.path.join("backend", "main.py")],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[] if os.environ.get("BUNDLE_OCR", "0").strip() == "1"
    else ["easyocr", "torch", "torchvision", "cv2", "skimage", "scipy"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mercariManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=icon_arg,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
