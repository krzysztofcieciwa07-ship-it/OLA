[CmdletBinding()]
param(
    [switch]$Install,
    [string]$DestinationDirectory = (Join-Path $env:USERPROFILE "Downloads\OLA-tools\OmniRoute")
)

$ErrorActionPreference = "Stop"
$version = "3.8.53"
$fileName = "OmniRoute.Setup.$version.exe"
$url = "https://github.com/cheaper-inference/OmniRoute/releases/download/v$version/$fileName"
$expectedSha256 = "757bc68dff73e9680d18fe1d2d1a8ad3b78318de5948c8218bf02a46ea69ccfe"

New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
$destination = Join-Path $DestinationDirectory $fileName
$partial = "$destination.partial"

if (Test-Path -LiteralPath $destination) {
    $existing = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($existing -eq $expectedSha256) {
        Write-Host "Verified existing artifact: $destination"
    } else {
        throw "Existing file hash mismatch. It was not executed: $destination"
    }
} else {
    Write-Host "Downloading pinned OmniRoute $version release..."
    Invoke-WebRequest -Uri $url -OutFile $partial
    $actual = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expectedSha256) {
        Remove-Item -LiteralPath $partial -Force
        throw "SHA-256 mismatch. Download removed. Expected $expectedSha256; got $actual"
    }
    Move-Item -LiteralPath $partial -Destination $destination
    Write-Host "SHA-256 verified: $actual"
}

Write-Host "Artifact ready: $destination"
if ($Install) {
    $signature = Get-AuthenticodeSignature -FilePath $destination
    if ($signature.Status -ne "Valid" -or -not $signature.SignerCertificate) {
        throw "Authenticode signature is not valid ($($signature.Status)). Installer was NOT executed."
    }
    Write-Host "Authenticode signer: $($signature.SignerCertificate.Subject)"
    Write-Host "Signer thumbprint: $($signature.SignerCertificate.Thumbprint)"
    Write-Warning "The release tag is unsigned. Independently confirm this signer identity with the publisher before proceeding."
    $confirmation = Read-Host "Type INSTALL only after confirming the signer identity"
    if ($confirmation -cne "INSTALL") {
        throw "Operator did not confirm publisher identity. Installer was NOT executed."
    }
    Write-Warning "Starting the OmniRoute installer. Review the Windows/UAC prompt before approving."
    $process = Start-Process -FilePath $destination -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "OmniRoute installer returned exit code $($process.ExitCode)"
    }
    Write-Host "Installer exited successfully. This does not prove the gateway is configured or running."
} else {
    Write-Host "Not installed or launched. Re-run with -Install only after reviewing the verified file."
}
