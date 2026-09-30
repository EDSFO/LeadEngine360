$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location $projectDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI não encontrado na innovaapps.'
}
docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Engine não está em execução.' }

$envPath = Join-Path $projectDir '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $template = [IO.File]::ReadAllText((Join-Path $projectDir '.env.example'))
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $jwtBytes = New-Object byte[] 32
        $dbBytes = New-Object byte[] 24
        $generator.GetBytes($jwtBytes)
        $generator.GetBytes($dbBytes)
    } finally {
        $generator.Dispose()
    }
    $jwtSecret = [BitConverter]::ToString($jwtBytes).Replace('-', '')
    $dbSecret = [BitConverter]::ToString($dbBytes).Replace('-', '')
    $template = $template.Replace('replace-with-a-long-random-secret', $jwtSecret)
    $template = $template.Replace('replace-with-a-long-random-password', $dbSecret)
    [IO.File]::WriteAllText($envPath, $template, [Text.UTF8Encoding]::new($false))
}

$configured = [IO.File]::ReadAllText($envPath)
$configured = [regex]::Replace($configured, '(?m)^APP_BIND_IP=.*$', 'APP_BIND_IP=0.0.0.0')
$configured = [regex]::Replace($configured, '(?m)^APP_PORT=.*$', 'APP_PORT=3002')
$configured = [regex]::Replace($configured, '(?m)^FRONTEND_ORIGIN=.*$', 'FRONTEND_ORIGIN=http://localhost:3002')
if ($configured -notmatch '(?m)^APP_PORT=') { $configured += "`nAPP_PORT=3002`n" }
if ($configured -match 'replace-with-a-long-random' -or $configured -match '(?m)^(JWT_SECRET|POSTGRES_PASSWORD)=$') {
    throw 'Configure JWT_SECRET e POSTGRES_PASSWORD antes de implantar.'
}
[IO.File]::WriteAllText($envPath, $configured, [Text.UTF8Encoding]::new($false))

$portInUse = Get-NetTCPConnection -State Listen -LocalPort 3002 -ErrorAction SilentlyContinue
if ($portInUse -and -not (docker compose ps -q web)) { throw 'A porta 3002 já está em uso na innovaapps.' }

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'docker compose config falhou.' }

# O gerenciador de credenciais do Docker Desktop não está disponível na sessão SSH.
# O CLI com configuração isolada baixa imagens públicas e constrói as imagens locais.
$env:DOCKER_CONFIG = Join-Path $projectDir '.docker-config'
New-Item -ItemType Directory -Force -Path $env:DOCKER_CONFIG | Out-Null
[IO.File]::WriteAllText((Join-Path $env:DOCKER_CONFIG 'config.json'), '{"auths":{}}', [Text.UTF8Encoding]::new($false))
$env:DOCKER_BUILDKIT = '0'
foreach ($baseImage in @('postgres:17-alpine', 'redis:7-alpine', 'python:3.12-slim', 'node:22-alpine')) {
    docker pull --quiet $baseImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Falha ao baixar $baseImage" }
}
docker build --pull=false -t leadengine360-api ./backend
if ($LASTEXITCODE -ne 0) { throw 'Falha ao construir a API.' }
docker tag leadengine360-api:latest leadengine360-worker:latest
docker build --pull=false -t leadengine360-web ./frontend
if ($LASTEXITCODE -ne 0) { throw 'Falha ao construir a interface.' }
docker compose up --no-build --pull never -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose up falhou.' }

$ruleName = 'LeadEngine360 3002 LAN e Tailscale'
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3002 -Profile Any -RemoteAddress 'LocalSubnet', '100.64.0.0/10' | Out-Null
}

docker compose ps
Write-Output 'Acesse http://<IP_LAN>:3002 na LAN ou http://<IP_TAILSCALE>:3002 pela Tailscale'
