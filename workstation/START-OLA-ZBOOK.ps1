# OLA DI-OS — one entry point for existing AURORA / OLA Core / Ollama.
# Default is read-only. -Setup MAY create a NEW preview + NEW tenant credential,
# but never deletes/replaces an existing container, volume, database or pepper.
[CmdletBinding()]
param(
  [switch]$Setup,
  [switch]$LiveTest,
  [switch]$NoBrowser,
  [switch]$SelfTest,
  [string]$Model = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Name = 'ola-cc-preview'
$script:Port = 18081
$script:Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:Auth = Join-Path $PSScriptRoot 'OLA-Preview-Auth.ps1'
$script:ExpectedPaths = @('/health','/auth/session','/chat','/nina-run','/control/overview','/evidence/{record_id}')

function Assert-Preflight {
  if($env:OS -ne 'Windows_NT'){ throw 'WINDOWS_REQUIRED' }
  foreach($bin in @('git.exe','docker.exe')){
    if(!(Get-Command $bin -ErrorAction SilentlyContinue)){ throw ('MISSING_COMMAND: '+$bin) }
  }
  if(!(Test-Path -LiteralPath $script:Auth -PathType Leaf)){throw 'PREVIEW_AUTH_HELPER_MISSING'}
  if(!(Test-Path -LiteralPath (Join-Path $script:Repo '.git'))){throw 'OLA_GIT_CHECKOUT_REQUIRED'}
  & docker.exe info --format '{{.ServerVersion}}' | Out-Null
  if($LASTEXITCODE -ne 0){throw 'DOCKER_DESKTOP_NOT_RUNNING'}
}
function Get-SourceSha {
  $value = (& git.exe -C $script:Repo rev-parse HEAD)
  if($LASTEXITCODE -ne 0 -or !$value){throw 'GIT_SOURCE_UNAVAILABLE'}
  $value = ([string]$value).Trim()
  if($value -notmatch '^[0-9a-f]{40}$'){throw 'INVALID_SOURCE_SHA'}
  $value
}
function Get-Preview {
  $names = @(& docker.exe ps -a --format '{{.Names}}')
  if($LASTEXITCODE -ne 0){throw 'DOCKER_CONTAINER_LIST_FAILED'}
  if($names -notcontains $script:Name){return $null}
  $raw = & docker.exe inspect --format '{{json .}}' $script:Name
  if($LASTEXITCODE -ne 0 -or !$raw){throw 'DOCKER_INSPECT_FAILED'}
  $c = ([string]$raw) | ConvertFrom-Json
  if($c.Name -ne '/ola-cc-preview' -or $c.HostConfig.Privileged -or $c.HostConfig.NetworkMode -eq 'host'){
    throw 'BLOCKED_UNEXPECTED_EXISTING_CONTAINER'
  }
  $binding = @($c.HostConfig.PortBindings.'8000/tcp')
  if($binding.Count -ne 1 -or $binding[0].HostIp -ne '127.0.0.1' -or $binding[0].HostPort -ne "$script:Port"){
    throw 'BLOCKED_UNSAFE_LOCAL_PORT'
  }
  return $c
}
function Assert-RunningPreview([object]$container,[string]$expectedSha) {
  if($null -eq $container){throw 'PREVIEW_NOT_FOUND'}
  $pinned = [string]$container.Config.Labels.'ola.source_sha'
  if($pinned -ne $expectedSha){
    throw 'BLOCKED_SOURCE_MISMATCH: existing container is not built from this checkout; DO NOT replace it automatically'
  }
  if($container.State.Status -ne 'running'){throw 'BLOCKED_PREVIEW_NOT_RUNNING: inspect before any restart'}
}
function Test-RealHttpSurface {
  $base = 'http://127.0.0.1:'+$script:Port
  $health = Invoke-RestMethod -Uri ($base+'/health') -TimeoutSec 8
  if($health.status -ne 'ok'){throw 'API_HEALTH_FAILED'}
  $spec = Invoke-RestMethod -Uri ($base+'/openapi.json') -TimeoutSec 8
  if(!$spec.paths){throw 'OPENAPI_MISSING'}
  $paths = @($spec.paths.PSObject.Properties.Name)
  foreach($path in $script:ExpectedPaths){
    if($paths -notcontains $path){throw ('OLA_API_ROUTE_MISSING: '+$path)}
  }
  $home = Invoke-WebRequest -Uri ($base+'/') -UseBasicParsing -TimeoutSec 8
  if($home.StatusCode -ne 200 -or $home.Content -notmatch 'OLA di OS' -or $home.Content -notmatch 'UI / API BRIDGE'){
    throw 'AURORA_SERVED_PAGE_MISMATCH: static demo or another application'
  }
  Write-Host 'API_HEALTH=PASS; OLA_ROUTES=PRESENT; AURORA_PAGE=SERVED_BY_CORE' -ForegroundColor Green
}
if($SelfTest){
  if($script:Name -ne 'ola-cc-preview' -or $script:Port -ne 18081 -or $script:ExpectedPaths.Count -lt 6){
    throw 'STARTER_CONTRACT_FAILED'
  }
  Write-Host 'OLA_ZBOOK_STARTER_SELFTEST=PASS'
  return
}
Assert-Preflight
$sha = Get-SourceSha
$preview = Get-Preview
if($null -eq $preview){
  if(!$Setup){throw 'NO_PREVIEW: run START-OLA-ZBOOK.ps1 -Setup to create a new isolated local preview'}
  Write-Host 'CREATING NEW, ISOLATED STAGING PREVIEW — existing services untouched' -ForegroundColor Cyan
  $options = @{CreatePreview=$true; ExpectedSha=$sha}
  if($Model){$options.Model=$Model}
  & $script:Auth @options
  if(!$?){throw 'PREVIEW_CREATION_BLOCKED'}
  $preview = Get-Preview
  Assert-RunningPreview $preview $sha
  # First local operator credential is issued once, on the workstation terminal.
  Write-Host 'NEW PREVIEW: issuing the first tenant credential once; keep it private.' -ForegroundColor Yellow
  & $script:Auth -IssueKey
  if(!$?){throw 'LOCAL_OPERATOR_PROVISIONING_FAILED'}
}else{
  Assert-RunningPreview $preview $sha
  & $script:Auth
  if(!$?){throw 'PREVIEW_AUTH_CONFIGURATION_INVALID'}
}
Test-RealHttpSurface
if($LiveTest){
  Write-Host 'Live test requests the LOCAL operator key inside the container terminal.' -ForegroundColor Cyan
  Write-Host 'A successful result requires a real Ollama answer and tenant evidence readback.'
  & docker.exe exec -it $script:Name python scripts/verify_aurora_connection.py --base-url 'http://127.0.0.1:8000'
  if($LASTEXITCODE -ne 0){throw 'LIVE_OLLAMA_EVIDENCE_TEST_BLOCKED'}
}else{
  Write-Host 'LLM / EVIDENCE NOT TESTED. Add -LiveTest for the real model and stored-evidence check.' -ForegroundColor Yellow
}
Write-Host ('AURORA STAGING: http://127.0.0.1:'+$script:Port+'/') -ForegroundColor Cyan
Write-Host 'Production status: NO-GO, signing and independent release proof required.'
if(!$NoBrowser){Start-Process ('http://127.0.0.1:'+$script:Port+'/')}
