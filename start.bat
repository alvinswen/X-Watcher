@echo off
chcp 65001 >nul 2>&1
title x-watcher

echo [x-watcher] Checking PostgreSQL container...

:: Check if container is running
docker ps --filter name=x-watcher-postgres --format "{{.Status}}" | findstr /i "Up" >nul 2>&1
if %errorlevel% neq 0 (
    echo [x-watcher] PostgreSQL not running, starting...
    docker compose --profile prod up -d postgres
    if %errorlevel% neq 0 (
        echo [x-watcher] ERROR: Failed to start PostgreSQL container.
        pause
        exit /b 1
    )

    echo [x-watcher] Waiting for PostgreSQL to be ready...
    :wait_pg
    docker inspect --format "{{.State.Health.Status}}" x-watcher-postgres 2>nul | findstr /i "healthy" >nul 2>&1
    if %errorlevel% neq 0 (
        timeout /t 2 /nobreak >nul
        goto wait_pg
    )
    echo [x-watcher] PostgreSQL is ready.
) else (
    echo [x-watcher] PostgreSQL is already running.
)

echo [x-watcher] Starting x-watcher serve...
"%APPDATA%\Python\Python314\Scripts\x-watcher.exe" serve
