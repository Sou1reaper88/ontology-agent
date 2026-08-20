@echo off
chcp 65001 >nul
rem ============================================
rem  ontology-agent 启动脚本
rem  后端 :8001 (FastAPI + uvicorn)
rem  前端 :5199 (Vite dev server)
rem ============================================
cd /d D:\projects\ontology-agent

echo [1/2] 启动后端 (8001)...
start "ontology-backend" cmd /k ".venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8001"

echo [2/2] 启动前端 (5199)...
cd /d D:\projects\ontology-agent\frontend
start "ontology-frontend" cmd /k "set NODE_OPTIONS=&& npm run dev -- --port 5199 --strictPort"

echo.
echo 启动完成，访问：
echo   前端: http://localhost:5199
echo   后端: http://127.0.0.1:8001  (文档 /docs)
echo   关闭: 运行 stop.bat
echo.
