param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$secretDirectory = Join-Path (Get-Location) '.lab-secrets'
if (-not (Test-Path -LiteralPath $secretDirectory)) {
    New-Item -ItemType Directory -Path $secretDirectory | Out-Null
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $secretDirectory /inheritance:r /grant:r "${identity}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict local secret directory access.' }
}
foreach ($name in @('postgres_password', 'agent_token', 'approver_token', 'mcp_token')) {
    $secretPath = Join-Path $secretDirectory $name
    if (-not (Test-Path -LiteralPath $secretPath)) {
        $randomBytes = New-Object byte[] 48
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
        $token = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        [System.IO.File]::WriteAllText($secretPath, $token, (New-Object System.Text.UTF8Encoding($false)))
    }
}
if ($SkipBuild) { docker compose up -d --wait } else { docker compose up -d --build --wait }
if ($LASTEXITCODE -ne 0) { throw 'Docker startup failed. Check Docker Desktop and docker compose logs.' }
Write-Output 'Frontend: http://127.0.0.1:8080'
Write-Output 'Swagger:  http://127.0.0.1:8001/docs'
Write-Output 'MCP:      http://127.0.0.1:8002/mcp'
