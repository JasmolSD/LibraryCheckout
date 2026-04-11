@echo off
title Library Checkout System
cd /d "%~dp0"

:: Check if uv is available
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv is not installed. Please run the installer or follow the setup guide.
    pause
    exit /b 1
)

:: Sync desktop dependencies silently (fast no-op if already up to date)
uv sync --group desktop --quiet

:: Launch the app
uv run python run.py
