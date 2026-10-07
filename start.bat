@echo off
echo ========================================
echo   mercari dev startup script
echo ========================================
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set WEBSIDE=%ROOT%webside

rem HTTP by default; System Config - Web access = Direct HTTPS makes both servers use a self-signed cert.

echo [1/2] Activating conda env mercari and starting backend (python main.py)...
call conda activate mercari >nul 2>&1
if /i "%CONDA_DEFAULT_ENV%"=="mercari" goto :conda_ok
rem Without "conda init cmd.exe", "conda" resolves to Scripts\conda.exe, which cannot activate.
rem Fall back to the activate.bat next to it.
set "CONDA_ACT="
for /f "delims=" %%C in ('where conda 2^>nul') do if not defined CONDA_ACT if exist "%%~dpCactivate.bat" set "CONDA_ACT=%%~dpCactivate.bat"
if defined CONDA_ACT call "%CONDA_ACT%" mercari
if /i "%CONDA_DEFAULT_ENV%"=="mercari" goto :conda_ok
echo [ERROR] Failed to activate conda env "mercari". Check: conda env list
pause
exit /b 1
:conda_ok
for /f "delims=" %%P in ('where python') do echo Using python: %%P& goto :py_shown
:py_shown

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
echo   Frontend:  http://localhost:9600  ^(https:// when System Config - Web access = Direct HTTPS^)
echo   Backend API:  http://localhost:9601
echo   API docs:     http://localhost:9601/docs
echo   Press Ctrl+C to stop
echo ========================================
echo.

npm run dev
