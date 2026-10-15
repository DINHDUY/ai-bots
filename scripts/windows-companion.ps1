param(
    [ValidateSet('setup', 'pair', 'run', 'test', 'forget')]
    [string]$Command = 'run',
    [string]$Backend = 'http://127.0.0.1:8000'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$companionPython = Join-Path $repo 'data/ufo/venv/Scripts/python.exe'
$ufoSource = Join-Path $repo 'data/ufo/upstream'
$companionPackage = Join-Path $repo 'packages/agentbot-windows-companion'
if ($Command -eq 'setup') {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
    if (-not (Test-Path -LiteralPath $companionPython)) {
        & uv venv --python 3.11 (Join-Path $repo 'data/ufo/venv')
        if ($LASTEXITCODE) { throw 'Python environment creation failed' }
    }
    & uv pip sync --python $companionPython --require-hashes (Join-Path $companionPackage 'requirements-ufo.lock')
    if ($LASTEXITCODE) { throw 'Locked dependency installation failed' }
    & uv pip install --python $companionPython --no-deps -e $companionPackage
    if ($LASTEXITCODE) { throw 'Companion package installation failed' }
    & $companionPython -m agentbot_windows.app prepare --source $ufoSource
} elseif (-not (Test-Path -LiteralPath $companionPython)) {
    throw 'Run ./scripts/windows-companion.ps1 setup first'
} elseif ($Command -eq 'test') {
    & $companionPython (Join-Path $companionPackage 'tests/job_probe.py')
    if ($LASTEXITCODE) { throw 'Worker supervision qualification failed' }
    & $companionPython (Join-Path $companionPackage 'tests/native_probe.py')
} else {
    & $companionPython -m agentbot_windows.app $Command --source $ufoSource --backend $Backend
}
if ($LASTEXITCODE) { throw "Windows companion $Command failed" }
