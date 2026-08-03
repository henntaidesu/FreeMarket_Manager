@echo off
echo ========================================
echo   mercari dev startup script
echo ========================================
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set WEBSIDE=%ROOT%webside

rem Both servers listen on plain HTTP. Put nginx in front if you need HTTPS.

echo [1/2] Activating conda env mercari and starting backend (python main.py)...
call conda activate mercari

cd /d %BACKEND%
start /b python main.py

timeout /t 2 /nobreak >nul

echo [2/2] Preparing frontend dev server...
where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Install it and add to PATH: https://nodejs.org/
  pause
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm not found. Check your Node.js installation.
  pause
  exit /b 1
)

cd /d %WEBSIDE%
call npm install
if errorlevel 1 (
  echo [ERROR] npm install failed. Check the network or package.json
  pause
  exit /b 1
)

echo.
echo ========================================
echo   Frontend ^(HTTP^):  http://localhost:9600
echo   Backend API:  http://localhost:9601
echo   API docs:     http://localhost:9601/docs
echo   Press Ctrl+C to stop
echo ========================================
echo.

npm run dev
