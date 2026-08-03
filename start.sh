#!/bin/bash
# mercari 开发启动脚本（Mac / Linux），等价于 Windows 的 start.bat
# 用法: ./start.sh    （首次需要: chmod +x start.sh）

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
WEBSIDE="$ROOT/webside"

echo "========================================"
echo "  mercari dev startup script (mac/linux)"
echo "========================================"
echo

# 前后端都只监听普通 HTTP；需要 HTTPS 请用 nginx 反代终止 TLS

# ---- 选择 Python 环境：优先 conda 的 mercari 环境，其次 backend/.venv（没有则自动创建）----
PYTHON=""
if command -v conda &>/dev/null; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  if conda activate mercari 2>/dev/null; then
    PYTHON="python"
    echo "[环境] 已激活 conda 环境 mercari"
  fi
fi

if [ -z "$PYTHON" ]; then
  if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.11+"
    exit 1
  fi
  if [ ! -d "$BACKEND/.venv" ]; then
    echo "[环境] 未找到 conda mercari 环境，自动创建 backend/.venv 虚拟环境..."
    python3 -m venv "$BACKEND/.venv" || { echo "[错误] 创建虚拟环境失败"; exit 1; }
    echo "[环境] 安装 Python 依赖（首次较慢，easyocr/torch 体积较大，请耐心等待）..."
    "$BACKEND/.venv/bin/python" -m pip install -r "$BACKEND/requirements.txt" || {
      echo "[错误] pip install 失败，请检查网络后重试"
      exit 1
    }
    echo "[提示] 如需 Mercari 浏览器自动化功能，还需安装 Edge 浏览器："
    echo "       $BACKEND/.venv/bin/python -m playwright install msedge"
  fi
  PYTHON="$BACKEND/.venv/bin/python"
fi

# ---- 检查 Node.js ----
if ! command -v node &>/dev/null; then
  echo "[错误] 未找到 Node.js，请安装: https://nodejs.org/"
  exit 1
fi
if ! command -v npm &>/dev/null; then
  echo "[错误] 未找到 npm，请检查 Node.js 安装"
  exit 1
fi

echo "[1/2] 启动后端 (python main.py) ..."
cd "$BACKEND" || exit 1
"$PYTHON" main.py &
BACKEND_PID=$!
# 前端退出（Ctrl+C）时一并关掉后端
trap 'kill $BACKEND_PID 2>/dev/null' EXIT

sleep 2

echo "[2/2] 准备前端开发服务器..."
cd "$WEBSIDE" || exit 1
npm install || { echo "[错误] npm install 失败，请检查网络或 package.json"; exit 1; }

echo
echo "========================================"
echo "  前端 (HTTP):  http://localhost:9600"
echo "  后端 API:  http://localhost:9601"
echo "  API 文档:  http://localhost:9601/docs"
echo "  按 Ctrl+C 停止"
echo "========================================"
echo

npm run dev
