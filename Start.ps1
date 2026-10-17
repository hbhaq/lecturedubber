$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Install and start Docker Desktop with Linux containers, then run this script again.'
}
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Created .env. Demo mode is ready; add OPENAI_API_KEY for live processing.'
}
docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed. Check Docker Desktop and the build output above.' }
Write-Host 'Open http://localhost:3000 in Chrome or Edge.'
