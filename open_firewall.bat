@echo off
rem ---------------------------------------------------------------------------
rem Open (or close) the Windows Firewall for the dev servers:
rem   9600  frontend      (Vite dev server)
rem   9601  backend       (FastAPI / uvicorn)
rem   9610  mercari-proxy (Cookie injection; the boot URL uses the page's host,
rem                        so a LAN browser connects to it directly)
rem
rem Why this exists: all three already listen on 0.0.0.0, so nothing in the
rem code stops a phone on the LAN -- Windows does, silently. The symptom is a
rem plain connection timeout with not one line in any server console.
rem
rem Usage (right-click -> Run as administrator):
rem   open_firewall.bat          add the inbound rules
rem   open_firewall.bat off      remove them again
rem
rem This only opens this machine. Reaching it from the internet still needs the
rem router to forward those ports (or a tunnel / nginx).
rem ---------------------------------------------------------------------------
setlocal

rem RULE_WEB is also probed by start.bat to warn when it is missing.
rem Change it here and there, or the warning starts lying.
set "RULE_WEB=FreeMarket Manager dev frontend 9600"
set "RULE_API=FreeMarket Manager dev backend 9601"
set "RULE_PROXY=FreeMarket Manager mercari-proxy 9610"

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator rights required.
    echo         Right-click this file and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

if /i "%~1"=="off" goto :remove

echo Adding inbound rules ...
rem Delete first so re-running does not stack up duplicates under one name.
netsh advfirewall firewall delete rule name="%RULE_WEB%" >nul 2>&1
netsh advfirewall firewall delete rule name="%RULE_API%" >nul 2>&1
netsh advfirewall firewall delete rule name="%RULE_PROXY%" >nul 2>&1

netsh advfirewall firewall add rule name="%RULE_WEB%" dir=in action=allow protocol=TCP localport=9600 profile=any
if errorlevel 1 goto :failed
netsh advfirewall firewall add rule name="%RULE_API%" dir=in action=allow protocol=TCP localport=9601 profile=any
if errorlevel 1 goto :failed
netsh advfirewall firewall add rule name="%RULE_PROXY%" dir=in action=allow protocol=TCP localport=9610 profile=any
if errorlevel 1 goto :failed

echo.
echo Done. 9600 / 9601 / 9610 now accept inbound TCP on every network profile.
echo Undo with: open_firewall.bat off
echo.
pause
exit /b 0

:remove
echo Removing inbound rules ...
netsh advfirewall firewall delete rule name="%RULE_WEB%" >nul 2>&1
netsh advfirewall firewall delete rule name="%RULE_API%" >nul 2>&1
netsh advfirewall firewall delete rule name="%RULE_PROXY%" >nul 2>&1
echo Done. The ports are blocked from outside again.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] netsh failed -- the rules were NOT created.
echo.
pause
exit /b 1
