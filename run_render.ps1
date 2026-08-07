# Render "The Man Who Owned The King" end to end.
#   powershell -ExecutionPolicy Bypass -File .\run_render.ps1
# Everything is logged to finals\colonel_parker\debug.log

$ErrorActionPreference = 'Continue'
Set-Location -Path $PSScriptRoot

$proj     = 'finals\colonel_parker'
$manifest = "$proj\manifest.json"
$voice    = "$proj\voice.mp3"
$log      = "$proj\debug.log"
$ffdir    = 'C:\Users\erick\Downloads\ffmpeg-8.1.1-essentials_build\ffmpeg-8.1.1-essentials_build\bin'

function Say($m) { Write-Host $m; Add-Content -Path $log -Value $m }

Set-Content -Path $log -Value "==== RENDER $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===="
Say "cwd = $(Get-Location)"
Say ""

# ---- python -------------------------------------------------------------
# 'python' on this machine is a .cmd wrapper; resolve a real interpreter.
$py = $null
foreach ($c in @(
    'C:\Users\erick\AppData\Local\Programs\Python\Python312\python.exe',
    'C:\Users\erick\AppData\Local\Programs\Python\Python311\python.exe',
    'C:\Users\erick\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe'
)) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) { Say "ERROR: no python found"; Read-Host "Enter to close"; exit 1 }
Say "python  : $py"
Say ("version : " + (& $py --version 2>&1))
Say ""

# ---- ffmpeg -------------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Test-Path "$ffdir\ffmpeg.exe") {
        $env:PATH += ";$ffdir"
        Say "ffmpeg  : using build in Downloads"
    } else { Say "ERROR: ffmpeg not found"; Read-Host "Enter to close"; exit 1 }
} else { Say "ffmpeg  : found on PATH" }
Say ("        " + ((& ffmpeg -version 2>&1) | Select-Object -First 1))
Say ""

# ---- required files -----------------------------------------------------
Say "---- required files ----"
foreach ($f in @($manifest, $voice, "$proj\script.txt",
                 'helpers\make_captions.py', 'helpers\assemble_production.py')) {
    if (Test-Path $f) { Say "  OK      $f" } else { Say "  MISSING $f" }
}
Say ""

# ---- scene images -------------------------------------------------------
Say "---- scene images ----"
$m = Get-Content $manifest -Raw | ConvertFrom-Json
$missing = 0
foreach ($s in $m.scenes) {
    $p = Join-Path $proj $s.image
    if (Test-Path $p) { Say ("  OK      {0,2}  {1}" -f $s.n, $s.image) }
    else { Say ("  MISSING {0,2}  {1}" -f $s.n, $s.image); $missing++ }
}
Say ""
if ($missing -gt 0) { Say "ERROR: $missing scene image(s) missing"; Read-Host "Enter to close"; exit 1 }

# ---- packages -----------------------------------------------------------
Say "---- packages ----"
& $py -m pip install --quiet --upgrade edge-tts pillow requests 2>&1 | Tee-Object -Append -FilePath $log
Say ""

# ---- captions -----------------------------------------------------------
Say "---- captions ----"
& $py -u helpers\make_captions.py --manifest $manifest 2>&1 | Tee-Object -Append -FilePath $log
Say ""

# ---- render -------------------------------------------------------------
Say "---- RENDER (this is the long part) ----"
& $py -u helpers\assemble_production.py --manifest $manifest --narration $voice `
      --preset medium --crf 19 --resume 2>&1 | Tee-Object -Append -FilePath $log
Say ""
Say "render exit code: $LASTEXITCODE"
Say ""
Say "---- outputs ----"
Get-ChildItem "$proj\*.mp4" | Sort-Object LastWriteTime -Descending |
    ForEach-Object { Say ("  {0,10:N0} KB  {1}  {2}" -f ($_.Length/1KB), $_.LastWriteTime.ToString('HH:mm'), $_.Name) }

Write-Host ""
Write-Host "============================================================"
Write-Host "  Done. Log: $log"
Write-Host "============================================================"
Read-Host "Press Enter to close"
