@echo off
chcp 65001 >nul
rem ============================================
rem  ontology-agent local starter
rem  backend :8001 (FastAPI + uvicorn)
rem  frontend :5199 (Vite dev server)
rem ============================================
setlocal
set "PROJECT_ROOT=%~dp0"

if not exist "%PROJECT_ROOT%.env" (
    echo [ERROR] .env not found: %PROJECT_ROOT%.env
    echo         Copy .env.example to .env and configure the application first.
    exit /b 1
)

if not exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found: %PROJECT_ROOT%.venv
    echo         Run: python -m venv .venv
    echo         Then: .venv\Scripts\python.exe -m pip install -e ".[dev]"
    exit /b 1
)

for /f "tokens=1 delims=." %%v in ('node --version 2^>nul') do set "NODE_VERSION=%%v"
set "NODE_MAJOR=%NODE_VERSION:v=%"
if not defined NODE_MAJOR (
    echo [ERROR] Node.js not found. The frontend requires Node.js 20 LTS or newer.
    exit /b 1
)
if %NODE_MAJOR% LSS 18 (
    echo [ERROR] Node.js major version is %NODE_MAJOR%. Vite 5 requires Node.js 18 or newer.
    echo         Install Node.js 20 LTS and reopen the terminal.
    exit /b 1
)

echo [1/2] Starting backend (8001)...
start "ontology-backend" cmd /k "cd /d ""%PROJECT_ROOT%"" ^&^& .venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8001"

echo [2/2] Starting frontend (5199)...
start "ontology-frontend" cmd /k "cd /d ""%PROJECT_ROOT%frontend"" ^&^& npm.cmd run dev -- --host 127.0.0.1 --port 5199 --strictPort"

echo.
echo Started. Open:
echo   Frontend: http://127.0.0.1:5199
echo   Backend:  http://127.0.0.1:8001/docs
echo   Stop:     stop.bat
echo.
endlocal
