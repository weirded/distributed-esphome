# ESPHome Distributed Build Client — uninstall script (Windows/PowerShell)
$ErrorActionPreference = "Stop"
$ContainerName = "esphome-dist-client"
$Image = "esphome-dist-client"

$running = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($running) {
    Write-Host "Stopping $ContainerName ..."
    docker stop $ContainerName | Out-Null
}

$exists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($exists) {
    Write-Host "Removing container $ContainerName ..."
    docker rm $ContainerName | Out-Null
}

$imgExists = docker image inspect $Image 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Removing image $Image ..."
    docker rmi $Image | Out-Null
}

$answer = Read-Host "Also remove the esphome-versions volume (cached ESPHome installs)? [y/N]"
if ($answer -match "^[Yy]$") {
    docker volume rm esphome-versions 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "Volume removed." } else { Write-Host "Volume not found." }
}

Write-Host "Uninstall complete."
