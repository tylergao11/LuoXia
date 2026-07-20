# 落霞宗本地一键启动（Windows）
# 用法: 在仓库根目录 powershell -File scripts/run_local.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"

Write-Host "== 落霞宗 本地启动 ==" -ForegroundColor Cyan

# Ollama 提示
try {
    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
    $names = $tags.models | ForEach-Object { $_.name }
    Write-Host "Ollama 模型: $($names -join ', ')" -ForegroundColor Green
    if ($names -notcontains "qwen3:8b") {
        Write-Host "建议: ollama pull qwen3:8b" -ForegroundColor Yellow
    }
} catch {
    Write-Host "未检测到 Ollama (11434)。将使用 Mock 或请先启动 ollama serve" -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $Backend ".venv"))) {
    Write-Host "创建 venv..."
    python -m venv (Join-Path $Backend ".venv")
}

& (Join-Path $Backend ".venv\Scripts\pip.exe") install -r (Join-Path $Backend "requirements.txt") -q

$envFile = Join-Path $Backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Backend ".env.example") $envFile
    Write-Host "已生成 backend/.env（默认 Ollama qwen3:8b）" -ForegroundColor Green
}

Write-Host "跑测试..."
& (Join-Path $Backend ".venv\Scripts\python.exe") -m pytest (Join-Path $Backend "tests") -q --tb=line
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "启动 API :8000 与前端 :5173 ..." -ForegroundColor Cyan
Start-Process -FilePath (Join-Path $Backend ".venv\Scripts\uvicorn.exe") `
    -ArgumentList "app.main:app","--reload","--port","8000" `
    -WorkingDirectory $Backend

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Push-Location $Frontend
    npm install
    Pop-Location
}
Start-Process -FilePath "npm" -ArgumentList "run","dev" -WorkingDirectory $Frontend

Write-Host "打开 http://localhost:5173" -ForegroundColor Green
