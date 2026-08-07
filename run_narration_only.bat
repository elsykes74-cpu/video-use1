@echo off
setlocal
REM ---------------------------------------------------------------
REM  NARRATION ONLY - takes about 60 seconds.
REM
REM  This does ONE job: turn the script into voice.mp3 using free
REM  Edge TTS. No video, no ffmpeg needed. Once this file exists,
REM  Claude can read it and render the whole video itself.
REM
REM  Output: finals\colonel_parker\voice.mp3
REM ---------------------------------------------------------------

cd /d "%~dp0"
title Narration - The Man Who Owned The King

echo.
echo ============================================================
echo   NARRATION ONLY  (about 60 seconds)
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: python not on PATH.
  pause & exit /b 1
)

echo Installing edge-tts if needed...
python -m pip install --quiet --upgrade edge-tts >nul 2>&1
echo.

python -u helpers\make_narration.py
set RC=%ERRORLEVEL%

echo.
if %RC% NEQ 0 (
  echo ============================================================
  echo   FAILED - exit code %RC%
  echo   Copy the red text above and send it to Claude.
  echo ============================================================
) else (
  echo ============================================================
  echo   DONE. Tell Claude "narration is ready".
  echo     finals\colonel_parker\voice.mp3
  echo     finals\colonel_parker\script_spoken.txt
  echo ============================================================
)
echo.
pause
