param(
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Not installed. Run scripts\install.ps1 first."
}

$Args = @("-m", "ai_context_hub.cli", "serve")
if ($NoOpen) {
    $Args += "--no-open"
}
& $Python @Args
