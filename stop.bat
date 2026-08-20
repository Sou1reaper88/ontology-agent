@echo off
chcp 65001 >nul
rem ============================================
rem  ontology-agent 关闭脚本
rem  结束 :8001(后端) 与 :5199(前端) 的进程
rem ============================================

echo 正在关闭 ontology-agent 服务...

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
    taskkill /F /T /PID %%p >nul 2>&1 && echo   [已结束] 后端进程 PID %%p
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5199.*LISTENING"') do (
    taskkill /F /T /PID %%p >nul 2>&1 && echo   [已结束] 前端进程 PID %%p
)

echo.
echo 服务已全部关闭。
echo.
