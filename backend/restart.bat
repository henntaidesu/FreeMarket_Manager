@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
cd /d "%ROOT%"

REM 发布目录：与 FreeMarket Manager.exe 同级时走生产重启
if exist "%ROOT%FreeMarket Manager.exe" (
  cd /d "%ROOT%"
  goto :prod_inline
)

REM Releases\版本号\ 等子目录发布包（优先使用该目录下的 restart.bat）
for /d %%D in ("%ROOT%Releases\*") do (
  if exist "%%D\FreeMarket Manager.exe" (
    if exist "%%D\restart.bat" (
      call "%%D\restart.bat"
      exit /b %errorlevel%
    )
    cd /d "%%D"
    goto :prod_inline
  )
)

echo ========================================
echo   mercari 开发环境 — 重启后端
echo ========================================
echo.

set "BACKEND_PORT=9601"
set "MERCARI_PORT=%BACKEND_PORT%"

echo [1/2] 停止占用 %BACKEND_PORT% 端口的进程...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$port=%BACKEND_PORT%; Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo [2/2] 启动后端 uvicorn...
where conda >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 conda，请先安装 Anaconda/Miniconda 并创建 mercari 环境。
  pause
  exit /b 1
)
call conda activate mercari
if errorlevel 1 (
  echo [错误] 无法激活 conda 环境 mercari
  pause
  exit /b 1
)

cd /d "%ROOT%backend"
start "mercari-backend" cmd /c "conda activate mercari && python -m uvicorn main:app --host 0.0.0.0 --port %BACKEND_PORT%"

echo 等待后端就绪...
set /a _n=0
:wait_dev_health
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%BACKEND_PORT%/api/health' -UseBasicParsing -TimeoutSec 2; exit ([int]($r.StatusCode -ne 200)) } catch { exit 1 }" 2>nul
if %errorlevel% equ 0 goto dev_done
set /a _n+=1
if %_n% geq 60 (
  echo [警告] 健康检查超时，请查看 mercari-backend 窗口。
  goto dev_done
)
timeout /t 1 /nobreak >nul
goto wait_dev_health

:dev_done
echo.
echo 后端已重启: http://127.0.0.1:%BACKEND_PORT%/
echo 前端 dev 需单独在 webside 目录运行 npm run dev ^(端口 9600^)。
echo.
pause
exit /b 0

:prod_inline
set "PORT=%MERCARI_PORT%"
if "%PORT%"=="" set "PORT=9601"
set "MERCARI_PORT=%PORT%"

echo ========================================
echo   FreeMarket Manager — 重启系统
echo   端口: %PORT%
echo ========================================
echo.

echo [1/3] 正在停止 FreeMarket Manager...
taskkill /IM "FreeMarket Manager.exe" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq FreeMarket Manager*" /F >nul 2>&1

echo [2/3] 等待服务退出...
set /a _n=0
:wait_down_inline
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/api/health' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" 2>nul
if %errorlevel% neq 0 goto start_inline
set /a _n+=1
if %_n% geq 30 goto force_wait_inline
timeout /t 1 /nobreak >nul
goto wait_down_inline

:force_wait_inline
timeout /t 2 /nobreak >nul

:start_inline
echo [3/3] 正在启动 FreeMarket Manager...
start "FreeMarket Manager" "%~dp0FreeMarket Manager.exe"

set /a _n=0
:wait_health_inline
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/api/health' -UseBasicParsing -TimeoutSec 2; exit ([int]($r.StatusCode -ne 200)) } catch { exit 1 }" 2>nul
if %errorlevel% equ 0 goto done_inline
set /a _n+=1
if %_n% geq 90 goto done_inline
timeout /t 1 /nobreak >nul
goto wait_health_inline

:done_inline
echo.
echo 重启完成。访问: http://127.0.0.1:%PORT%/
echo.
pause
exit /b 0
