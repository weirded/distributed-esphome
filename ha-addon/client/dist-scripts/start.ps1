# ESPHome Distributed Build Client — start script (Windows/PowerShell)
#
# Usage:
#   .\start.ps1                       Start and tail logs (Ctrl-C detaches; container keeps running)
#   .\start.ps1 -Background           Start detached
#   .\start.ps1 -ServerUrl URL -Token TOKEN   Override env vars
#
# {{BUILD_INFO}}

param(
    [switch]$Background,
    [string]$ServerUrl = $env:SERVER_URL,
    [string]$Token = $env:SERVER_TOKEN,
    [string]$HostPlatform = $env:HOST_PLATFORM,
    [int]$MaxParallelJobs = 0
)

$ErrorActionPreference = "Stop"

if (-not $ServerUrl) {
    Write-Error "SERVER_URL is required. Pass -ServerUrl or set `$env:SERVER_URL"
    exit 1
}
if (-not $Token) {
    Write-Error "SERVER_TOKEN is required. Pass -Token or set `$env:SERVER_TOKEN"
    exit 1
}

# Auto-detect host platform
if (-not $HostPlatform) {
    $os = (Get-CimInstance Win32_OperatingSystem)
    $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    $HostPlatform = "$($os.Caption) $($os.Version)"
    if ($cpu) { $HostPlatform += " ($cpu)" }
}

$Image = "esphome-dist-client"
$ContainerName = "esphome-dist-client"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TarFile = Join-Path $ScriptDir "esphome-dist-client.tar"

Write-Host "Loading Docker image..."
docker load -i $TarFile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Remove existing container if present
$existing = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($existing) {
    Write-Host "Removing existing container..."
    docker rm -f $ContainerName | Out-Null
}

Write-Host "Starting $ContainerName ..."
$runArgs = @(
    "run", "-d",
    "--name", $ContainerName,
    "--restart", "unless-stopped",
    "--hostname", $env:COMPUTERNAME,
    "-e", "SERVER_URL=$ServerUrl",
    "-e", "SERVER_TOKEN=$Token",
    "-e", "HOST_PLATFORM=$HostPlatform"
)

if ($MaxParallelJobs -gt 0) {
    $runArgs += "-e"
    $runArgs += "MAX_PARALLEL_JOBS=$MaxParallelJobs"
}

$runArgs += @("-v", "esphome-versions:/esphome-versions", $Image)

docker @runArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Background) {
    Write-Host "Started in background. Logs: docker logs -f $ContainerName"
} else {
    Write-Host "Started. Tailing logs (Ctrl-C to detach - container keeps running)..."
    docker logs -f $ContainerName
}
