<#
.SYNOPSIS
  Set up the XREAL VR bridge on Windows.

.DESCRIPTION
  Creates a virtual environment, installs this project, optionally copies the
  VRto3D driver from its official zip, writes the recommended VRto3D settings
  after a backup, and creates Start Menu and Desktop shortcuts.

  This script does not change the system OpenXR runtime and does not edit
  steamvr.vrsettings. OpenXR apps that should use SteamVR are started with
  tools\launch-openxr-steamvr.ps1, which sets the runtime for that process only.

.PARAMETER InstallDir
  Folder to install into. Default is D:\VR\xreal-vr-bridge when D: exists,
  otherwise %USERPROFILE%\xreal-vr-bridge. Enter "." in the prompt to set up
  the folder this script is already in.

.PARAMETER DisplayIndex
  VRto3D display_index. Omit to detect the XREAL panel (hardware id MRG4100)
  or to ask. 0 means the primary monitor.

.PARAMETER NonInteractive
  Do not ask questions. Installs to the suggested folder (or -InstallDir),
  downloads the VRto3D driver zip when the driver is missing, and uses the
  detected display index when there is one.

.PARAMETER SkipVRto3D
  Do not download VRto3D and do not edit its config.

.PARAMETER PythonExe
  Python 3.11+ used to create the virtual environment.
#>
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$DisplayIndex,
    [switch]$NonInteractive,
    [switch]$SkipVRto3D,
    [string]$PythonExe
)

$ErrorActionPreference = 'Stop'
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

# No slash or backslash: Windows treats those as path separators inside a .lnk name.
$ShortcutNames = @(
    'XREAL Bridge (SteamVR and Apps, offset 180)',
    'XREAL Bridge (Games and UEVR, offset 0)',
    'XREAL OpenXR via SteamVR (this app only)'
)

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "== $Message"
}

function Invoke-Native {
    # Native programs write to stderr and return non-zero on purpose (py when
    # a version is missing, robocopy when it copies files, winget progress).
    # ErrorActionPreference Stop would turn that into a terminating error
    # before the caller can read $LASTEXITCODE.
    param([Parameter(Mandatory)][scriptblock]$Command)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command
        if ($null -eq $LASTEXITCODE) { $global:LASTEXITCODE = 0 }
    } catch {
        if (-not $LASTEXITCODE) { $global:LASTEXITCODE = 1 }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Read-YesNo([string]$Prompt, [bool]$DefaultYes) {
    if ($NonInteractive) { return $DefaultYes }
    $hint = if ($DefaultYes) { 'Y/n' } else { 'y/N' }
    $answer = Read-Host "$Prompt [$hint]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return $answer -match '^(y|yes)$'
}

function Test-SamePath([string]$Left, [string]$Right) {
    $a = [IO.Path]::GetFullPath($Left).TrimEnd('\')
    $b = [IO.Path]::GetFullPath($Right).TrimEnd('\')
    return $a.Equals($b, [StringComparison]::OrdinalIgnoreCase)
}

function Get-SuggestedInstallDir {
    if (Test-Path -LiteralPath 'D:\') {
        return 'D:\VR\xreal-vr-bridge'
    }
    return (Join-Path $env:USERPROFILE 'xreal-vr-bridge')
}

function Test-Python311Plus([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    try {
        $ver = & $Exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        return $false
    }
    if ($LASTEXITCODE -ne 0 -or -not $ver) { return $false }
    $parts = $ver.Trim().Split('.')
    if ($parts.Length -lt 2) { return $false }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    return ($major -gt 3) -or (($major -eq 3) -and ($minor -ge 11))
}

function Find-PythonExe {
    if ($PythonExe) {
        if (Test-Python311Plus $PythonExe) { return (Resolve-Path -LiteralPath $PythonExe).Path }
        throw "Python at '$PythonExe' is not 3.11 or newer. The 250 Hz sender needs 3.11+ on Windows."
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        # A missing interpreter (py -3.12 when only 3.13 is installed) writes an
        # error and, with ErrorActionPreference Stop, aborts the whole installer.
        # Any 3.11+ is fine, including 3.13. Try the next spec instead.
        foreach ($spec in @('-3.13', '-3.12', '-3.11', '-3')) {
            $exe = $null
            $code = 1
            try {
                $exe = & py $spec -c "import sys; print(sys.executable)" 2>$null
                $code = $LASTEXITCODE
            } catch {
                continue
            }
            if ($code -ne 0 -or -not $exe) { continue }
            $exePath = "$((@($exe) | Select-Object -Last 1))".Trim()
            if (Test-Python311Plus $exePath) { return $exePath }
        }
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Python311Plus $candidate) { return $candidate }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-Python311Plus $python.Source)) { return $python.Source }
    return $null
}

function Install-Python312 {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw @"
Python 3.11 or newer was not found, and winget is not available.
Install Python 3.12 from https://www.python.org/downloads/ (check 'Add python.exe to PATH') and run this installer again.
"@
    }
    Write-Host "Installing Python 3.12 for the current user with winget..."
    Invoke-Native { & winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements }
    # 0 = installed. -1978335189 = already installed, nothing to do.
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        throw "winget could not install Python 3.12 (exit $LASTEXITCODE)."
    }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $env:Path = "$userPath;$machinePath"
}

