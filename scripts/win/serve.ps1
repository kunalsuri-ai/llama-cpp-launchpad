# llama-cpp-launchpad for Windows (PowerShell 5.1+ or PowerShell 7).
# Pick a .gguf model and an interface with the arrow keys, then serve it with llama.cpp's llama-server.
#
# Settings (all optional, via environment variables):
#   MODELS_DIR      folder with your .gguf files          (default: <project>\models)
#   LLAMA_SERVER    path to llama-server.exe              (default: auto-detected)
#   PORT            port to serve on                      (default: 8080)
#   KILL_EXISTING   1 = stop running llama-server first   (default: 1, set 0 to disable)
#   OPEN_BROWSER    1 = open the web UI when ready        (default: 1, set 0 to disable)
#   UI              default | translation: skip the interface menu and use this one
#   EXTRA_ARGS      extra flags passed to llama-server    (e.g. "-t 8 -c 8192")

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir   = Split-Path -Parent (Split-Path -Parent $ScriptDir)   # project root (scripts\win -> root)

function Get-Setting([string]$Name, [string]$Default) {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($v)) { return $Default } else { return $v }
}

$ModelsDir    = Get-Setting 'MODELS_DIR' (Join-Path $RootDir 'models')
$Port         = Get-Setting 'PORT' '8080'
$KillExisting = Get-Setting 'KILL_EXISTING' '1'
$OpenBrowser  = Get-Setting 'OPEN_BROWSER' '1'
$ExtraArgs    = Get-Setting 'EXTRA_ARGS' ''
$UiChoice     = (Get-Setting 'UI' '').ToLower()

# --- Locate llama-server -----------------------------------------------------
function Find-LlamaServer {
    $override = Get-Setting 'LLAMA_SERVER' ''
    if ($override) { return $override }
    $cmd = Get-Command llama-server -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $RootDir 'bin\llama-server.exe'
    if (Test-Path $local) { return $local }
    return $null
}

$Server = Find-LlamaServer
if (-not $Server -or -not (Test-Path $Server)) {
    Write-Host 'Could not find llama-server.' -ForegroundColor Red
    Write-Host "Looked in: `$env:LLAMA_SERVER, your PATH, $RootDir\bin"
    Write-Host ''
    Write-Host 'Install llama.cpp, for example:  winget install llama.cpp'
    Write-Host 'Then open a NEW terminal so it is on your PATH (see README.md), or run:'
    Write-Host '  $env:LLAMA_SERVER = "C:\path\to\llama-server.exe"'
    exit 1
}

# --- Stop any running server -------------------------------------------------
if ($KillExisting -eq '1') {
    $running = Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host '* Stopping running llama-server... ' -ForegroundColor Yellow -NoNewline
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 50; $i++) {
            if (-not (Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 100
        }
        Write-Host 'done'
    }
}

# --- Collect models (skip multimodal projector files) ------------------------
$models = @(Get-ChildItem -Path $ModelsDir -Filter '*.gguf' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike 'mmproj*' } | Sort-Object Name)
if ($models.Count -eq 0) {
    Write-Host "No .gguf models found in $ModelsDir" -ForegroundColor Red
    Write-Host 'Download one, e.g. from https://huggingface.co/ggml-org (see README.md).'
    exit 1
}

function Format-Size([long]$Bytes) {
    if ($Bytes -ge 1GB) { return ('{0:N1}G' -f ($Bytes / 1GB)) }
    return ('{0:N0}M' -f ($Bytes / 1MB))
}

# --- Arrow-key menu ----------------------------------------------------------
$script:menuSel = 0
$script:menuTop = 0
$script:menuItems = @()
$script:menuNotes = @()

function Show-Menu {
    [Console]::SetCursorPosition(0, $script:menuTop)
    $width = [Math]::Max(20, [Console]::WindowWidth - 1)
    for ($i = 0; $i -lt $script:menuItems.Count; $i++) {
        if ($i -eq $script:menuSel) {
            $line = ('  > {0,-42} {1,13}' -f $script:menuItems[$i], $script:menuNotes[$i]).PadRight($width)
            Write-Host $line -ForegroundColor Yellow
        } else {
            $line = ('    {0,-42} {1,13}' -f $script:menuItems[$i], $script:menuNotes[$i]).PadRight($width)
            Write-Host $line -ForegroundColor DarkGray
        }
    }
}

