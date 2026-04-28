$TaskName = "VMwareWebManager"
$WorkingDir = Get-Location
# Get the absolute path to uv.exe
$UvPath = (Get-Command uv.exe).Source
if (-not $UvPath) {
    # Fallback to common uv location if not in PATH for some reason
    $UvPath = "$env:USERPROFILE\.cargo\bin\uv.exe"
}
$LogFile = "$WorkingDir\install.log"

"Installing $TaskName..." | Out-File $LogFile

# Create the action: run uvicorn through uv in a hidden window
# We set LOG_LEVEL to WARNING by default
$Arguments = "run uvicorn main:app --host 0.0.0.0 --port 8000"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -Command `"`$env:LOG_LEVEL='WARNING'; $UvPath $Arguments`"" -WorkingDirectory $WorkingDir

# Create the trigger: at system startup
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Create the settings: allow running without being logged in, highest privileges
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Register the task under the current user account with Highest privileges
# This ensures vmrun can see the user's running VMs.
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
try {
    Register-ScheduledTask -Action $Action -Trigger $Trigger -TaskName $TaskName -User $CurrentUser -RunLevel Highest -Settings $Settings -Force
    "Successfully registered task $TaskName for user $CurrentUser." | Out-File $LogFile -Append
    Write-Host "Successfully registered task $TaskName for user $CurrentUser."
    Write-Host "It will run automatically on system boot (or when you log in)."
    Write-Host "To start it now, run: Start-ScheduledTask -TaskName $TaskName"
} catch {
    "Failed to register task: $_" | Out-File $LogFile -Append
    Write-Error "Failed to register task. Ensure you are running as Administrator."
}