function Get-SteamRoot {
    $keys = @(
        'HKCU:\Software\Valve\Steam',
        'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam',
        'HKLM:\SOFTWARE\Valve\Steam'
    )
    foreach ($key in $keys) {
        try {
            $item = Get-ItemProperty -Path $key -ErrorAction Stop
        } catch {
            continue
        }
        foreach ($name in @('SteamPath', 'InstallPath')) {
            $value = $item.$name
            if (-not $value) { continue }
            $value = ($value -replace '/', '\')
            if (Test-Path -LiteralPath $value) { return $value }
        }
    }
    foreach ($candidate in @(
        (Join-Path ${env:ProgramFiles(x86)} 'Steam'),
        (Join-Path $env:ProgramFiles 'Steam')
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return $null
}

function Get-SteamLibrary([string]$SteamRoot) {
    $libs = New-Object System.Collections.Generic.List[string]
    $libs.Add($SteamRoot)
    $vdf = Join-Path $SteamRoot 'steamapps\libraryfolders.vdf'
    if (Test-Path -LiteralPath $vdf) {
        foreach ($line in (Get-Content -LiteralPath $vdf)) {
            if ($line -match '"path"\s+"(.+)"') {
                $path = $Matches[1] -replace '\\\\', '\' -replace '/', '\'
                if (Test-Path -LiteralPath $path) { $libs.Add($path) }
            }
        }
    }
    return @($libs | Select-Object -Unique)
}

function Find-SteamVr([string[]]$Libraries) {
    foreach ($lib in $Libraries) {
        $candidate = Join-Path $lib 'steamapps\common\SteamVR'
        if (Test-Path -LiteralPath (Join-Path $candidate 'bin\win64\vrserver.exe')) {
            return $candidate
        }
        if (Test-Path -LiteralPath (Join-Path $candidate 'steamxr_win64.json')) {
            return $candidate
        }
    }
    return $null
}

function Copy-Project([string]$From, [string]$To) {
    if (Test-SamePath $From $To) { return }
    if (-not (Test-Path -LiteralPath (Join-Path $From 'pyproject.toml'))) {
        throw "pyproject.toml is missing in $From. Run install.ps1 from a clone of this repository."
    }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    Write-Host "Copying the project to $To"
    Write-Host "(existing files there are kept; nothing is deleted)"
    Invoke-Native {
        & robocopy $From $To /E /NFL /NDL /NJH /NJS /nc /ns /np `
            /XD .git .venv venv __pycache__ .pytest_cache .mypy_cache `
            /XF .xreal-install.json
    }
    if ($LASTEXITCODE -ge 8) {
        throw "Could not copy the project (robocopy exit $LASTEXITCODE)."
    }
}

function Initialize-VirtualEnvironment([string]$BasePython, [string]$Target) {
    $venvDir = Join-Path $Target '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        if (Test-Python311Plus $venvPython) {
            Write-Host "Reusing the virtual environment in $venvDir"
            return $venvPython
        }
        $brokenName = '.venv.broken-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
        Write-Host "The existing virtual environment is not Python 3.11+. Renaming it to $brokenName"
        Rename-Item -LiteralPath $venvDir -NewName $brokenName
    }
    Write-Host "Creating a virtual environment"
    Invoke-Native { & $BasePython -m venv $venvDir }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        throw "Could not create the virtual environment."
    }
    return $venvPython
}

