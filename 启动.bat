@echo off
title project5 AI 知识库 - 一键启动
cd /d "%~dp0"

echo ============================================
echo   project5 AI 知识库 - 一键启动
echo   双击本文件：自动拉起 Docker - 启动服务 - 打开浏览器
echo ============================================
echo.

REM ---- 1/3 Docker 引擎：没起就拉起 Docker Desktop 并等就绪 ----
docker info >nul 2>&1
if not errorlevel 1 goto dockerdone
echo [1/3] Docker 未运行，正在启动 Docker Desktop（首次可能要 1 分钟）...
if not exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" goto nodocker
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
set /a n=0
:waitdocker
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto dockerdone
set /a n+=1
if %n% lss 40 goto waitdocker
echo   Docker 长时间未就绪：看一眼 Docker Desktop 有没有要处理的弹窗，然后再双击本文件。
pause
exit /b 1
:nodocker
echo   没找到 Docker Desktop（C:\Program Files\Docker\Docker\Docker Desktop.exe）。
echo   请手动启动 Docker 后再运行本脚本。
pause
exit /b 1
:dockerdone
echo [1/3] Docker 就绪

REM ---- 2/3 服务容器（幂等：已经在跑就是 no-op，几秒过） ----
echo [2/3] 启动服务容器（数据库 / 后端 / 前端 + Langfuse 面板）...
docker compose up -d
docker compose -f docker-compose.langfuse.yml up -d

REM ---- 3/3 等前端就绪后打开浏览器 ----
echo [3/3] 等待应用就绪...
set /a n=0
:waitweb
curl -s -o nul --max-time 2 http://127.0.0.1:5173
if not errorlevel 1 goto openweb
timeout /t 2 /nobreak >nul
set /a n+=1
if %n% lss 60 goto waitweb
echo   前端迟迟没起来，可能是容器出错了，用下面命令看日志：
echo     docker compose logs --tail 50
pause
exit /b 1
:openweb
start "" http://localhost:5173
echo.
echo ============================================
echo   已打开：http://localhost:5173
echo   观测面板（可选）：http://localhost:8080
echo   本窗口可以直接关掉（服务在后台继续运行）
echo   改了代码要重建镜像时用：docker compose up -d --build
echo ============================================
timeout /t 5 /nobreak >nul
exit /b 0