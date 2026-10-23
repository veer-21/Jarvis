<#
.SYNOPSIS
    JARVIS AI Assistant - Windows Desktop Shortcut Creator (Phase 7.0 & 8.0)
.DESCRIPTION
    Uses the Windows Script Host (WScript.Shell) COM object to safely create
    or update a 1-click desktop shortcut pointing to Start_Jarvis.bat.
#>

[CmdletBinding()]
param(
    [string]$TargetDirectory = "D:\Jarvis",
    [string]$ShortcutName = "JARVIS AI Assistant.lnk"
)

try {
    $WshShell = New-Object -ComObject WScript.Shell
    $DesktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
    $ShortcutPath = Join-Path -Path $DesktopPath -ChildPath $ShortcutName
    $TargetBat = Join-Path -Path $TargetDirectory -ChildPath "Start_Jarvis.bat"

    if (-not (Test-Path $TargetBat)) {
        Write-Warning "Target launcher '$TargetBat' does not exist yet. Generating shortcut anyway."
    }

    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetBat
    $Shortcut.WorkingDirectory = $TargetDirectory
    $Shortcut.WindowStyle = 1
    $Shortcut.Description = "JARVIS AI Assistant - Personal AI Operating System"
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
    $Shortcut.Save()

    Write-Host "[SUCCESS] JARVIS desktop shortcut created successfully at: $ShortcutPath" -ForegroundColor Cyan
}
catch {
    Write-Error "Failed to create desktop shortcut: $_"
    exit 1
}