function Install-Vrto3dDriver([string]$SteamVrRoot) {
    $dest = Join-Path $SteamVrRoot 'drivers\vrto3d'
    $manifest = Join-Path $dest 'driver.vrdrivermanifest'
    if (Test-Path -LiteralPath $manifest) {
        Write-Host "VRto3D is already installed at $dest"
        return
    }
    $page = 'https://github.com/oneup03/VRto3D/releases/latest'
    $zipUrl = 'https://github.com/oneup03/VRto3D/releases/latest/download/vrto3d.zip'
    if (-not (Read-YesNo "VRto3D was not found. Download the official driver zip and copy it into SteamVR? $page" $true)) {
        Write-Host "Skipped. Install VRto3D from $page and run this installer again."
        Write-Host "Copy the vrto3d folder from the zip into:"
        Write-Host "  $dest"
        return
    }
    $work = Join-Path $env:TEMP ('vrto3d-xreal-' + [guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        $zip = Join-Path $work 'vrto3d.zip'
        Write-Host "Downloading $zipUrl"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $work 'unzipped') -Force
        $found = Get-ChildItem -Path (Join-Path $work 'unzipped') -Filter 'driver.vrdrivermanifest' -Recurse -File |
            Select-Object -First 1
        if (-not $found) {
            Write-Host "That zip did not contain a VRto3D driver."
            Write-Host "Install it by hand from $page and copy the vrto3d folder to:"
            Write-Host "  $dest"
            return
        }
        New-Item -ItemType Directory -Force -Path (Join-Path $SteamVrRoot 'drivers') | Out-Null
        Invoke-Native { & robocopy $found.Directory.FullName $dest /E /NFL /NDL /NJH /NJS /nc /ns /np }
        if ($LASTEXITCODE -ge 8) {
            Write-Host "Could not copy the VRto3D driver (robocopy exit $LASTEXITCODE)."
            Write-Host "Copy the vrto3d folder by hand to $dest"
            return
        }
        Write-Host "Installed the VRto3D driver to $dest"
    } catch {
        Write-Host "Download failed: $($_.Exception.Message)"
        Write-Host "Install VRto3D by hand from $page"
        Write-Host "Copy the vrto3d folder from the zip into:"
        Write-Host "  $dest"
    } finally {
        if (Test-Path -LiteralPath $work) {
            Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-BridgeShortcut {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [string]$Path,
        [string]$TargetPath,
        [string]$Arguments,
        [string]$WorkDir,
        [string]$Description
    )
    if (-not $PSCmdlet.ShouldProcess($Path, "Create shortcut")) { return }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $TargetPath
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $WorkDir
    $link.Description = $Description
    $link.Save()
}

function Resolve-InstallDir([string]$ScriptRoot) {
    $suggested = Get-SuggestedInstallDir
    if ($InstallDir) { return $InstallDir }
    if ($NonInteractive) { return $suggested }
    Write-Host "Suggested install folder: $suggested"
    Write-Host "This copy:                $ScriptRoot"
    Write-Host "Press Enter for the suggested folder, type another path, or type . to set up this copy."
    $answer = Read-Host "Install folder"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $suggested }
    if ($answer.Trim() -eq '.') { return $ScriptRoot }
    return $answer.Trim()
}

if ($env:OS -ne 'Windows_NT') {
    Write-Host "install.ps1 runs on Windows."
    exit 1
}

Write-Host "XREAL VR bridge installer"
Write-Host "This installer does not change the system OpenXR runtime and does not edit steamvr.vrsettings."

$scriptRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $scriptRoot 'pyproject.toml'))) {
    throw "Run install.ps1 from the repository root (pyproject.toml was not found next to it)."
}

$target = Resolve-InstallDir $scriptRoot
Write-Step "Install folder"
Write-Host $target
if (-not (Test-SamePath $scriptRoot $target)) {
    Copy-Project $scriptRoot $target
}

