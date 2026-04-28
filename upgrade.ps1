$TaskName = "VMwareWebManager"
$WorkingDir = Get-Location

Write-Host "Stopping $TaskName..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

Write-Host "Syncing dependencies with uv..." -ForegroundColor Cyan
uv sync

Write-Host "Re-applying installation settings..." -ForegroundColor Cyan
powershell.exe -ExecutionPolicy Bypass -File install.ps1

Write-Host "Restarting $TaskName..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $TaskName

Write-Host "Upgrade complete! The service is running the latest code." -ForegroundColor Green
