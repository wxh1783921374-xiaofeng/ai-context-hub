param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
Set-Location -LiteralPath $ProjectRoot

Write-Host "AI Context Hub installer"
Write-Host "Project: $ProjectRoot"

$python = Get-Command python -ErrorAction Stop
& $python.Source --version

$venvPath = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path -LiteralPath $venvPath)) {
    & $python.Source -m venv $venvPath
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e ".[dev]"
& $venvPython -m ai_context_hub.cli init
& $venvPython -m ai_context_hub.cli pair-extension

$localBin = Join-Path $env:USERPROFILE ".local\bin"
New-Item -ItemType Directory -Force -Path $localBin | Out-Null
$locationFile = Join-Path $env:USERPROFILE ".ai-context-hub-location"
Set-Content -LiteralPath $locationFile -Value $ProjectRoot -Encoding UTF8

$launcherPs1 = Join-Path $localBin "ai-context.ps1"
$launcherPsContent = @'
$ErrorActionPreference = "Stop"
$LocationFile = Join-Path $env:USERPROFILE ".ai-context-hub-location"
$ProjectLocation = (Get-Content -LiteralPath $LocationFile -Raw -Encoding UTF8).Trim()
$Python = Join-Path $ProjectLocation ".venv\Scripts\python.exe"
& $Python -m ai_context_hub.cli @args
exit $LASTEXITCODE
'@
Set-Content -LiteralPath $launcherPs1 -Value $launcherPsContent -Encoding ASCII

$launcherPath = Join-Path $localBin "ai-context.cmd"
$launcher = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%USERPROFILE%\.local\bin\ai-context.ps1`" %*"
Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathParts = @()
if ($userPath) {
    $pathParts = $userPath.Split(";", [System.StringSplitOptions]::RemoveEmptyEntries)
}
if ($pathParts -notcontains $localBin) {
    $newPath = (@($pathParts) + $localBin) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Added $localBin to the user PATH. Open a new terminal to use it."
}

$codexSkills = Join-Path $env:USERPROFILE ".codex\skills"
New-Item -ItemType Directory -Force -Path $codexSkills | Out-Null
$codexSkillsResolved = (Resolve-Path -LiteralPath $codexSkills).Path
$skillSource = Join-Path $ProjectRoot "skills\ai-context-hub"
$skillTarget = Join-Path $codexSkills "ai-context-hub"
if (Test-Path -LiteralPath $skillTarget) {
    $skillTargetResolved = (Resolve-Path -LiteralPath $skillTarget).Path
    $expectedPrefix = $codexSkillsResolved.TrimEnd("\") + "\"
    if (-not $skillTargetResolved.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the Codex skills directory: $skillTargetResolved"
    }
    Remove-Item -LiteralPath $skillTarget -Recurse -Force
}
Copy-Item -LiteralPath $skillSource -Destination $skillTarget -Recurse

$tokenPath = Join-Path $ProjectRoot "local-vault\token"
Write-Host ""
Write-Host "Installation complete."
Write-Host "Start: powershell -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\start.ps1`""
Write-Host "Extension directory: $ProjectRoot\extension"
Write-Host "Pairing token file: $tokenPath"
Write-Host "Restart Codex or open a new chat if the skill list has not refreshed."
