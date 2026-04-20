@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
:: x-watcher 定时抓取入口（Windows Task Scheduler）
::
:: 用途：每天定时拉取所有关注账号的最新推文 + Claude Code 翻译入库
:: 默认计划：每天 04:00（在 Task Scheduler 中配置）
:: 日志位置：%LOGDIR%\scrape-YYYY-MM-DD.log
::
:: 部署步骤：
::   1. 按实际项目位置替换脚本中所有 C:\dailywork\x-watcher 路径
::      （LOGDIR、cd /d、docker compose -f 三处）
::   2. 按实际 Docker Desktop 安装路径调整 DOCKER_DESKTOP_EXE
::   3. 按实际 Claude CLI 路径调整 CLAUDE_EXE
::   4. 在 Task Scheduler 注册（管理员 cmd 中执行）：
::        schtasks /Create /SC DAILY /ST 04:00 /TN "x-watcher-scrape" ^
::            /TR "C:\dailywork\x-watcher\scripts\scheduled-scrape.bat"
::
:: 依赖：
::   - Docker Desktop（脚本会按需自启）
::   - postgres 容器名 x-watcher-postgres（docker-compose --profile prod）
::   - Claude Code CLI 已安装并配置 x-watcher MCP server
::
:: 维护警告（参考 CLAUDE.md）：
::   - 文件必须 CRLF 行尾，LF 会让 cmd.exe 整段解析失败且零日志输出
::   - if/for 块内 echo 含字面量括号必须写 ^( ^)，否则块解析失败
:: ============================================================

set LOGDIR=C:\dailywork\x-watcher\logs
set LOGFILE=%LOGDIR%\scrape-%date:~0,4%-%date:~5,2%-%date:~8,2%.log
set DOCKER_DESKTOP_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [%date% %time%] === Scheduled scrape-and-translate started === >> "%LOGFILE%"

:: Step 1: Ensure Docker Desktop is running
echo [%date% %time%] Checking Docker engine... >> "%LOGFILE%"
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] Docker engine not responding, starting Docker Desktop... >> "%LOGFILE%"
    if not exist "%DOCKER_DESKTOP_EXE%" (
        echo [%date% %time%] ERROR: Docker Desktop not found at "%DOCKER_DESKTOP_EXE%" >> "%LOGFILE%"
        exit /b 1
    )
    start "" "%DOCKER_DESKTOP_EXE%"

    set /a wait_docker=0
    :wait_docker_loop
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if !errorlevel! equ 0 goto docker_ready
    set /a wait_docker+=3
    if !wait_docker! geq 120 (
        echo [%date% %time%] ERROR: Docker engine did not become ready within 120s >> "%LOGFILE%"
        exit /b 1
    )
    goto wait_docker_loop
    :docker_ready
    echo [%date% %time%] Docker engine is ready ^(waited !wait_docker!s^). >> "%LOGFILE%"
) else (
    echo [%date% %time%] Docker engine is already running. >> "%LOGFILE%"
)

:: Step 2: Ensure PostgreSQL is running
echo [%date% %time%] Checking PostgreSQL container... >> "%LOGFILE%"
docker ps --filter name=x-watcher-postgres --format "{{.Status}}" | findstr /i "Up" >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] PostgreSQL not running, starting... >> "%LOGFILE%"
    docker compose -f C:\dailywork\x-watcher\docker-compose.yml --profile prod up -d postgres >> "%LOGFILE%" 2>&1
    if %errorlevel% neq 0 (
        echo [%date% %time%] ERROR: Failed to start PostgreSQL >> "%LOGFILE%"
        exit /b 1
    )

    set /a wait_pg=0
    :wait_pg_loop
    docker inspect --format "{{.State.Health.Status}}" x-watcher-postgres 2>nul | findstr /i "healthy" >nul 2>&1
    if !errorlevel! equ 0 goto pg_ready
    timeout /t 2 /nobreak >nul
    set /a wait_pg+=2
    if !wait_pg! geq 60 (
        echo [%date% %time%] ERROR: PostgreSQL did not become healthy within 60s >> "%LOGFILE%"
        exit /b 1
    )
    goto wait_pg_loop
    :pg_ready
    echo [%date% %time%] PostgreSQL is ready ^(waited !wait_pg!s^). >> "%LOGFILE%"
) else (
    echo [%date% %time%] PostgreSQL is already running. >> "%LOGFILE%"
)

:: Step 3: Pre-flight — verify x-watcher MCP server reachable
cd /d C:\dailywork\x-watcher
set CLAUDE_EXE=%USERPROFILE%\.local\bin\claude

echo [%date% %time%] Pre-flight: checking x-watcher MCP connectivity... >> "%LOGFILE%"
"%CLAUDE_EXE%" mcp list 2>&1 | findstr /r /c:"x-watcher.*Connected" >nul
if %errorlevel% neq 0 (
    echo [%date% %time%] MCP check failed, waiting 10s and retrying... >> "%LOGFILE%"
    timeout /t 10 /nobreak >nul
    "%CLAUDE_EXE%" mcp list >> "%LOGFILE%" 2>&1
    "%CLAUDE_EXE%" mcp list 2>&1 | findstr /r /c:"x-watcher.*Connected" >nul
    if !errorlevel! neq 0 (
        echo [%date% %time%] ERROR: x-watcher MCP server not connected after retry >> "%LOGFILE%"
        exit /b 1
    )
)
echo [%date% %time%] MCP pre-flight OK. >> "%LOGFILE%"

:: Step 4: Run Claude Code with scrape-and-translate (with one retry)
echo [%date% %time%] Starting Claude Code scrape-and-translate (attempt 1)... >> "%LOGFILE%"
"%CLAUDE_EXE%" -p "/scrape-and-translate" --dangerously-skip-permissions --output-format text >> "%LOGFILE%" 2>&1
set CLAUDE_EXIT=!errorlevel!

if !CLAUDE_EXIT! neq 0 (
    echo [%date% %time%] claude exited with !CLAUDE_EXIT!, waiting 30s and retrying... >> "%LOGFILE%"
    timeout /t 30 /nobreak >nul
    echo [%date% %time%] Starting Claude Code scrape-and-translate ^(attempt 2^)... >> "%LOGFILE%"
    "%CLAUDE_EXE%" -p "/scrape-and-translate" --dangerously-skip-permissions --output-format text >> "%LOGFILE%" 2>&1
    set CLAUDE_EXIT=!errorlevel!
)

echo [%date% %time%] === Scheduled scrape-and-translate finished (claude exit: !CLAUDE_EXIT!) === >> "%LOGFILE%"
exit /b !CLAUDE_EXIT!
