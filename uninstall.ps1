<#
.SYNOPSIS
  Remove the XREAL VR bridge shortcuts created by install.ps1.

.DESCRIPTION
  Removes the Start Menu and Desktop shortcuts this project created.
  Does not delete the project folder, SteamVR, VRto3D, or your documents.
  Does not change the system OpenXR runtime.

  The virtual environment is removed only with -RemoveVenv (or if you answer
  yes to the prompt). A VRto3D config backup is restored only with
  -RestoreConfig (or if you answer yes). Restoring copies the current config
  aside first and does not delete the backup.
#>
[CmdletBinding()]
param(
    [string]$InstallDir,
    [switch]$NonInteractive,
    [switch]$RemoveVenv,
    [switch]$RestoreConfig
)

$ErrorActionPreference = 'Stop'

$ShortcutNames = @(
    'XREAL Bridge (SteamVR and Apps, offset 180).lnk',
    'XREAL Bridge (Games and UEVR, offset 0).lnk',
    'XREAL OpenXR via SteamVR (this app only).lnk'
)

function Read-YesNo([string]$Prompt, [bool]$DefaultYes) {
    if ($NonInteractive) { return $DefaultYes }
    $hint = if ($DefaultYes) { 'Y/n' } else { 'y/N' }
    $answer = Read-Host "$Prompt [$hint]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return $answer -match '^(y|yes)$'
}

if ($env:OS -ne 'Windows_NT') {
    Write-Host "uninstall.ps1 runs on Windows."
    exit 1
}

$root = $InstallDir
if (-not $root) { $root = $PSScriptRoot }
$markerPath = Join-Path $root '.xreal-install.json'
$marker = $null
if (Test-Path -LiteralPath $markerPath) {
    try {
        $marker = Get-Content -Raw -LiteralPath $markerPath | ConvertFrom-Json
    } catch {
        Write-Host "Could not read $markerPath. Shortcuts will still be removed by name."
    }
}

Write-Host "Removing XREAL VR bridge shortcuts."
Write-Host "The project folder is left in place: $root"

$paths = New-Object System.Collections.Generic.List[string]
if ($marker -and $marker.shortcuts) {
    foreach ($path in @($marker.shortcuts)) {
        if ($path) { $paths.Add([string]$path) }
    }
}
$desktop = [Environment]::GetFolderPath('Desktop')
$startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\XREAL VR Bridge'
foreach ($dir in @($desktop, $startDir)) {
    foreach ($name in $ShortcutNames) {
        $paths.Add((Join-Path $dir $name))
    }
}

$seen = @{}
foreach ($path in $paths) {
    if ($seen.ContainsKey($path)) { continue }
    $seen[$path] = $true
    if (-not (Test-Path -LiteralPath $path)) { continue }
    if ([IO.Path]::GetExtension($path) -ne '.lnk') {
        Write-Host "Skipped (not a shortcut): $path"
        continue
    }
    Remove-Item -LiteralPath $path -Force
    Write-Host "Removed $path"
}

if (Test-Path -LiteralPath $startDir) {
    $left = Get-ChildItem -LiteralPath $startDir -Force
    if (-not $left) {
        Remove-Item -LiteralPath $startDir -Force
        Write-Host "Removed empty Start Menu folder $startDir"
    }
}

$doVenv = $RemoveVenv
if (-not $PSBoundParameters.ContainsKey('RemoveVenv') -and -not $NonInteractive) {
    $doVenv = Read-YesNo "Remove the Python virtual environment in $root\.venv ?" $false
}
$venv = Join-Path $root '.venv'
if ($doVenv -and (Test-Path -LiteralPath $venv)) {
    Remove-Item -LiteralPath $venv -Recurse -Force
    Write-Host "Removed $venv"
} else {
    Write-Host "Left the virtual environment in place."
}

$doRestore = $RestoreConfig
if (-not $PSBoundParameters.ContainsKey('RestoreConfig') -and -not $NonInteractive) {
    $doRestore = Read-YesNo "Restore the newest VRto3D config backup this installer made?" $false
}
if ($doRestore -and $marker -and $marker.vrto3d_config -and $marker.vrto3d_backups) {
    $cfg = [string]$marker.vrto3d_config
    $backups = @($marker.vrto3d_backups | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
    if ((Test-Path -LiteralPath $cfg) -and $backups.Count -gt 0) {
        $latest = [string]$backups[-1]
        $aside = $cfg + '.before-restore-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
        Copy-Item -LiteralPath $cfg -Destination $aside
        Copy-Item -LiteralPath $latest -Destination $cfg -Force
        Write-Host "Restored $latest"
        Write-Host "The config that was current is now at $aside"
    } else {
        Write-Host "No VRto3D backup was available to restore."
    }
}

Write-Host ""
Write-Host "Done. SteamVR, VRto3D, and the system OpenXR runtime were not modified by this uninstall,"
Write-Host "except for a config restore you explicitly asked for."
Write-Host "The source folder is still at $root"
if (-not $NonInteractive) {
    Write-Host ""
    Read-Host "Press Enter to close"
}
exit 0
