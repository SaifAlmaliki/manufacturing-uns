# Run Halabja MES/LIMS/SAP (+ machine) MQTT publishers on the host.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
uv run python conf/simulator/multi_system_publishers.py @args
