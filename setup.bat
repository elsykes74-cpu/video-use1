@echo off
title Elvis ^& MJ Bot Setup
echo.
echo ================================================
echo   Elvis ^& MJ Content Bot - Windows Setup
echo ================================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Please download and install Python from https://python.org/downloads
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/5] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Could not create virtual environment.
    pause
    exit /b 1
)

echo [2/5] Installing project dependencies...
call .venv\Scripts\pip install -e . --quiet
if errorlevel 1 (
    echo ERROR: Failed to install project deps.
    pause
    exit /b 1
)

echo [3/5] Installing bot dependencies...
call .venv\Scripts\pip install -r bot\requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install bot deps.
    pause
    exit /b 1
)

echo [4/5] Setting up .env file...
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Your .env file has been created. Opening it now...
    echo Add your TELEGRAM_BOT_TOKEN and GEMINI_API_KEY, then save.
    echo Then close Notepad and come back here.
    echo.
    pause
    notepad .env
) else (
    echo .env already exists, skipping.
)

echo [5/5] Setting up AI video pipeline (youtube-shorts-pipeline)...
echo This installs the /generate command. It may take a few minutes...
call .venv\Scripts\python bot\setup_verticals.py
if errorlevel 1 (
    echo WARNING: Pipeline setup had issues. You can re-run it later:
    echo   .venv\Scripts\python bot\setup_verticals.py
)

echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo To start the bot, double-click  start_bot.bat
echo.
echo In Telegram, try:
echo   /generate Elvis recorded Hound Dog in one take
echo   /generate mj How Michael Jackson created the moonwalk
echo.
pause
