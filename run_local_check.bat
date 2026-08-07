@echo off
REM ---------------------------------------------------------------
REM  Local environment check for the video pipeline.
REM  Double-click this file. It installs the two packages the
REM  pipeline needs, then tests whether THIS machine can reach
REM  Gemini (images) and Edge TTS (free narration).
REM  Results are written to finals\local_check.log
REM ---------------------------------------------------------------

cd /d "%~dp0"

echo.
echo ============================================================
echo   VIDEO PIPELINE - LOCAL ENVIRONMENT CHECK
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: python is not on your PATH.
  echo Install Python 3.10+ and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo Installing / updating required packages...
python -m pip install --quiet --upgrade requests pillow edge-tts
echo.

echo Running checks...
echo.
python helpers\local_env_check.py

echo.
echo ============================================================
echo   Finished. Log written to finals\local_check.log
echo.
echo   Two files to check by hand:
echo     finals\local_check_gemini.png  - should be a coffee mug
echo     finals\local_check_voice.mp3   - listen to the names
echo ============================================================
echo.
echo Closing in 10 seconds...
timeout /t 10 /nobreak >nul
exit /b 0
