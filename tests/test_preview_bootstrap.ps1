# PowerShell control-flow harness. No Docker, model, credential or product runs.
# Run with Windows PowerShell 5.1+ or pwsh; this is NOT Windows product E2E.
param([string]$CaseFilter='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

$repoRoot=Split-Path -Parent $PSScriptRoot
$target=Join-Path $repoRoot 'workstation/OLA-Preview-Auth.ps1'
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($target,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw ('PREVIEW_PARSE_FAILED: '+($parseErrors -join '; '))}
$definitions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false))
foreach($definition in $definitions){. ([scriptblock]::Create($definition.Extent.Text))}
$branchParameter=@($ast.ParamBlock.Parameters|Where-Object{$_.Name.VariablePath.UserPath -eq 'ExpectedBranch'})
if($branchParameter.Count -ne 1 -or $branchParameter[0].DefaultValue.Value -ne 'ui/ola-command-center-live-20261014'){
 throw 'DEFAULT_BRANCH_GUARD_CHANGED'
}

$script:Cases=0
$script:FixtureRoot=Join-Path ([IO.Path]::GetTempPath()) ('ola-preview-harness-'+[guid]::NewGuid().ToString('N'))
$script:PreviewRoot=$script:FixtureRoot
$script:Preview='ola-cc-preview'
$script:TestSha='a'*40
$script:OtherSha='b'*40
$script:DefaultBranch='ui/ola-command-center-live-20261014'

function Assert-That([bool]$Condition,[string]$Message){if(!$Condition){throw ('ASSERTION_FAILED: '+$Message)}}
function Event([string]$Name){$script:Events.Add($Name)}
function Write-FixtureManifest([string]$Sha,[string]$Schema='ola-local-build-v1',[string]$FileHash=('0'*64)){
 $manifest=@{schema=$Schema;source_sha=$Sha;files=@{'app/main.py'=$FileHash}}
 [IO.File]::WriteAllText((Join-Path $script:FixtureRoot 'source-manifest.json'),($manifest|ConvertTo-Json -Depth 5))
}
function Reset-Fixture {
 if(Test-Path -LiteralPath $script:FixtureRoot){Remove-Item -LiteralPath $script:FixtureRoot -Recurse -Force}
 New-Item -ItemType Directory -Path (Join-Path $script:FixtureRoot '.git') -Force|Out-Null
 New-Item -ItemType Directory -Path (Join-Path $script:FixtureRoot 'scripts') -Force|Out-Null
 foreach($name in @('provision_local_operator.py','build_source_manifest.py')){
  [IO.File]::WriteAllText((Join-Path $script:FixtureRoot ('scripts/'+$name)),'# inert fixture')
 }
 $script:Fixture=@{
  Sha=$script:TestSha;Branch=$script:DefaultBranch;Dirty=$false;
  Generator='ok';Build='ok';PreviewExists=$false;VolumeExists=$false;
  PythonPresent=$true;Built=$false;PreviewDuringBuild=$false;VolumeDuringBuild=$false;ReparseManifest=$false;
  Models=@([pscustomobject]@{name='local:test'});TagsResponseOverride=$false;TagsResponse=$null;
  ShowFailure=$false;ShowCalls=0;ShowModelSeen='';
  ShowResponse=[pscustomobject]@{
   details=[pscustomobject]@{format='gguf';family='llama'};
   model_info=[pscustomobject]@{'general.architecture'='llama'}
  }
 }
 $script:Events=New-Object 'Collections.Generic.List[string]'
 $script:ExpectedSha=$script:TestSha
 $script:ExpectedBranch=$script:DefaultBranch
 $script:Model='local:test'
 $global:LASTEXITCODE=0
}

