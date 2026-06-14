@echo off
title Elvis & MJ Bot Setup
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

echo [1/4] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Could not create virtual environment.
    pause
    exit /b 1
)

echo [2/4] Installing project dependencies...
call .venv\Scripts\pip install -e . --quiet
if errorlevel 1 (
    echo ERROR: Failed to install project deps.
    pause
    exit /b 1
)

echo [3/4] Installing bot dependencies...
call .venv\Scripts\pip install -r bot\requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install bot deps.
    pause
    exit /b 1
)

echo [4/4] Setting up .env file...
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Your .env file has been created. Opening it now...
    echo Add your TELEGRAM_BOT_TOKEN and save the file.
    echo Then close Notepad and come back here.
    echo.
    pause
    notepad .env
) else (
    echo .env already exists, skipping.
)

echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo To start the bot, double-click  start_bot.bat
echo Or run:  .venv\Scripts\python bot\bot.py
echo.
pause
