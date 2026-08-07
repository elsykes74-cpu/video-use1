# One command, prompt to finished video.
#
#   cd C:\Users\erick\video-use1
#   powershell -ExecutionPolicy Bypass -File .\make.ps1            # build once
#   powershell -ExecutionPolicy Bypass -File .\make.ps1 -Watch     # build forever
#   powershell -ExecutionPolicy Bypass -File .\make.ps1 -Redo narration
param(
  [string]$Project = 'finals\colonel_parker',
  [string]$Redo    = '',
  [switch]$Watch
)

Set-Location -Path $PSScriptRoot

# A locked log must never stop a build. If build.log is held by another
# instance, fall back to a timestamped file, then to no log at all.
$log = Join-Path $Project 'build.log'
try   { [IO.File]::AppendAllText($log, '') }
catch { $log = Join-Path $Project ("build_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss')) }

# 'python' here is a .cmd shim; find a real interpreter.
$py = $null
foreach ($c in @(
    'C:\Users\erick\AppData\Local\Programs\Python\Python312\python.exe',
    'C:\Users\erick\AppData\Local\Programs\Python\Python311\python.exe',
    'C:\Users\erick\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe'
)) { if (Test-Path $c) { $py = $c; break } }
if (-not $py) { $c = Get-Command python -ErrorAction SilentlyContinue; if ($c) { $py = $c.Source } }
if (-not $py) { Write-Host "ERROR: no python found"; Read-Host "Enter to close"; exit 1 }

# ffmpeg
$ffdir = 'C:\Users\erick\Downloads\ffmpeg-8.1.1-essentials_build\ffmpeg-8.1.1-essentials_build\bin'
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Test-Path "$ffdir\ffmpeg.exe") { $env:PATH += ";$ffdir" }
    else { Write-Host "ERROR: ffmpeg not found"; Read-Host "Enter to close"; exit 1 }
}

Write-Host ""
Write-Host "python  : $py"
Write-Host "project : $Project"
Write-Host "log     : $log"
if ($Watch) { Write-Host "mode    : WATCH - leave this window open" }
Write-Host ""

$a = @('-u','helpers\make_video.py','--project',$Project)
if ($Redo)  { $a += @('--redo', $Redo) }
if ($Watch) { $a += '--watch' }

try {
    & $py @a 2>&1 | Tee-Object -FilePath $log
} catch {
    Write-Host "(logging unavailable - running without it)"
    & $py @a 2>&1
}

if (-not $Watch) {
  Write-Host ""
  Read-Host "Press Enter to close"
}
