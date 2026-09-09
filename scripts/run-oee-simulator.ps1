# Run the OEE demo MQTT publisher on the host (requires Git Bash + running stack).
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$bash = Join-Path ${env:ProgramFiles} "Git\bin\bash.exe"
if (-not (Test-Path $bash)) {
    Write-Error "Git Bash not found at $bash. Install Git for Windows or run from Git Bash: ./HiveMQ-Simulator.sh"
}
& $bash -lc "cd '$($repoRoot -replace '\\', '/')' && ./HiveMQ-Simulator.sh"
