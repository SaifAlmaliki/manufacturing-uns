# Shared helpers for the AWS operator scripts. Dotted-source from Install-*.ps1.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-UnsRepoRoot {
    param([string]$StartDir = $PSScriptRoot)
    $current = (Resolve-Path $StartDir).Path
    while ($current) {
        if ((Test-Path (Join-Path $current "deploy\cloud\compose.yml")) -and
            (Test-Path (Join-Path $current "deploy\edge\compose.yml"))) {
            return $current
        }
        $parent = Split-Path $current -Parent
        if ($parent -eq $current) { break }
        $current = $parent
    }
    throw "Could not locate the manufacturing-uns repository root from $StartDir"
}

function Import-UnsAwsParams {
    param([string]$Path)
    if (-not $Path) {
        $Path = Join-Path $PSScriptRoot "uns-aws.params.ps1"
    }
    if (-not (Test-Path $Path)) {
        $example = Join-Path $PSScriptRoot "uns-aws.params.example.ps1"
        throw @"
Missing $Path
Copy the example and fill in host names and HiveMQ images:
  Copy-Item '$example' '$Path'
"@
    }
    . $Path
    if (-not $UnsAws) { throw "uns-aws.params.ps1 must define `$UnsAws" }
    foreach ($required in @(
            "SshUser", "SshKeyPath", "CloudHost", "EdgeHost",
            "ConsoleHost", "EnrollHost", "ManagementHost", "MqttHost",
            "HivemqBrokerImage", "HivemqEdgeImage"
        )) {
        if ([string]::IsNullOrWhiteSpace([string]$UnsAws[$required])) {
            throw "uns-aws.params.ps1 is missing $required"
        }
    }
    if (-not (Test-Path $UnsAws.SshKeyPath)) {
        throw "SSH private key not found: $($UnsAws.SshKeyPath)"
    }
    return $UnsAws
}

function Get-UnsSshArgs {
    param($Params)
    @(
        "-i", $Params.SshKeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=12"
    )
}

function Invoke-UnsSsh {
    param(
        $Params,
        [string]$HostName,
        [Parameter(Mandatory = $true)][string]$Command,
        [switch]$Sudo
    )
    $target = "$($Params.SshUser)@$HostName"
    $remote = $Command
    if ($Sudo) {
        $remote = "sudo bash -lc $(ConvertTo-UnsSshQuote $Command)"
    }
    $sshArgs = (Get-UnsSshArgs $Params) + @($target, $remote)
    Write-Host "ssh $target $Command" -ForegroundColor DarkGray
    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw "ssh failed ($LASTEXITCODE): $Command"
    }
}

function ConvertTo-UnsSshQuote {
    param([string]$Value)
    "'" + ($Value -replace "'", "'\''") + "'"
}

function Copy-UnsFileToHost {
    param(
        $Params,
        [string]$HostName,
        [string]$LiteralPath,
        [string]$Destination
    )
    $target = "$($Params.SshUser)@${HostName}:$Destination"
    $scpArgs = (Get-UnsSshArgs $Params) + @("--", $LiteralPath, $target)
    Write-Host "scp $LiteralPath -> $target" -ForegroundColor DarkGray
    & scp @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "scp failed ($LASTEXITCODE): $LiteralPath"
    }
}

function Copy-UnsFileFromHost {
    param(
        $Params,
        [string]$HostName,
        [string]$RemotePath,
        [string]$LiteralPath
    )
    $source = "$($Params.SshUser)@${HostName}:$RemotePath"
    $dir = Split-Path $LiteralPath -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    $scpArgs = (Get-UnsSshArgs $Params) + @("--", $source, $LiteralPath)
    Write-Host "scp $source -> $LiteralPath" -ForegroundColor DarkGray
    & scp @scpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "scp download failed ($LASTEXITCODE): $RemotePath"
    }
}