Write-Step "Python"
$base = Find-PythonExe
if (-not $base) {
    Install-Python312
    $base = Find-PythonExe
}
if (-not $base) {
    throw "Python 3.11 or newer is still not available. Open a new terminal and run install.bat again."
}
Write-Host "Using $base"
$venvPython = Initialize-VirtualEnvironment $base $target
Write-Host "Installing the bridge into the virtual environment"
Invoke-Native { & $venvPython -m pip install --upgrade pip }
if ($LASTEXITCODE -ne 0) { throw "pip could not upgrade itself." }
Invoke-Native { & $venvPython -m pip install -e $target }
if ($LASTEXITCODE -ne 0) { throw "Could not install the bridge." }

$steamRoot = $null
$steamVr = $null
$manifest = $null
$configPath = $null
$newBackup = $null

if (-not $SkipVRto3D) {
    Write-Step "SteamVR and VRto3D"
    $steamRoot = Get-SteamRoot
    if (-not $steamRoot) {
        Write-Host "Steam was not found. Install Steam and SteamVR, then run this installer again to set up VRto3D."
        Write-Host "The bridge shortcuts will still be created."
    } else {
        Write-Host "Steam: $steamRoot"
        $libs = Get-SteamLibrary $steamRoot
        $steamVr = Find-SteamVr $libs
        if (-not $steamVr) {
            Write-Host "SteamVR was not found. In Steam, install SteamVR (app 250820), then run this installer again."
        } else {
            Write-Host "SteamVR: $steamVr"
            $manifestCandidate = Join-Path $steamVr 'steamxr_win64.json'
            if (Test-Path -LiteralPath $manifestCandidate) { $manifest = $manifestCandidate }
            Install-Vrto3dDriver $steamVr
            $configPath = Join-Path $steamRoot 'config\vrto3d\default_config.json'
            if (-not (Test-Path -LiteralPath $configPath)) {
                Write-Host ""
                Write-Host "VRto3D has not created its config yet."
                Write-Host "Start SteamVR once, quit it, then run this installer again. It will back up that file and set FOV 61, side-by-side 1920x1080, and OpenTrack on port 4242."
            } else {
                $indexArg = @()
                $chosen = $null
                if ($PSBoundParameters.ContainsKey('DisplayIndex') -and -not [string]::IsNullOrWhiteSpace($DisplayIndex)) {
                    $chosen = [int]$DisplayIndex
                } else {
                    $reportRaw = Invoke-Native { & $venvPython -m xreal_vr_bridge.vrto3d --report }
                    if ($LASTEXITCODE -ne 0) { throw "Could not list displays." }
                    $report = $reportRaw | ConvertFrom-Json
                    Write-Host ""
                    Write-Host "Displays in VRto3D order. Index 1 is the primary monitor."
                    Write-Host "display_index 0 also means primary. The glasses are the other number."
                    foreach ($row in @($report.displays)) {
                        $tags = @()
                        if ($row.primary) { $tags += 'primary' }
                        if ($row.xreal) { $tags += 'XREAL' }
                        $suffix = ''
                        if ($tags.Count -gt 0) { $suffix = ' [' + ($tags -join ', ') + ']' }
                        Write-Host ("  {0}: {1} | {2}{3}" -f $row.index, $row.name, $row.id, $suffix)
                    }
                    if ($null -ne $report.xreal_index) {
                        Write-Host "The XREAL panel (MRG4100) looks like display_index $($report.xreal_index)."
                        Write-Host "On the reference laptop, with the laptop as the primary screen, this was 2."
                    } else {
                        Write-Host "No MRG4100 panel was found. Plug in the glasses, or type the index from the list above."
                        Write-Host "Windows Settings, System, Display, Identify is a different numbering. If the picture is on the wrong screen, change display_index and restart SteamVR."
                    }
                    if ($NonInteractive) {
                        if ($null -ne $report.xreal_index) { $chosen = [int]$report.xreal_index }
                    } else {
                        $defaultText = ''
                        if ($null -ne $report.xreal_index) { $defaultText = [string]$report.xreal_index }
                        $typed = Read-Host "display_index [$defaultText] (Enter to accept, s to skip)"
                        if ([string]::IsNullOrWhiteSpace($typed)) {
                            if ($defaultText -ne '') { $chosen = [int]$defaultText }
                        } elseif ($typed -notmatch '^(s|skip)$') {
                            $chosen = [int]$typed
                        }
                    }
                }
                if ($null -ne $chosen) { $indexArg = @('--display-index', "$chosen") }
                $applyRaw = Invoke-Native { & $venvPython -m xreal_vr_bridge.vrto3d --apply --config $configPath @indexArg }
                $applyCode = $LASTEXITCODE
                if ($applyCode -eq 1) { throw "Could not update the VRto3D config: $applyRaw" }
                $apply = $applyRaw | ConvertFrom-Json
                if ($apply.status -eq 'updated') {
                    $newBackup = [string]$apply.backup
                    Write-Host "Updated $configPath"
                    Write-Host "Previous file copied to $newBackup"
                    Write-Host "Restart SteamVR. In a game, Ctrl+Shift+F10 reloads FOV and the other profile values."
                } elseif ($apply.status -eq 'unchanged') {
                    Write-Host "VRto3D config already has the recommended settings."
                }
            }
        }
    }
}

