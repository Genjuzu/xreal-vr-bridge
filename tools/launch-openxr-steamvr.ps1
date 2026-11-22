<#
.SYNOPSIS
  Start one program with SteamVR as its OpenXR runtime.

.DESCRIPTION
  Sets XR_RUNTIME_JSON for the program you name, then starts it.
  The variable applies to that process and the processes it spawns.
  Nothing is written for other programs. Virtual Desktop, the Oculus app,
  and every other OpenXR app keep whatever runtime they already use.

.PARAMETER Exe
  Program to start. If omitted, a file dialog asks for an .exe.

.PARAMETER Arguments
  Arguments passed to that program.

.PARAMETER SteamVrRoot
  SteamVR folder that contains steamxr_win64.json. Searched automatically
  when omitted.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Exe,
    [string]$Arguments = '',
    [string]$SteamVrRoot
)

$ErrorActionPreference = 'Stop'

function Get-SteamRoot {
    foreach ($key in @(
        'HKCU:\Software\Valve\Steam',
        'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam',
        'HKLM:\SOFTWARE\Valve\Steam'
    )) {
        try { $item = Get-ItemProperty -Path $key -ErrorAction Stop } catch { continue }
        foreach ($name in @('SteamPath', 'InstallPath')) {
            $value = $item.$name
            if (-not $value) { continue }
            $value = ($value -replace '/', '\')
            if (Test-Path -LiteralPath $value) { return $value }
        }
    }
    return $null
}

function Find-SteamXrManifest([string]$Hint) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Hint) { $candidates.Add((Join-Path $Hint 'steamxr_win64.json')) }
    $marker = Join-Path (Split-Path -Parent $PSScriptRoot) '.xreal-install.json'
    if (Test-Path -LiteralPath $marker) {
        try {
            $saved = Get-Content -Raw -LiteralPath $marker | ConvertFrom-Json
            if ($saved.openxr_manifest) { $candidates.Add([string]$saved.openxr_manifest) }
            if ($saved.steamvr_root) { $candidates.Add((Join-Path ([string]$saved.steamvr_root) 'steamxr_win64.json')) }
        } catch {
            Write-Host "Could not read $marker. Searching Steam instead."
        }
    }
    $steam = Get-SteamRoot
    if ($steam) {
        $candidates.Add((Join-Path $steam 'steamapps\common\SteamVR\steamxr_win64.json'))
        $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf) {
            foreach ($line in (Get-Content -LiteralPath $vdf)) {
                if ($line -match '"path"\s+"(.+)"') {
                    $lib = $Matches[1] -replace '\\\\', '\' -replace '/', '\'
                    $candidates.Add((Join-Path $lib 'steamapps\common\SteamVR\steamxr_win64.json'))
                }
            }
        }
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

if (-not $Exe) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.Filter = 'Programs (*.exe)|*.exe|All files (*.*)|*.*'
        $dialog.Title = 'Choose the OpenXR app to launch with SteamVR'
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
            Write-Host "No program selected."
            exit 1
        }
        $Exe = $dialog.FileName
    } catch {
        Write-Host "Could not open a file dialog ($($_.Exception.Message))."
        $Exe = Read-Host "Full path of the .exe (leave empty to cancel)"
        if ([string]::IsNullOrWhiteSpace($Exe)) {
            Write-Host "No program selected."
            exit 1
        }
    }
}

if (-not (Test-Path -LiteralPath $Exe)) {
    Write-Host "Program not found: $Exe"
    exit 1
}

$manifest = Find-SteamXrManifest $SteamVrRoot
if (-not $manifest) {
    Write-Host "Could not find steamxr_win64.json."
    Write-Host "Install SteamVR, or pass -SteamVrRoot with the SteamVR folder."
    exit 1
}

Write-Host "OpenXR for this process only:"
Write-Host "  $manifest"
Write-Host "Other programs are unchanged."

$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = (Resolve-Path -LiteralPath $Exe).Path
$start.Arguments = $Arguments
$start.WorkingDirectory = (Split-Path -Parent $start.FileName)
$start.UseShellExecute = $false
$start.EnvironmentVariables['XR_RUNTIME_JSON'] = $manifest
$process = [System.Diagnostics.Process]::Start($start)
if (-not $process) {
    Write-Host "The program did not start."
    exit 1
}
Write-Host "Started $($start.FileName) (pid $($process.Id))"
exit 0
