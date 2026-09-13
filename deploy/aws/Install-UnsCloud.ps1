<#
.SYNOPSIS
  Sync the repo to the cloud EC2 host, install Docker, build images, and start the cloud bundle.

.EXAMPLE
  Copy-Item deploy\aws\uns-aws.params.example.ps1 deploy\aws\uns-aws.params.ps1
  # edit host names, SSH key, HiveMQ images
  .\deploy\aws\Install-UnsCloud.ps1
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

Write-Host "Cloud host: $($params.CloudHost)" -ForegroundColor Cyan
Write-Host "Console:    https://$($params.ConsoleHost)" -ForegroundColor Cyan

if (-not $SkipSync) {
    Publish-UnsRepoTarball -Params $params -HostName $params.CloudHost -RepoRoot $repoRoot -RemoteRepoRoot $params.RemoteRepoRoot
}

Invoke-UnsSsh -Params $params -HostName $params.CloudHost -Sudo `
    -Command "UNS_DEPLOY_USER='$($params.SshUser)' bash $($params.RemoteRepoRoot)/deploy/aws/remote/install-docker.sh"

$licenseRemote = ""
if ($params.HivemqBrokerLicensePath -and (Test-Path $params.HivemqBrokerLicensePath)) {
    $licenseRemote = "/tmp/hivemq-broker.lic"
    Copy-UnsFileToHost -Params $params -HostName $params.CloudHost `
        -LiteralPath $params.HivemqBrokerLicensePath -Destination $licenseRemote
}

$envExports = Get-UnsCloudEnvExports $params
if ($licenseRemote) {
    $envExports += "`nexport UNS_HIVEMQ_LICENSE_FILE='$licenseRemote'"
}

Invoke-UnsSsh -Params $params -HostName $params.CloudHost -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/cloud-bootstrap.sh"

if (-not $SkipBuild) {
    Write-Host "Building cloud images on the EC2 host. This often takes 20-40 minutes." -ForegroundColor Yellow
    Invoke-UnsSsh -Params $params -HostName $params.CloudHost -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/cloud-build-images.sh"
}

Invoke-UnsSsh -Params $params -HostName $params.CloudHost -Command "$envExports; bash $($params.RemoteRepoRoot)/deploy/aws/remote/cloud-start.sh"

$workCa = Join-Path $PSScriptRoot "work\cloud-ca.crt"
try {
    Copy-UnsFileFromHost -Params $params -HostName $params.CloudHost `
        -RemotePath "$($params.RemoteRepoRoot)/deploy/cloud/secrets/tls/ca/ca.crt" `
        -LiteralPath $workCa
    Write-Host "Saved demo CA to $workCa (install in the browser if TlsMode=demo)" -ForegroundColor Cyan
}
catch {
    Write-Host "Could not download demo CA (expected for letsencrypt/existing): $_" -ForegroundColor DarkYellow
}

Write-Host @"

Cloud stack start issued.

Next:
  1. Open https://$($params.ConsoleHost) and sign in (Keycloak admin password is on the host in deploy/cloud/secrets/runtime.env).
  2. Fill AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in that runtime.env if the lake mapper should write to S3, then rerun this script with -SkipSync -SkipBuild.
  3. Register one edge in the console and issue an enrollment token.
  4. Run .\deploy\aws\Install-UnsEdge.ps1 then .\deploy\aws\Enroll-UnsEdge.ps1 -Token <token>

Security group on this instance: inbound TCP 22 (your IP), 80, 443, 8883. Deny 5432/9092/7474/7687/8000/8080/3000.
"@
