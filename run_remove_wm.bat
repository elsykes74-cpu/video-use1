@echo off
setlocal enabledelayedexpansion
title MJ FOREVER — Watermark Remover

echo.
echo ================================================
echo   MJ Watermark Remover  (MJ FOREVER logo)
echo ================================================
echo.

:: ── HOW TO USE ────────────────────────────────────────────────────────
:: EASIEST:  Drag your video file directly onto this .bat file.
:: MANUAL:   Edit the INPUT= line below with your video path,
::           then double-click this file.
:: ──────────────────────────────────────────────────────────────────────

:: Accept drag-and-drop
if not "%~1"=="" (
    set "INPUT=%~1"
    goto :have_input
)

:: Fallback: set path manually (edit this line)
set "INPUT=C:\Users\erick\Google Drive\My Drive\Video by mjforeverofficial.mp4"

:have_input

:: ── OUTPUT ────────────────────────────────────────────────────────────
set "OUTPUT=%USERPROFILE%\video-use1\mj_no_watermark.mp4"

:: ── VALIDATE ──────────────────────────────────────────────────────────
if not exist "%INPUT%" (
    echo ERROR: Video not found:
    echo   %INPUT%
    echo.
    echo Try dragging your video directly onto this .bat file.
    echo Or edit the INPUT= line near the top of this script.
    echo.
    pause
    exit /b 1
)

echo Input:  %INPUT%
echo Output: %OUTPUT%
echo.
echo Blurring MJ FOREVER watermark (top-right corner)...
echo This takes 1-3 minutes depending on video length.
echo.

:: ── REMOVE WATERMARK ──────────────────────────────────────────────────
:: Strategy: extract the watermark region, blur it heavily, overlay it back.
:: Targets the MJ FOREVER logo at top-right corner of a 1080-wide vertical video.
:: Region: x=790 y=65 w=290 h=195  (adjust if logo is cut off — see TUNING below)

set "WM_FILTER=split[base][logo];[logo]crop=290:195:790:65,avgblur=radius=18[blurred];[base][blurred]overlay=790:65"

ffmpeg -y ^
  -i "%INPUT%" ^
  -vf "%WM_FILTER%" ^
  -c:v libx264 -preset fast -crf 18 ^
  -c:a copy ^
  "%OUTPUT%"

if errorlevel 1 (
    echo.
    echo ================================================
    echo   ERROR: FFmpeg failed.
    echo ================================================
    echo.
    echo Make sure FFmpeg is installed. If not:
    echo   1. Go to: https://www.gyan.dev/ffmpeg/builds/
    echo   2. Download "ffmpeg-release-essentials.zip"
    echo   3. Extract it and add the \bin folder to your PATH
    echo.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Done!  Clean video saved to:
echo   %OUTPUT%
echo ================================================
echo.

:: Open the output folder automatically
explorer /select,"%OUTPUT%"

pause

:: ── TUNING ────────────────────────────────────────────────────────────
:: If the logo is still visible or the blur box is in the wrong spot:
::
::   crop=W:H:X:Y  where X/Y is the TOP-LEFT corner of the watermark
::   overlay=X:Y   must match crop X:Y exactly
::
::   Current values target a 1080xANY vertical video.
::   If your video is a different width (e.g. 720 wide) scale the X by 0.667:
::     790 * 0.667 = 527  →  change 790 to 527, and 290 to 194
:: ──────────────────────────────────────────────────────────────────────