# Replace all external commands and credential creation. The source functions
# above execute for real, but their effects stay inside this inert fixture.
function Get-Preview {
 if($script:Fixture.PreviewExists -or ($script:Fixture.Built -and $script:Fixture.PreviewDuringBuild)){
  return [pscustomobject]@{Name='/ola-cc-preview'}
 }
 return $null
}
function New-PreviewSecretFile {Event 'secret';return (Join-Path $script:FixtureRoot 'NO-ACTUAL-SECRET.env')}
function Get-Item {
 [CmdletBinding()]
 param([string]$LiteralPath,[switch]$Force)
 if($script:Fixture.ReparseManifest -and $LiteralPath -eq (Join-Path $script:FixtureRoot 'source-manifest.json')){
  return [pscustomobject]@{Attributes=[IO.FileAttributes]::ReparsePoint;PSIsContainer=$false}
 }
 Microsoft.PowerShell.Management\Get-Item @PSBoundParameters
}
function Get-Command {
 param([string]$Name,[object]$CommandType,[string]$ErrorAction)
 if($script:Fixture.PythonPresent -and $Name -eq 'py.exe'){
  return [pscustomobject]@{Source='Invoke-MockedPython';CommandType='Application'}
 }
 return $null
}
function Invoke-MockedPython {
 $arguments=@($args);$global:LASTEXITCODE=0
 if($arguments -contains '-c'){return 'OLA_PREVIEW_PYTHON_OK'}
 Assert-That ($arguments[-1] -like '*build_source_manifest.py') 'only the existing generator may be invoked'
 Event 'generate'
 switch($script:Fixture.Generator){
  'failed' {$global:LASTEXITCODE=9;return}
  'wrong-sha' {Write-FixtureManifest $script:OtherSha;return}
  'wrong-schema' {Write-FixtureManifest $script:TestSha 'unsupported';return}
  'change-source' {$script:Fixture.Sha=$script:OtherSha}
  'change-branch' {$script:Fixture.Branch='unexpected/branch'}
  'reparse-manifest' {$script:Fixture.ReparseManifest=$true}
 }
 Write-FixtureManifest $script:TestSha
}
function git.exe {
 $arguments=@($args);$global:LASTEXITCODE=0
 Assert-That ($arguments[0] -eq '-C' -and $arguments[1] -eq $script:FixtureRoot) 'Git must read the selected checkout'
 switch($arguments[2]){
  'rev-parse' {return $script:Fixture.Sha}
  'branch' {return $script:Fixture.Branch}
  'status' {if($script:Fixture.Dirty){return ' M app/main.py'};return}
  default {throw ('UNEXPECTED_GIT_CALL: '+($arguments -join ' '))}
 }
}
function docker.exe {
 $arguments=@($args);$global:LASTEXITCODE=0
 if($arguments[0] -eq 'volume' -and $arguments[1] -eq 'ls'){
  if($script:Fixture.VolumeExists -or ($script:Fixture.Built -and $script:Fixture.VolumeDuringBuild)){return 'ola-cc-preview-data'}
  return
 }
 if($arguments[0] -eq 'build'){
  Event 'build'
  Assert-That (Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'source-manifest.json')) 'a clean checkout needs a generated manifest before build'
  if($script:Fixture.Build -eq 'failed'){$global:LASTEXITCODE=8;return}
  $script:Fixture.Built=$true
  if($script:Fixture.Build -eq 'change-source'){$script:Fixture.Sha=$script:OtherSha}
  if($script:Fixture.Build -eq 'change-manifest'){Write-FixtureManifest $script:TestSha 'ola-local-build-v1' ('1'*64)}
  if($script:Fixture.Build -eq 'reparse-manifest'){$script:Fixture.ReparseManifest=$true}
  return
 }
 if($arguments[0] -eq 'volume' -and $arguments[1] -eq 'create'){Event 'volume';return 'fake-volume'}
 if($arguments[0] -eq 'run'){Event 'run';return 'fake-container'}
 throw ('UNEXPECTED_DOCKER_CALL: '+($arguments -join ' '))
}
function Invoke-RestMethod {
 param([string]$Uri,[int]$TimeoutSec,[string]$Method='Get',[string]$Body,[string]$ContentType)
 if($Uri -eq 'http://127.0.0.1:11434/api/tags'){
  Assert-That ($Method -eq 'Get') 'listing model metadata must not start a model'
  if($script:Fixture.TagsResponseOverride){return $script:Fixture.TagsResponse}
  return [pscustomobject]@{models=$script:Fixture.Models}
 }
 if($Uri -eq 'http://127.0.0.1:11434/api/show'){
  Assert-That ($Method -eq 'Post' -and $ContentType -eq 'application/json') 'show must use the documented read-only JSON request'
  Assert-That ($script:Events.Count -eq 0) 'model locality must be checked before generation, build or provisioning'
  $script:Fixture.ShowCalls++
  $script:Fixture.ShowModelSeen=($Body|ConvertFrom-Json).model
  Assert-That ($script:Fixture.ShowModelSeen -in @($script:Fixture.Models|ForEach-Object{$_.name})) 'metadata must describe an installed model'
  if($script:Fixture.ShowFailure){throw 'FAKE_SHOW_UNAVAILABLE'}
  return $script:Fixture.ShowResponse
 }
 if($Uri -eq 'http://127.0.0.1:18081/health'){return [pscustomobject]@{status='ok'}}
 throw ('UNEXPECTED_HTTP_CALL: '+$Uri)
}
function Start-Sleep {param([int]$Seconds)}
function Assert-NoMutations {
 foreach($event in @('secret','volume','run')){Assert-That (!$script:Events.Contains($event)) ('blocked path performed '+$event)}
}
function Run-Case([string]$Name,[scriptblock]$Arrange,[string]$ExpectedError='',[scriptblock]$Check={}){
 if($CaseFilter -and $Name -notmatch $CaseFilter){return}
 Reset-Fixture
 & $Arrange
 $failure=$null
 try{Create-Preview}catch{$failure=$_.Exception.Message}
 if($ExpectedError){
  Assert-That ($null -ne $failure -and $failure.StartsWith($ExpectedError)) ($Name+' expected '+$ExpectedError+', got '+$failure)
  Assert-NoMutations
  if($ExpectedError -match '^(OLLAMA_|NO_LOCAL_OLLAMA_MODEL)'){
   Assert-That ($script:Events.Count -eq 0) 'unproven local models must stop before generation, build or provisioning'
  }
 }else{Assert-That ($null -eq $failure) ($Name+' failed: '+$failure)}
 & $Check
 $script:Cases++
 Write-Host ('PASS '+$Name)
}

