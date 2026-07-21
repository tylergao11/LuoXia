$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$runDir = Join-Path $backend "data\run"
$pidFile = Join-Path $runDir "backend.pid"
$deepseekKeyFile = Join-Path $runDir "deepseek.key"

New-Item -ItemType Directory -Force -Path $runDir | Out-Null

if (Test-Path $deepseekKeyFile) {
    $env:LLM_API_KEY = (Get-Content $deepseekKeyFile -Raw).Trim()
    $env:LLM_BASE_URL = "https://api.deepseek.com/v1"
    $env:LLM_MODEL = "deepseek-v4-flash"
}

if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        exit 0
    }
}

$process = Start-Process `
    -FilePath (Join-Path $backend ".venv\Scripts\uvicorn.exe") `
    -ArgumentList "app.main:app", "--host", "127.0.0.1", "--port", "8002" `
    -WorkingDirectory $backend `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $runDir "backend.stdout.log") `
    -RedirectStandardError (Join-Path $runDir "backend.stderr.log") `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id -Encoding ascii
