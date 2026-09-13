<#
.SYNOPSIS
  Sync the repo to the edge EC2 host, install Docker, build edge images, and start HiveMQ Edge + agent.

.EXAMPLE
  .\deploy\aws\Install-UnsEdge.ps1
  .\deploy\aws\Install-UnsEdge.ps1 -SkipSync
#>
[CmdletBinding()]
param(
    [string]$ParamsPath,
    [switch]$SkipSync,
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "UnsAwsCommon.ps1")

$repoRoot = Get-UnsRepoRoot
$params = Import-UnsAwsParams -Path $ParamsPath

Write-Host "Edge host: $($params.EdgeHost)" -ForegroundColor Cyan
Write-Host "Cloud MQTT/management targets: $($params.MqttHost) / $($params.ManagementHost)" -ForegroundColor Cyan

if (-not $SkipSync) {
    Publish-UnsRepoTarball -Params $params -HostName $params.EdgeHost -RepoRoot $repoRoot -RemoteRepoRoot $params.RemoteRepoRoot
}

Invoke-UnsSsh -Params $params -HostName $params.EdgeHost -Sudo `
    -Command "UNS_DEPLOY_USER='$($params.SshUser)' bash $($params.RemoteRepoRoot)/deploy/aws/remote/install-docker.sh"

$caLocal = Join-Path $PSScriptRoot "work\cloud-ca.crt"
if (-not (Test-Path $caLocal)) {
    Write-Host "Local demo CA missing; downloading from the cloud host" -ForegroundColor DarkYellow
    Copy-UnsFileFromHost -Params $params -HostName $params.CloudHost `
        -RemotePath "$($params.RemoteRepoRoot)/deploy/cloud/secrets/tls/ca/ca.crt" `
        -LiteralPath $caLocal
}
Copy-UnsFileToHost -Params $params -HostName $params.EdgeHost -LiteralPath $caLocal -Destination "/tmp/uns-cloud-ca.crt"

if ($params.HivemqEdgeLicensePath -and (Test-Path $params.HivemqEdgeLicensePath)) {
    Copy-UnsFileToHost -Params $params -HostName $params.EdgeHost `
        -LiteralPath $params.HivemqEdgeLicensePath -Destination "/tmp/hivemq-edge.lic"
}

$envExports = Get-UnsEdgeEnvExports $params
Invoke-UnsSsh -Params $params -HostName $params.EdgeHost -Sudo -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/edge-bootstrap.sh"

if (-not $SkipBuild) {
    Write-Host "Building edge images on the EC2 host." -ForegroundColor Yellow
    Invoke-UnsSsh -Params $params -HostName $params.EdgeHost -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/edge-build-images.sh"
}

Invoke-UnsSsh -Params $params -HostName $params.EdgeHost -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/edge-start.sh"

Write-Host @"

Edge stack start issued.

Security group on this instance: inbound TCP 22 from your IP only. Outbound TCP 443 and 8883 to the cloud host. No inbound 8443/8883 from the internet.

Next:
  1. In the cloud console, register edge id $($params.EdgeId) and create a one-time enrollment token.
  2. Run .\deploy\aws\Enroll-UnsEdge.ps1 -Token '<token>'
  3. Apply the sample OPC UA/Modbus connections from deploy/edge/simulation/connections.json
"@
