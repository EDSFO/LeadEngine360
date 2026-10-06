param([ValidateRange(1, 65535)][int]$AppPort)

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
if ($AppPort) {
    $configured = [regex]::Replace($configured, '(?m)^APP_PORT=.*$', "APP_PORT=$AppPort")
    if ($configured -notmatch '(?m)^APP_PORT=') { $configured += "`nAPP_PORT=$AppPort`n" }
}
$portMatch = [regex]::Match($configured, '(?m)^APP_PORT=(\d+)\s*$')
if (-not $portMatch.Success) { throw 'Defina APP_PORT na .env ou informe -AppPort.' }
$resolvedPort = [int]$portMatch.Groups[1].Value
$configured = [regex]::Replace($configured, '(?m)^FRONTEND_ORIGIN=.*$', "FRONTEND_ORIGIN=http://localhost:$resolvedPort")
if ($configured -match 'replace-with-a-long-random' -or $configured -match '(?m)^(JWT_SECRET|POSTGRES_PASSWORD)=$') {
    throw 'Configure JWT_SECRET e POSTGRES_PASSWORD antes de implantar.'
}
$portInUse = Get-NetTCPConnection -State Listen -LocalPort $resolvedPort -ErrorAction SilentlyContinue
if ($portInUse) {
    $published = docker compose port web 3000 2>$null
    if ($LASTEXITCODE -ne 0 -or $published -notmatch ":$resolvedPort$") {
        throw "A porta $resolvedPort já está em uso por outro serviço na innovaapps."
    }
}
[IO.File]::WriteAllText($envPath, $configured, [Text.UTF8Encoding]::new($false))

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
docker tag leadengine360-api:latest leadengine360-scheduler:latest
docker build --pull=false -t leadengine360-web ./frontend
if ($LASTEXITCODE -ne 0) { throw 'Falha ao construir a interface.' }
docker compose up --no-build --pull never -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose up falhou.' }

$ruleName = "LeadEngine360 $resolvedPort LAN e Tailscale"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $resolvedPort -Profile Any -RemoteAddress 'LocalSubnet', '100.64.0.0/10' | Out-Null
}

docker compose ps
Write-Output "Acesse http://<IP_LAN>:$resolvedPort na LAN ou http://<IP_TAILSCALE>:$resolvedPort pela Tailscale"
