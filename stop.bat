@echo off
chcp 65001 >nul
rem ============================================
rem  ontology-agent local service stopper
rem  terminate listeners on :8001 and :5199
rem ============================================

echo Stopping ontology-agent services...

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
    taskkill /F /T /PID %%p >nul 2>&1 && echo   [Stopped] backend PID %%p
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5199.*LISTENING"') do (
    taskkill /F /T /PID %%p >nul 2>&1 && echo   [Stopped] frontend PID %%p
)

echo.
echo Services stopped.
echo.
