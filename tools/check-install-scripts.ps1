# Parse the Windows installer scripts and fail if they call a function that
# is neither defined in that file nor a real command. Also reject shortcut
# titles that contain a slash: CreateShortcut treats '/' as a directory.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$scripts = @(
    (Join-Path $root 'install.ps1'),
    (Join-Path $root 'uninstall.ps1'),
    (Join-Path $root 'tools\launch-openxr-steamvr.ps1')
)
$failed = $false

foreach ($path in $scripts) {
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors -and $parseErrors.Count -gt 0) {
        foreach ($err in $parseErrors) {
            Write-Host "$path`:$($err.Extent.StartLineNumber): $($err.Message)"
        }
        $failed = $true
        continue
    }

    $defined = @{}
    $functions = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true)
    foreach ($fn in $functions) {
        $defined[$fn.Name.ToLowerInvariant()] = $true
    }

    $commands = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.CommandAst]
    }, $true)
    foreach ($command in $commands) {
        $name = $command.GetCommandName()
        if (-not $name) { continue }
        if ($name -notmatch '^[A-Za-z][A-Za-z0-9]*-[A-Za-z]') { continue }
        if ($defined.ContainsKey($name.ToLowerInvariant())) { continue }
        $resolved = Get-Command -Name $name -ErrorAction SilentlyContinue
        if (-not $resolved) {
            $line = $command.Extent.StartLineNumber
            Write-Host "$path`:${line}: undefined function or command '$name'"
            $failed = $true
        }
    }
    Write-Host "parsed $(Split-Path -Leaf $path) ($($defined.Count) functions)"
}

$shortcutSources = $scripts + @(Join-Path $root 'README.md')
foreach ($path in $shortcutSources) {
    $text = Get-Content -Raw -LiteralPath $path
    foreach ($match in [regex]::Matches($text, 'XREAL Bridge \([^)\r\n]*\)')) {
        if ($match.Value -match '[\\/]') {
            Write-Host "$path`: shortcut name contains a path separator: $($match.Value)"
            $failed = $true
        }
    }
}

if ($failed) { exit 1 }
Write-Host "installer scripts ok"
exit 0