# Shows a menu, returns the chosen index. The menu collapses once you choose.
function Select-Menu([string]$Title, [string[]]$Items, [string[]]$Notes) {
    $script:menuItems = $Items; $script:menuNotes = $Notes; $script:menuSel = 0
    Write-Host '  ' -NoNewline
    Write-Host $Title -NoNewline
    Write-Host '  Up/Down move, Enter select, Q quit' -ForegroundColor DarkGray
    Write-Host ''
    # Print once so the console scrolls if needed, then remember where the menu starts.
    for ($i = 0; $i -lt $Items.Count; $i++) { Write-Host '' }
    $script:menuTop = [Console]::CursorTop - $Items.Count
    try {
        [Console]::CursorVisible = $false
        Show-Menu
        while ($true) {
            $key = [Console]::ReadKey($true)
            switch ($key.Key) {
                'UpArrow'   { if ($script:menuSel -gt 0) { $script:menuSel-- } }
                'DownArrow' { if ($script:menuSel -lt $Items.Count - 1) { $script:menuSel++ } }
                'Escape'    { exit 0 }
                'Q'         { exit 0 }
                'K'         { if ($script:menuSel -gt 0) { $script:menuSel-- } }
                'J'         { if ($script:menuSel -lt $Items.Count - 1) { $script:menuSel++ } }
            }
            if ($key.Key -eq 'Enter') { break }
            Show-Menu
        }
    } finally {
        [Console]::CursorVisible = $true
    }
    # Collapse the menu (items + blank line + heading) so the next step starts clean
    $heading = $script:menuTop - 2
    [Console]::SetCursorPosition(0, $heading)
    $blank = ' ' * ([Math]::Max(20, [Console]::WindowWidth - 1))
    for ($i = 0; $i -lt $Items.Count + 2; $i++) { Write-Host $blank }
    [Console]::SetCursorPosition(0, $heading)
    return $script:menuSel
}

function Write-Choice([string]$Label, [string]$Value) {
    Write-Host '  * ' -ForegroundColor Green -NoNewline
    Write-Host ('{0,-10}' -f $Label) -ForegroundColor DarkGray -NoNewline
    Write-Host $Value
}

$interactive = -not [Console]::IsInputRedirected

# --- Step 1: model -----------------------------------------------------------
if ($interactive) {
    Write-Host ''
    Write-Host '  * llama-cpp-launchpad  ' -ForegroundColor Yellow -NoNewline
    Write-Host 'local model server' -ForegroundColor DarkGray
    Write-Host "  $ModelsDir" -ForegroundColor DarkGray
    Write-Host ''
    $notes = @($models | ForEach-Object { Format-Size $_.Length })
    $modelIdx = Select-Menu 'Choose a model' @($models | ForEach-Object { $_.Name }) $notes
} else {
    # Non-interactive: read a 1-based number from stdin
    $modelIdx = [int](Read-Host) - 1
    if ($modelIdx -lt 0 -or $modelIdx -ge $models.Count) { Write-Host 'Invalid model choice'; exit 1 }
}
$model = $models[$modelIdx]
if ($interactive) { Write-Choice 'Model' $model.Name }

# --- Step 2: interface -------------------------------------------------------
$uiNames = @('llama.cpp Default', 'Translation')
$uiKeys  = @('default', 'translation')
$uiIdx = [Array]::IndexOf($uiKeys, $UiChoice)
if ($uiIdx -lt 0) {
    if ($interactive) {
        Write-Host ''
        $uiIdx = Select-Menu 'Choose an interface' $uiNames @('built-in chat', 'translator')
    } else {
        $u = $null
        try { $u = Read-Host } catch { }
        if ([string]::IsNullOrWhiteSpace($u)) { $u = '1' }
        $uiIdx = [int]$u - 1
        if ($uiIdx -lt 0 -or $uiIdx -ge $uiKeys.Count) { Write-Host 'Invalid interface choice'; exit 1 }
    }
}
Write-Choice 'Interface' $uiNames[$uiIdx]
$UiMode = $uiKeys[$uiIdx]

# --- Serve -------------------------------------------------------------------
$Url = "http://localhost:$Port"
Write-Host ''
Write-Host '  * ' -ForegroundColor Green -NoNewline
Write-Host "Loading $($model.Name)"
Write-Host '  Serving at ' -ForegroundColor DarkGray -NoNewline
Write-Host $Url -ForegroundColor Cyan -NoNewline
Write-Host '  (Ctrl+C to stop)' -ForegroundColor DarkGray
Write-Host ''

# Open the browser once the server is up
if ($OpenBrowser -eq '1') {
    Start-Job -ScriptBlock {
        param($Url)
        for ($i = 0; $i -lt 120; $i++) {
            try {
                Invoke-WebRequest -Uri "$Url/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
                Start-Process $Url
                return
            } catch { Start-Sleep -Seconds 1 }
        }
    } -ArgumentList $Url | Out-Null
}

$serverArgs = @('-m', $model.FullName, '--port', $Port)
if ($UiMode -eq 'translation') {
    $uiDir = Join-Path (Join-Path $RootDir 'ui') 'translation'
    if (Test-Path (Join-Path $uiDir 'index.html')) {
        $serverArgs += @('--path', $uiDir)
    } else {
        Write-Host "Translation UI not found at $uiDir, using the default." -ForegroundColor Red
    }
}
if ($ExtraArgs) { $serverArgs += @($ExtraArgs -split '\s+' | Where-Object { $_ }) }
& $Server @serverArgs
