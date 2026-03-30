# ESPHome Distributed Build Client — stop script (Windows/PowerShell)
$ErrorActionPreference = "Stop"
$ContainerName = "esphome-dist-client"

$running = docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($running) {
    Write-Host "Stopping $ContainerName ..."
    docker stop $ContainerName | Out-Null
}

$exists = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $ContainerName }
if ($exists) {
    Write-Host "Removing $ContainerName ..."
    docker rm $ContainerName | Out-Null
}

Write-Host "Done."
