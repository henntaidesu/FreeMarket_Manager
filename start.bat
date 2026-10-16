@echo off
setlocal enabledelayedexpansion
echo ========================================
echo   FreeMarket Manager - dev startup
echo ========================================
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "WEBSIDE=%ROOT%webside"
set "ENV_NAME=mercari"
set "WEB_PORT=9600"
set "API_PORT=9601"

rem HTTP by default; System Config - Web access = Direct HTTPS makes both servers use a self-signed cert.

rem ---- conda activate ----
call conda activate %ENV_NAME% >nul 2>&1
if /i "%CONDA_DEFAULT_ENV%"=="%ENV_NAME%" goto :conda_ok
rem Without "conda init cmd.exe", "conda" resolves to Scripts\conda.exe, which cannot activate.
rem Fall back to the activate.bat next to it.
set "CONDA_ACT="
for /f "delims=" %%C in ('where conda 2^>nul') do if not defined CONDA_ACT if exist "%%~dpCactivate.bat" set "CONDA_ACT=%%~dpCactivate.bat"
if defined CONDA_ACT call "%CONDA_ACT%" %ENV_NAME%
if /i "%CONDA_DEFAULT_ENV%"=="%ENV_NAME%" goto :conda_ok

rem ---- env not found, create it ----
where conda >nul 2>&1
if errorlevel 1 (
    echo [ERROR] conda not on PATH. Install Miniconda: https://www.anaconda.com/download/success
    pause
    exit /b 1
)
echo [*] Env "%ENV_NAME%" not found, creating ...
call conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main >nul 2>&1
call conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r >nul 2>&1
call conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/msys2 >nul 2>&1
call conda create -y -n %ENV_NAME% python=3.12
if errorlevel 1 (
    echo [ERROR] conda create failed.
    pause
    exit /b 1
)
call conda activate %ENV_NAME% >nul 2>&1
if /i not "%CONDA_DEFAULT_ENV%"=="%ENV_NAME%" (
    if defined CONDA_ACT call "%CONDA_ACT%" %ENV_NAME%
)
if /i not "%CONDA_DEFAULT_ENV%"=="%ENV_NAME%" (
    echo [ERROR] Env created but activation failed. Check: conda env list
    pause
    exit /b 1
)
echo [*] Installing backend deps ^(first run is slow: torch/easyocr are large^) ...
python -m pip install -r "%ROOT%requirements.txt"
if errorlevel 1 (
    echo [ERROR] pip install failed. Fix the network and re-run; the env is kept.
    echo         Or remove it to start over: conda env remove -n %ENV_NAME%
    pause
    exit /b 1
)
:conda_ok
for /f "delims=" %%P in ('where python') do echo Using python: %%P& goto :py_shown
:py_shown

rem ---- node check (before starting the backend, so a failure leaves nothing running) ----
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js: https://nodejs.org/
    pause
    exit /b 1
)

rem ---- stale backend ----
rem A backend left over from a killed window still holds the port, and the new one would fail to bind.
rem /T also takes its children (mitmdump, the Node mercari-proxy, automation browsers).
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%API_PORT% " ^| findstr LISTENING') do (
    echo [*] Port %API_PORT% is held by PID %%a, stopping it ...
    taskkill /T /F /PID %%a >nul 2>&1
)

rem ---- backend ----
echo [1/2] Starting backend ^(python main.py^) ...
pushd "%BACKEND%"
start "FreeMarket-Backend" /b python main.py
popd

timeout /t 2 /nobreak >nul

rem ---- frontend ----
echo [2/2] Preparing frontend dev server ...
pushd "%WEBSIDE%"
if not exist "node_modules" (
    echo Installing frontend deps ...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed. Check the network or package.json
        popd
        goto :stop_backend
    )
)

rem The backend records the scheme it actually listens on (Web access = Direct HTTPS -> https).
set "SCHEME=http"
findstr /c:"\"https\": true" "%BACKEND%\data\web_tls\state.json" >nul 2>&1 && set "SCHEME=https"

echo.
echo ========================================
echo   Frontend:  %SCHEME%://localhost:%WEB_PORT%
echo   Backend :  %SCHEME%://localhost:%API_PORT%
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "LANIP=%%i"
    set "LANIP=!LANIP: =!"
    echo   LAN     :  %SCHEME%://!LANIP!:%WEB_PORT%
)
netsh advfirewall firewall show rule name="FreeMarket Manager dev frontend %WEB_PORT%" >nul 2>&1
if errorlevel 1 (
    echo   [^^!] No firewall rule - other devices will time out.
    echo       Run open_firewall.bat once as administrator.
)
echo   Close this window or press Ctrl+C to stop both.
echo ========================================
echo.

call npm run dev
popd

:stop_backend
echo.
echo Stopping backend on port %API_PORT% ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%API_PORT% " ^| findstr LISTENING') do taskkill /T /F /PID %%a >nul 2>&1
endlocal
