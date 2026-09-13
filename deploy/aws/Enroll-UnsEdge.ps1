<#
.SYNOPSIS
  Run uns_edge_enroll on the edge VM with a one-time console token.

.EXAMPLE
  .\deploy\aws\Enroll-UnsEdge.ps1 -Token 'paste-from-console'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$ParamsPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "UnsAwsCommon.ps1")
$params = Import-UnsAwsParams -Path $ParamsPath

$dest = $params.EdgeDestination
$enrollUrl = "https://$($params.EnrollHost)"
$quotedToken = ConvertTo-UnsSshQuote $Token
$command = @"
set -euo pipefail
cd '$dest'
docker compose --project-directory '$dest' -f compose.yml -f compose.images.yml exec -T uns-edge-agent \
  uv run --package uns_edge_agent uns_edge_enroll --token $quotedToken --cloud-url '$enrollUrl'
docker compose --project-directory '$dest' -f compose.yml -f compose.images.yml restart uns-edge-agent
"@

Invoke-UnsSsh -Params $params -HostName $params.EdgeHost -Command $command

$envExports = Get-UnsEdgeEnvExports $params
Invoke-UnsSsh -Params $params -HostName $params.EdgeHost `
    -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/edge-install-bridge-certs.sh"

Write-Host "Enrollment command completed. Confirm heartbeat for $($params.EdgeId) in the cloud console." -ForegroundColor Cyan
