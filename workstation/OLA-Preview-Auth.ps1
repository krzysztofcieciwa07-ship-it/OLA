# OLA DI-OS ZBook preview auth: read-only by default.
# -IssueKey creates a new tenant credential ONLY in the already configured preview.
[CmdletBinding()]
param([switch]$IssueKey,[switch]$CreatePreview,[switch]$SelfTest,[string]$ExpectedSha='', [string]$Model='', [string]$ExpectedBranch='ui/ola-command-center-live-20261014')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:Preview='ola-cc-preview'
$script:PreviewRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Get-Preview {
 $names=@(& docker.exe ps -a --format '{{.Names}}')
 if($LASTEXITCODE -ne 0){throw 'DOCKER_ENGINE_UNAVAILABLE'}
 if($names -notcontains $script:Preview){return $null}
 $raw=& docker.exe inspect --format '{{json .}}' $script:Preview
 if($LASTEXITCODE -ne 0 -or !$raw){throw 'PREVIEW_INSPECT_FAILED'}
 $c=$raw|ConvertFrom-Json
 if($c.Name -ne '/ola-cc-preview' -or $c.HostConfig.Privileged -or $c.HostConfig.NetworkMode -eq 'host'){throw 'BLOCKED_UNEXPECTED_CONTAINER'}
 $port=$c.HostConfig.PortBindings.'8000/tcp'
 if(!$port -or @($port).Count -ne 1 -or $port[0].HostIp -ne '127.0.0.1' -or $port[0].HostPort -ne '18081'){throw 'BLOCKED_UNSAFE_PORT'}
 $c
}
function Test-Pepper {
 $v=& docker.exe exec $script:Preview python -c "import os; p=os.environ.get('OLA_API_KEY_PEPPER',''); print('READY' if len(p.encode('utf-8')) >= 32 and not p.startswith('CI-ONLY-') else 'MISSING')" 2>$null
 ($LASTEXITCODE -eq 0 -and ([string]$v).Trim() -eq 'READY')
}