try {
 Run-Case 'clean checkout without manifest' {} '' {
  Assert-That ($script:Fixture.ShowCalls -eq 1) 'a local model requires a successful metadata check'
  Assert-That (($script:Events -join ',') -eq 'generate,build,secret,volume,run') 'inventory and successful build must precede all provision effects'
  Assert-That (!(Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'NO-ACTUAL-SECRET.env'))) 'the harness must never create a secret file'
 }
 Run-Case 'explicit reviewed PR branch' {
  $script:ExpectedBranch='work/adr001-bound-review-integration-20261014'
  $script:Fixture.Branch=$script:ExpectedBranch
 }
 Run-Case 'default branch mismatch remains blocked' {$script:Fixture.Branch='work/other'} 'UNEXPECTED_GIT_BRANCH'
 Run-Case 'branch comparison is case-sensitive' {$script:ExpectedBranch=$script:DefaultBranch.ToUpperInvariant()} 'UNEXPECTED_GIT_BRANCH'
 Run-Case 'SHA mismatch' {$script:Fixture.Sha=$script:OtherSha} 'SOURCE_SHA_MISMATCH'
 Run-Case 'uppercase SHA is not a lowercase source pin' {$script:ExpectedSha=$script:TestSha.ToUpperInvariant()} 'EXPECTED_SOURCE_SHA_REQUIRED'
 Run-Case 'empty branch cannot disable guard' {$script:ExpectedBranch=''} 'EXPECTED_GIT_BRANCH_REQUIRED'
 Run-Case 'dirty checkout' {$script:Fixture.Dirty=$true} 'DIRTY_CHECKOUT_BLOCKED'
 Run-Case 'existing manifest reparse point is refused before generator' {$script:Fixture.ReparseManifest=$true} 'BUILD_INVENTORY_UNSAFE_PATH' {
  Assert-That ($script:Events.Count -eq 0) 'a reparse path must stop before generator, build or credential effects'
 }
 Run-Case 'generator fails' {$script:Fixture.Generator='failed'} 'BUILD_INVENTORY_GENERATION_FAILED' {
  Assert-That (!$script:Events.Contains('build')) 'a failed generator must prevent build'
 }
 Run-Case 'generator writes another SHA' {$script:Fixture.Generator='wrong-sha'} 'BUILD_INVENTORY_SOURCE_OR_SCHEMA_MISMATCH'
 Run-Case 'generator writes wrong schema' {$script:Fixture.Generator='wrong-schema'} 'BUILD_INVENTORY_SOURCE_OR_SCHEMA_MISMATCH'
 Run-Case 'source changes during generation' {$script:Fixture.Generator='change-source'} 'SOURCE_SHA_MISMATCH'
 Run-Case 'branch changes during generation' {$script:Fixture.Generator='change-branch'} 'UNEXPECTED_GIT_BRANCH'
 Run-Case 'manifest becomes reparse point after generation' {$script:Fixture.Generator='reparse-manifest'} 'BUILD_INVENTORY_UNSAFE_PATH' {
  Assert-That (!$script:Events.Contains('build')) 'a reparse inventory must prevent build'
 }
 Run-Case 'failed build leaves no secret or volume' {$script:Fixture.Build='failed'} 'BUILD_FAILED' {
  Assert-That (($script:Events -join ',') -eq 'generate,build') 'build failure must stop before credentials or data provisioning'
 }
 Run-Case 'source changes during build' {$script:Fixture.Build='change-source'} 'SOURCE_SHA_MISMATCH'
 Run-Case 'manifest changes during build' {$script:Fixture.Build='change-manifest'} 'BUILD_INVENTORY_CHANGED_DURING_BUILD'
 Run-Case 'manifest becomes reparse point during build' {$script:Fixture.Build='reparse-manifest'} 'BUILD_INVENTORY_UNSAFE_PATH'
 Run-Case 'existing preview is preserved' {$script:Fixture.PreviewExists=$true} 'PREVIEW_EXISTS' {
  Assert-That ($script:Events.Count -eq 0) 'an existing preview must stop before generation/build'
 }
 Run-Case 'existing volume is preserved' {$script:Fixture.VolumeExists=$true} 'PREVIEW_VOLUME_EXISTS' {
  Assert-That ($script:Events.Count -eq 0) 'an existing volume must stop before generation/build'
 }
 Run-Case 'preview appears during build' {$script:Fixture.PreviewDuringBuild=$true} 'PREVIEW_EXISTS'
 Run-Case 'volume appears during build' {$script:Fixture.VolumeDuringBuild=$true} 'PREVIEW_VOLUME_EXISTS'
 Run-Case 'Python unavailable' {$script:Fixture.PythonPresent=$false} 'LOCAL_PYTHON_310_OR_NEWER_REQUIRED'
 Run-Case 'explicit cloud tag is refused' {
  $script:Model='gpt-oss:cloud';$script:Fixture.Models=@([pscustomobject]@{name=$script:Model})
 } 'OLLAMA_CLOUD_MODEL_BLOCKED'
 Run-Case 'explicit size-cloud tag is refused' {
  $script:Model='gpt-oss:120b-cloud';$script:Fixture.Models=@([pscustomobject]@{name=$script:Model})
 } 'OLLAMA_CLOUD_MODEL_BLOCKED'
 Run-Case 'automatic cloud-only inventory is refused' {
  $script:Model='';$script:Fixture.Models=@([pscustomobject]@{name='gpt-oss:cloud'})
 } 'NO_LOCAL_OLLAMA_MODEL'
 Run-Case 'automatic size-cloud-only inventory is refused' {
  $script:Model='';$script:Fixture.Models=@([pscustomobject]@{name='gpt-oss:120b-cloud'})
 } 'NO_LOCAL_OLLAMA_MODEL'
 Run-Case 'automatic selection skips size-cloud tags' {
  $script:Model='';$script:Fixture.Models=@([pscustomobject]@{name='gpt-oss:120b-cloud'},[pscustomobject]@{name='local:test'})
 } '' {
  Assert-That ($script:Fixture.ShowModelSeen -ceq 'local:test') 'a mixed inventory must select and inspect the local model'
 }
 Run-Case 'tag metadata refuses a remote alias' {
  $script:Fixture.Models=@([pscustomobject]@{name='local:test';remote_host='https://ollama.com'})
 } 'OLLAMA_CLOUD_MODEL_BLOCKED'
 Run-Case 'show remote host refuses an ordinary alias' {
  $script:Fixture.ShowResponse|Add-Member -NotePropertyName remote_host -NotePropertyValue 'https://ollama.com'
 } 'OLLAMA_CLOUD_MODEL_BLOCKED'
 Run-Case 'show remote model refuses an ordinary alias' {
  $script:Fixture.ShowResponse|Add-Member -NotePropertyName remote_model -NotePropertyValue 'gpt-oss:120b'
 } 'OLLAMA_CLOUD_MODEL_BLOCKED'
 Run-Case 'missing show response is refused' {$script:Fixture.ShowResponse=$null} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'missing model info is refused' {$script:Fixture.ShowResponse.model_info=$null} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'empty model info is refused' {$script:Fixture.ShowResponse.model_info=[pscustomobject]@{}} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'nonobject model info is refused' {$script:Fixture.ShowResponse.model_info=@('llama')} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'missing local model details are refused' {$script:Fixture.ShowResponse.details=$null} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'unavailable show endpoint is refused' {$script:Fixture.ShowFailure=$true} 'OLLAMA_MODEL_DETAILS_UNAVAILABLE'
 Run-Case 'remote metadata of an invalid type is refused' {
  $script:Fixture.ShowResponse|Add-Member -NotePropertyName remote_host -NotePropertyValue @('https://ollama.com')
 } 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'empty remote strings remain valid for a local model' {
  $script:Fixture.ShowResponse|Add-Member -NotePropertyName remote_host -NotePropertyValue ''
  $script:Fixture.ShowResponse|Add-Member -NotePropertyName remote_model -NotePropertyValue ''
 }
 Run-Case 'empty show object is refused' {$script:Fixture.ShowResponse=[pscustomobject]@{}} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'empty local details object is refused' {$script:Fixture.ShowResponse.details=[pscustomobject]@{}} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'local format missing from details is refused' {$script:Fixture.ShowResponse.details=[pscustomobject]@{family='llama'}} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'nonstring local format is refused' {$script:Fixture.ShowResponse.details.format=42} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'missing tags response is refused' {
  $script:Fixture.TagsResponseOverride=$true;$script:Fixture.TagsResponse=$null
 } 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'empty tags object is refused' {
  $script:Fixture.TagsResponseOverride=$true;$script:Fixture.TagsResponse=[pscustomobject]@{}
 } 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'models in tags must be an array' {
  $script:Fixture.TagsResponseOverride=$true;$script:Fixture.TagsResponse=[pscustomobject]@{models=[pscustomobject]@{name='local:test'}}
 } 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'empty tag object is refused' {$script:Fixture.Models=@([pscustomobject]@{})} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'nonstring tag name is refused' {$script:Fixture.Models=@([pscustomobject]@{name=42})} 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'duplicate selected model metadata is refused' {
  $script:Fixture.Models=@([pscustomobject]@{name='local:test'},[pscustomobject]@{name='local:test'})
 } 'OLLAMA_MODEL_METADATA_INVALID'
 Run-Case 'automatic remote alias is refused' {
  $script:Model=''
  $script:Fixture.ShowResponse|Add-Member -NotePropertyName remote_host -NotePropertyValue 'https://ollama.com'
 } 'OLLAMA_CLOUD_MODEL_BLOCKED'
 Write-Host ('OLA_PREVIEW_BOOTSTRAP_HARNESS=PASS CASES='+$script:Cases+' SCOPE=MOCKED_POWERSHELL_CONTROL_FLOW')
}finally{
 if(Test-Path -LiteralPath $script:FixtureRoot){Remove-Item -LiteralPath $script:FixtureRoot -Recurse -Force}
}
