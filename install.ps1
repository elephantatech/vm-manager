$TaskName = "VMwareWebManager"
$WorkingDir = Get-Location
$UvPath = (Get-Command uv).Source
$LogFile = "$WorkingDir\install.log"

"Installing $TaskName..." | Out-File $LogFile

# Create the action: run uvicorn through uv
# We use --host 0.0.0.0 to allow LAN access
$Action = New-ScheduledTaskAction -Execute $UvPath -Argument "run uvicorn main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $WorkingDir

# Create the trigger: at system startup
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Create the settings: allow running without being logged in, highest privileges
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register the task under the SYSTEM account with Highest privileges
try {
    Register-ScheduledTask -Action $Action -Trigger $Trigger -TaskName $TaskName -User "SYSTEM" -RunLevel Highest -Settings $Settings -Force
    "Successfully registered task $TaskName." | Out-File $LogFile -Append
    Write-Host "Successfully registered task $TaskName. It will run automatically on system boot."
    Write-Host "To start it now, run: Start-ScheduledTask -TaskName $TaskName"
} catch {
    "Failed to register task: $_" | Out-File $LogFile -Append
    Write-Error "Failed to register task. Ensure you are running as Administrator."
}