Write-Step "Shortcuts"
$desktop = [Environment]::GetFolderPath('Desktop')
$startDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\XREAL VR Bridge'
New-Item -ItemType Directory -Force -Path $startDir | Out-Null
$pythonw = $venvPython
$created = @()

function Publish-Shortcut([string]$Name, [string]$TargetPath, [string]$Arguments, [string]$Description) {
    foreach ($dir in @($desktop, $startDir)) {
        $path = Join-Path $dir ($Name + '.lnk')
        New-BridgeShortcut -Path $path -TargetPath $TargetPath -Arguments $Arguments -WorkDir $target -Description $Description
        $script:created += $path
        Write-Host $path
    }
}

Publish-Shortcut -Name $ShortcutNames[0] -TargetPath $pythonw `
    -Arguments '-m xreal_vr_bridge.cli --recenter-yaw-offset 180' `
    -Description 'XREAL head tracking for SteamVR home and Unity apps. Yaw offset 180.'
Publish-Shortcut -Name $ShortcutNames[1] -TargetPath $pythonw `
    -Arguments '-m xreal_vr_bridge.cli --recenter-yaw-offset 0' `
    -Description 'XREAL head tracking for UEVR and other games. Yaw offset 0.'

$launcher = Join-Path $target 'tools\launch-openxr-steamvr.ps1'
$powerShellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$launcherArgs = "-NoProfile -STA -ExecutionPolicy Bypass -File `"$launcher`""
Publish-Shortcut -Name $ShortcutNames[2] -TargetPath $powerShellExe -Arguments $launcherArgs `
    -Description 'Start one OpenXR app with SteamVR. Other apps keep their current runtime.'

$markerPath = Join-Path $target '.xreal-install.json'
$backups = @()
if (Test-Path -LiteralPath $markerPath) {
    try {
        $old = Get-Content -Raw -LiteralPath $markerPath | ConvertFrom-Json
        if ($old.vrto3d_backups) { $backups = @($old.vrto3d_backups) }
    } catch {
        Write-Host "Could not read the existing install notes. A new file will be written."
    }
}
if ($newBackup) { $backups += $newBackup }
$marker = [ordered]@{
    version = 1
    install_dir = $target
    shortcuts = @($created)
    steam_root = $steamRoot
    steamvr_root = $steamVr
    openxr_manifest = $manifest
    vrto3d_config = $configPath
    vrto3d_backups = @($backups | Where-Object { $_ })
}
$marker | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $markerPath -Encoding UTF8

Write-Step "Ready"
Write-Host "1. On the glasses: Follow mode, stabilizer off, 3840x1080 side-by-side where the glasses offer it."
Write-Host "2. Start 'XREAL Bridge (SteamVR and Apps, offset 180)' and hold the glasses still for a few seconds."
Write-Host "   The window should say 'Fusion mode: ref' and 'Glasses are still'."
Write-Host "3. Start SteamVR. For a UEVR game, use the offset 0 shortcut instead, and inject with OpenVR."
Write-Host "4. OpenXR apps that should use the glasses: use 'XREAL OpenXR via SteamVR (this app only)'."
Write-Host "   That sets the runtime for the program you pick. It does not change the system OpenXR runtime."
Write-Host ""
Write-Host "Uninstall with uninstall.bat in $target"
if (-not $NonInteractive) {
    Write-Host ""
    Read-Host "Press Enter to close"
}
exit 0