function New-PreviewSecretFile {
 $secretDir=Join-Path $env:LOCALAPPDATA 'OLA-Control\secrets'
 $secretPath=Join-Path $secretDir 'preview.env'
 if(Test-Path -LiteralPath $secretPath){throw 'PREVIEW_SECRET_FILE_ALREADY_EXISTS'}
 New-Item -ItemType Directory -Path $secretDir -Force|Out-Null
 $username=[Security.Principal.WindowsIdentity]::GetCurrent().Name
 $acl=Get-Acl -LiteralPath $secretDir
 $acl.SetAccessRuleProtection($true,$false)
 $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($username,'FullControl','ContainerInherit,ObjectInherit','None','Allow')))
 Set-Acl -LiteralPath $secretDir -AclObject $acl
 $bytes=New-Object byte[] 48
 $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
 try{$rng.GetBytes($bytes)}finally{$rng.Dispose()}
 $pepper=[Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
 [IO.File]::WriteAllText($secretPath,("OLA_API_KEY_PEPPER="+$pepper+[Environment]::NewLine),(New-Object Text.UTF8Encoding($false)))
 $aclFile=Get-Acl -LiteralPath $secretPath
 $aclFile.SetAccessRuleProtection($true,$false)
 $aclFile.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($username,'FullControl','Allow')))
 Set-Acl -LiteralPath $secretPath -AclObject $aclFile
 $secretPath
}
function Assert-PreviewSource([string]$Repo) {
 if($ExpectedSha -cnotmatch '^[a-f0-9]{40}$'){throw 'EXPECTED_SOURCE_SHA_REQUIRED'}
 if([string]::IsNullOrWhiteSpace($ExpectedBranch)){throw 'EXPECTED_GIT_BRANCH_REQUIRED'}
 if(!(Test-Path -LiteralPath (Join-Path $Repo '.git'))){throw 'CHECKOUT_REQUIRED'}
 $actual=& git.exe -C $Repo rev-parse HEAD
 if($LASTEXITCODE -ne 0 -or !$actual -or ([string]$actual).Trim() -cne $ExpectedSha){throw 'SOURCE_SHA_MISMATCH'}
 $branch=& git.exe -C $Repo branch --show-current
 if($LASTEXITCODE -ne 0 -or !$branch -or ([string]$branch).Trim() -cne $ExpectedBranch){throw 'UNEXPECTED_GIT_BRANCH'}
 $dirty=@(& git.exe -C $Repo status --porcelain)
 if($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0){throw 'DIRTY_CHECKOUT_BLOCKED'}
}
function Get-PreviewPython {
 # Resolve applications only: do not execute a caller-supplied command or shell expression.
 foreach($candidate in @(
  @{Name='py.exe';Arguments=@('-3')},
  @{Name='python.exe';Arguments=@()},
  @{Name='python3.exe';Arguments=@()}
 )) {
  $command=Get-Command -Name $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if(!$command -or !$command.Source){continue}
  $prefix=@($candidate.Arguments)
  $probe=& $command.Source @prefix -c "import sys; print('OLA_PREVIEW_PYTHON_OK' if sys.version_info >= (3,10) else 'UNSUPPORTED')" 2>$null
  if($LASTEXITCODE -eq 0 -and ([string]$probe).Trim() -eq 'OLA_PREVIEW_PYTHON_OK'){
   return [pscustomobject]@{Path=[string]$command.Source;Arguments=$prefix}
  }
 }
 throw 'LOCAL_PYTHON_310_OR_NEWER_REQUIRED'
}
function Assert-PreviewManifestPath([string]$Repo) {
 $path=Join-Path $Repo 'source-manifest.json'
 try{$item=Get-Item -LiteralPath $path -Force -ErrorAction Stop}
 catch [Management.Automation.ItemNotFoundException]{return}
 # The generator writes this ignored file: never follow an existing reparse
 # point to another location. Other read/access errors intentionally block.
 if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $item.PSIsContainer){
  throw 'BUILD_INVENTORY_UNSAFE_PATH'
 }
}
function Get-PreviewManifestHash([string]$Repo) {
 Assert-PreviewManifestPath $Repo
 $path=Join-Path $Repo 'source-manifest.json'
 if(!(Test-Path -LiteralPath $path -PathType Leaf)){throw 'BUILD_INVENTORY_MISSING'}
 try{$manifest=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json}
 catch{throw 'BUILD_INVENTORY_INVALID_JSON'}
 if(!$manifest -or !($manifest.PSObject.Properties.Name -contains 'schema') -or
    !($manifest.PSObject.Properties.Name -contains 'source_sha') -or
    !($manifest.PSObject.Properties.Name -contains 'files') -or
    $manifest.schema -cne 'ola-local-build-v1' -or $manifest.source_sha -cne $ExpectedSha -or
    $manifest.files -isnot [pscustomobject] -or @($manifest.files.PSObject.Properties).Count -eq 0){
  throw 'BUILD_INVENTORY_SOURCE_OR_SCHEMA_MISMATCH'
 }
 (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
}
function Assert-PreviewVolumeAbsent([string]$Volume) {
 $volumes=@(& docker.exe volume ls --format '{{.Name}}')
 if($LASTEXITCODE -ne 0){throw 'DOCKER_VOLUME_LIST_FAILED'}
 if($volumes -contains $Volume){throw 'PREVIEW_VOLUME_EXISTS: manual review required'}
}
function Test-CloudModelName([string]$Name) {
 # Ollama cloud tags include both :cloud and sized tags such as :120b-cloud.
 return ($Name -match '(?i)(?:^|[:-])cloud$')
}
function Assert-NoRemoteModelMetadata($Metadata) {
 if($null -eq $Metadata -or $Metadata -isnot [pscustomobject] -or
    @($Metadata.PSObject.Properties).Count -eq 0){throw 'OLLAMA_MODEL_METADATA_INVALID'}
 foreach($field in @('remote_host','remote_model')){
  if($Metadata.PSObject.Properties.Name -contains $field){
   $value=$Metadata.$field
   if($value -isnot [string]){throw 'OLLAMA_MODEL_METADATA_INVALID'}
   if($value.Length -gt 0){throw 'OLLAMA_CLOUD_MODEL_BLOCKED'}
  }
 }
}
function Assert-LocalOllamaModel($Tag,[string]$Name) {
 if(Test-CloudModelName $Name){throw 'OLLAMA_CLOUD_MODEL_BLOCKED'}
 Assert-NoRemoteModelMetadata $Tag
 # /api/show only reads metadata; it neither pulls nor loads the model.
 # See Ollama docs/api.md (Show Model Information) and api/types.go ShowResponse.
 try{
  $body=@{model=$Name}|ConvertTo-Json -Compress
  $metadata=Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/show' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 5
 }catch{throw 'OLLAMA_MODEL_DETAILS_UNAVAILABLE'}
 Assert-NoRemoteModelMetadata $metadata
 if($metadata.PSObject.Properties.Name -notcontains 'details' -or
    $metadata.PSObject.Properties.Name -notcontains 'model_info' -or
    $metadata.details -isnot [pscustomobject] -or
    @($metadata.details.PSObject.Properties).Count -eq 0 -or
    $metadata.model_info -isnot [pscustomobject] -or
    @($metadata.model_info.PSObject.Properties).Count -eq 0){throw 'OLLAMA_MODEL_METADATA_INVALID'}
 foreach($field in @('format','family')){
  if($metadata.details.PSObject.Properties.Name -notcontains $field -or
     $metadata.details.$field -isnot [string] -or
     [string]::IsNullOrWhiteSpace($metadata.details.$field)){throw 'OLLAMA_MODEL_METADATA_INVALID'}
 }
}
function Create-Preview {
 if(Get-Preview){throw 'PREVIEW_EXISTS: no existing data will be modified or replaced'}
 $repo=$script:PreviewRoot
 Assert-PreviewSource $repo
 if(!(Test-Path -LiteralPath (Join-Path $repo 'scripts\provision_local_operator.py'))){throw 'PROVISION_MODULE_MISSING'}
 $generator=Join-Path $repo 'scripts\build_source_manifest.py'
 if(!(Test-Path -LiteralPath $generator -PathType Leaf)){throw 'BUILD_INVENTORY_GENERATOR_MISSING'}
 try{$tags=Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5}
 catch{throw 'OLLAMA_NOT_AVAILABLE: start host Ollama first'}
 if($null -eq $tags -or $tags -isnot [pscustomobject] -or
    @($tags.PSObject.Properties).Count -eq 0 -or
    $tags.PSObject.Properties.Name -notcontains 'models' -or
    $tags.models -isnot [array]){throw 'OLLAMA_MODEL_METADATA_INVALID'}
 foreach($tag in $tags.models){
  if($null -eq $tag -or $tag -isnot [pscustomobject] -or
     @($tag.PSObject.Properties).Count -eq 0 -or
     $tag.PSObject.Properties.Name -notcontains 'name' -or
     $tag.name -isnot [string] -or [string]::IsNullOrWhiteSpace($tag.name)){throw 'OLLAMA_MODEL_METADATA_INVALID'}
 }
 $available=@($tags.models|ForEach-Object{$_.name})
 if(!$Model){
  $localModels=@($available|Where-Object{!(Test-CloudModelName $_)})
  if($localModels.Count -eq 0){throw 'NO_LOCAL_OLLAMA_MODEL'}
  $Model=[string]$localModels[0]
 }
 if($Model -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.\/-]{0,95}(:[a-zA-Z0-9_.-]{1,32})?$'){throw 'INVALID_OLLAMA_MODEL_NAME'}
 if($Model -notin $available){throw 'OLLAMA_MODEL_NOT_PRESENT'}
 $selectedTags=@($tags.models|Where-Object{$_.name -ceq $Model})
 if($selectedTags.Count -ne 1){throw 'OLLAMA_MODEL_METADATA_INVALID'}
 Assert-LocalOllamaModel $selectedTags[0] $Model
 $volume='ola-cc-preview-data'
 Assert-PreviewVolumeAbsent $volume
 Assert-PreviewManifestPath $repo
 $python=Get-PreviewPython
 $pythonArgs=@($python.Arguments)+@($generator)
 & $python.Path @pythonArgs | Out-Host
 if($LASTEXITCODE -ne 0){throw 'BUILD_INVENTORY_GENERATION_FAILED'}
 Assert-PreviewSource $repo
 $inventoryHash=Get-PreviewManifestHash $repo
 $image='ola-cc-preview:'+($ExpectedSha.Substring(0,12))
 & docker.exe build -t $image $repo
 if($LASTEXITCODE -ne 0){throw 'BUILD_FAILED: no container created'}
 # Recheck the checkout and inventory after generation/build. This is local
 # consistency, not attestation or protection against a privileged restore race.
 Assert-PreviewSource $repo
 if((Get-PreviewManifestHash $repo) -ne $inventoryHash){throw 'BUILD_INVENTORY_CHANGED_DURING_BUILD'}
 if(Get-Preview){throw 'PREVIEW_EXISTS: no existing data will be modified or replaced'}
 Assert-PreviewVolumeAbsent $volume
 $secretFile=New-PreviewSecretFile
 & docker.exe volume create $volume | Out-Null
 if($LASTEXITCODE -ne 0){throw 'VOLUME_CREATE_FAILED'}
 $arguments=@(
  'run','-d','--name',$script:Preview,'--restart','no',
  '--memory','2g','--env-file',$secretFile,
  '--env',('OLA_RUNTIME_COMMIT='+$ExpectedSha),
  '--env','OLA_LLM_PROVIDER=ollama','--env','OLA_CHAT_PROVIDER=ollama',
  '--env',('OLA_LLM_MODEL='+$Model),'--env',('OLA_CHAT_MODEL='+$Model),
  '--env','OLA_LLM_MODE=required',
  '--env','OLLAMA_BASE_URL=http://host.docker.internal:11434',
  '--add-host','host.docker.internal:host-gateway',
  '--mount',('type=volume,source='+$volume+',target=/data'),
  '--publish','127.0.0.1:18081:8000',
  '--label',('ola.source_sha='+$ExpectedSha),$image
 )
 & docker.exe @arguments | Out-Null
 if($LASTEXITCODE -ne 0){throw 'PREVIEW_START_FAILED: volume and secret preserved for manual diagnosis'}
 $ready=$false
 for($i=0;$i -lt 20;$i++){
  Start-Sleep -Seconds 2
  try{
   $response=Invoke-RestMethod 'http://127.0.0.1:18081/health' -TimeoutSec 5
   if($response.status -eq 'ok'){$ready=$true;break}
  }catch{}
 }
 if(!$ready){throw 'PREVIEW_HEALTH_FAILED: previous OLA services unchanged'}
 Write-Host 'OLA PREVIEW CREATED / HEALTH PASS / PERSISTENT SQLITE / SOURCE PINNED' -ForegroundColor Green
 Write-Host 'Random pepper stored in restricted LocalAppData; it was not printed.'
 Write-Host 'Run -IssueKey separately to create the first tenant credential.'
}

if($SelfTest){
 if($script:Preview -ne 'ola-cc-preview'){throw 'PREVIEW_NAME_CHANGED'}
 Write-Host 'OLA_PREVIEW_AUTH_SELFTEST=PASS';exit 0
}
if($IssueKey -and $CreatePreview){throw 'USE_ONLY_ONE_WRITE_MODE'}
if($CreatePreview -and !(Get-Command git.exe -ErrorAction SilentlyContinue)){throw 'GIT_CLI_MISSING'}
if(!(Get-Command docker.exe -ErrorAction SilentlyContinue)){throw 'DOCKER_CLI_MISSING'}
if($CreatePreview){Create-Preview;exit 0}
$state=Get-Preview
if(!$state){Write-Host 'PREVIEW_NOT_FOUND: create a new credential-enabled preview after verifying source SHA.';exit 2}
if($state.State.Status -ne 'running'){Write-Host ("PREVIEW_NOT_RUNNING: "+$state.State.Status);exit 3}
if(!(Test-Pepper)){
 Write-Host 'AUTH_NOT_CONFIGURED: preview has no OLA_API_KEY_PEPPER.' -ForegroundColor Yellow
 Write-Host 'BLOCKED: no key created, no container restart, no data changed.'
 Write-Host 'A reviewed backup + preview recreation is required before issuing credentials.'
 exit 4
}
$module=& docker.exe exec $script:Preview python -c "import scripts.provision_local_operator; print('READY')" 2>$null
if($LASTEXITCODE -ne 0 -or ([string]$module).Trim() -ne 'READY'){
 Write-Host 'AUTH_MODULE_NOT_DEPLOYED: update preview image after source verification.'
 exit 5
}
if(!$IssueKey){
 Write-Host 'PREVIEW_AUTH_READY. Run this script with -IssueKey to create the operator API key.' -ForegroundColor Green
 exit 0
}
Write-Host 'Creating a NEW tenant API key for OLA Core, not a Windows Local Executor token.' -ForegroundColor Cyan
& docker.exe exec $script:Preview python -m scripts.provision_local_operator
if($LASTEXITCODE -ne 0){throw 'KEY_ISSUANCE_FAILED_OR_DUPLICATE_TENANT'}
Write-Host 'Copy X_API_KEY_ONCE into Command Center > SETTINGS > X-API-Key > Verify.' -ForegroundColor Green
Write-Host 'Do not send the key to ChatGPT or store it in your Git repository.'
