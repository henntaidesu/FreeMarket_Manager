@echo off
echo ========================================
echo   mercari one-click build (PyInstaller)
echo ========================================

rem ===== Version (edit this on each release) =====
set VERSION=v1.0.0

rem ===== Bundle OCR (easyocr/torch, ~2GB, slower start). 0=no 1=yes =====
set BUNDLE_OCR=0

set ROOT=%~dp0
set RELEASE=%ROOT%Releases\%VERSION%

rem ===== Activate conda env mercari =====
echo.
echo [0/3] Activating conda env mercari ...
call conda activate mercari
if %errorlevel% neq 0 (
    echo ERROR: failed to activate conda env mercari
    pause
    exit /b 1
)

rem ===== Ensure pyinstaller is available =====
rem NOTE: call it via "python -m PyInstaller" (NOT the bare "pyinstaller" command).
rem This script is named pyinstaller.bat; cmd resolves "pyinstaller" to THIS file
rem (current dir before PATH), which would recurse into an infinite loop.
python -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo pyinstaller not found, installing...
    python -m pip install pyinstaller
)

rem ===== Ensure pystray is available (system tray icon) =====
python -c "import pystray" >nul 2>&1
if %errorlevel% neq 0 (
    echo pystray not found, installing...
    python -m pip install pystray
)

rem ===== Prepare release directory =====
echo.
echo [1/3] Cleaning and creating release dir %RELEASE% ...
if exist "%RELEASE%" rmdir /s /q "%RELEASE%"
mkdir "%RELEASE%"
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"

rem ===== Build frontend =====
echo.
echo [2/3] Building frontend webside ...
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: npm not found, please install Node.js: https://nodejs.org/
    pause
    exit /b 1
)
pushd "%ROOT%webside"
if not exist "node_modules" (
    echo Installing frontend deps...
    call npm install
    if %errorlevel% neq 0 ( echo ERROR: npm install failed & popd & pause & exit /b 1 )
)
call npm run build
if %errorlevel% neq 0 ( echo ERROR: frontend build failed & popd & pause & exit /b 1 )
popd
if not exist "%ROOT%webside\dist\index.html" (
    echo ERROR: webside\dist\index.html not found, frontend build may have failed
    pause
    exit /b 1
)

rem ===== Build main program mercariManager.exe =====
echo.
echo [3/3] Building mercariManager.exe (windowed, system tray; frontend bundled in) ...
python -m PyInstaller --clean --noconfirm "%ROOT%mercari.spec" ^
    --distpath "%RELEASE%" --workpath "%ROOT%build\backend"
if %errorlevel% neq 0 (
    echo ERROR: mercariManager.exe build failed
    pause
    exit /b 1
)

rem Frontend webside/dist is bundled INTO mercariManager.exe (see mercari.spec); no external webside folder.
rem (To hot-swap the frontend without rebuilding, drop a "webside" folder next to mercariManager.exe.)

rem Note: Playwright uses the system-installed Microsoft Edge (channel=msedge); target machine must have Edge (bundled with Win11).
rem Note: MITM capture (Scripts\mitmdump.exe) is NOT bundled in this package; other features unaffected.

rem ===== Clean build intermediates =====
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"

echo.
echo ========================================
echo   Build complete! Output dir: %RELEASE%
echo ========================================
dir /b "%RELEASE%"
echo ----------------------------------------
echo   Put mercariDB.db next to mercariManager.exe, then run mercariManager.exe
echo   A run window with live logs opens on launch. Clicking X asks whether to
echo   exit or minimize to the tray; the tray icon (bottom-right) restores it.
echo   Then open https://localhost:9600 in your browser (self-signed cert auto-generated)
echo ========================================
pause