function Publish-UnsRepoTarball {
    param(
        $Params,
        [string]$HostName,
        [string]$RepoRoot,
        [string]$RemoteRepoRoot
    )
    $work = Join-Path $PSScriptRoot "work"
    if (-not (Test-Path $work)) {
        New-Item -ItemType Directory -Path $work | Out-Null
    }
    $archive = Join-Path $work "uns-repo.tgz"
    Write-Host "Creating repository archive $archive" -ForegroundColor Cyan
    if (Test-Path $archive) { Remove-Item $archive -Force }
    Push-Location $RepoRoot
    try {
        & tar.exe -czf $archive `
            --exclude=.git `
            --exclude=node_modules `
            --exclude=.venv `
            --exclude=graphify-out `
            --exclude=__pycache__ `
            --exclude=deploy/aws/work `
            --exclude=deploy/aws/uns-aws.params.ps1 `
            .
        if ($LASTEXITCODE -ne 0) { throw "tar.exe failed with $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }

    Copy-UnsFileToHost -Params $Params -HostName $HostName -LiteralPath $archive -Destination "/tmp/uns-repo.tgz"
    $extract = @"
set -euo pipefail
sudo mkdir -p '$RemoteRepoRoot'
sudo tar -xzf /tmp/uns-repo.tgz -C '$RemoteRepoRoot'
sudo chown -R $($Params.SshUser):$($Params.SshUser) '$RemoteRepoRoot'
rm -f /tmp/uns-repo.tgz
"@
    Invoke-UnsSsh -Params $Params -HostName $HostName -Command $extract
}

function Get-UnsCloudEnvExports {
    param($Params)
    $tls = [string]$Params.TlsMode
    if (-not $tls) { $tls = "demo" }
    $publications = [string]$Params.PublicationsHost
    if (-not $publications) { $publications = "publications.$($Params.ConsoleHost)" }
    $email = [string]$Params.LetsEncryptEmail
    @"
export UNS_REPO_ROOT='$($Params.RemoteRepoRoot)'
export UNS_CLOUD_BUNDLE='$($Params.RemoteRepoRoot)/deploy/cloud'
export UNS_CONSOLE_HOST='$($Params.ConsoleHost)'
export UNS_ENROLL_HOST='$($Params.EnrollHost)'
export UNS_MGMT_HOST='$($Params.ManagementHost)'
export UNS_MQTT_HOST='$($Params.MqttHost)'
export UNS_PUBLICATIONS_HOST='$publications'
export UNS_AWS_REGION='$($Params.AwsRegion)'
export UNS_S3_LAKE_BUCKET='$($Params.S3LakeBucket)'
export UNS_TLS_MODE='$tls'
export UNS_LETSENCRYPT_EMAIL='$email'
export UNS_HIVEMQ_BROKER_IMAGE='$($Params.HivemqBrokerImage)'
export UNS_IMAGE_TAG='aws-demo'
"@
}

function Get-UnsEdgeEnvExports {
    param($Params)
    $sim = "0"
    if ($Params.EnableEdgeSim) { $sim = "1" }
    @"
export UNS_REPO_ROOT='$($Params.RemoteRepoRoot)'
export UNS_EDGE_DESTINATION='$($Params.EdgeDestination)'
export UNS_CONSOLE_HOST='$($Params.ConsoleHost)'
export UNS_ENROLL_HOST='$($Params.EnrollHost)'
export UNS_MGMT_HOST='$($Params.ManagementHost)'
export UNS_MQTT_HOST='$($Params.MqttHost)'
export UNS_EDGE_ID='$($Params.EdgeId)'
export UNS_HIVEMQ_EDGE_IMAGE='$($Params.HivemqEdgeImage)'
export UNS_EDGE_ENABLE_SIM='$sim'
export UNS_IMAGE_TAG='aws-demo'
export UNS_CLOUD_CA_FILE='/tmp/uns-cloud-ca.crt'
"@
}
