# Read-only diagnostic for a Windows OLA checkout; not an installer or release gate.
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$RepoRoot,
 [string]$ExpectedSha='',
 [string]$OutputFile='',
 [switch]$ProbeLoopback
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Write-Report($Report) {
 $json=$Report | ConvertTo-Json -Depth 12
 if($OutputFile){
  $destination=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputFile)
  [IO.File]::WriteAllText($destination,$json+[Environment]::NewLine,(New-Object Text.UTF8Encoding($false)))
 }
 Write-Output $json
}
function Quote-NativeArgument([string]$Value) {
 # Windows CommandLineToArgvW escaping; no shell is used.
 $escaped=[regex]::Replace($Value,'(\\*)"','$1$1\"')
 $escaped=[regex]::Replace($escaped,'(\\+)$','$1$1')
 return '"'+$escaped+'"'
}
function Read-Command([string]$Executable,[string[]]$Arguments) {
 $process=New-Object Diagnostics.Process
 $info=New-Object Diagnostics.ProcessStartInfo
 $info.FileName=$Executable
 $info.Arguments=(@($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $process.StartInfo=$info
 $timer=[Diagnostics.Stopwatch]::StartNew()
 try {
  [void]$process.Start()
  $stdout=$process.StandardOutput.ReadToEndAsync()
  $stderr=$process.StandardError.ReadToEndAsync()
  if(!$process.WaitForExit(8000)){
   try{$process.Kill()}catch{}
   [void]$process.WaitForExit(1000)
   return @{state='TIMEOUT';value=$null}
  }
  if($process.ExitCode -ne 0){return @{state='COMMAND_FAILED';value=$null}}
  # A child can inherit these handles even after the parent exits. Apply the
  # same deadline to stream completion; never wait unboundedly for GetResult.
  $remaining=[int][Math]::Max(0,8000-$timer.ElapsedMilliseconds)
  if(![Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdout,$stderr),$remaining)){
   return @{state='TIMEOUT';value=$null}
  }
  return @{state='OK';value=([string]$stdout.GetAwaiter().GetResult()).Trim()}
 }catch{return @{state='UNAVAILABLE';value=$null}}
 finally{$process.Dispose()}
}
function Find-Application([string]$Name) {
 $commands=@(Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
 if($commands.Count){return [string]$commands[0].Source}
 return $null
}
function Read-Git([string[]]$Arguments) {
 return Read-Command $script:GitPath (@('--no-optional-locks','-c','core.fsmonitor=false','-C',$script:Checkout)+$Arguments)
}

$report=[ordered]@{
 schema='ola.windows-preflight/v1';created_utc=[DateTime]::UtcNow.ToString('o')
 diagnostic='NOT_RUN';platform=[Environment]::OSVersion.Platform.ToString()
 powershell=$PSVersionTable.PSVersion.ToString();product_readiness='NOT_ASSESSED'
 production_authorization='NOT_GRANTED_BY_THIS_REPORT'
 tools=@{};checkout=@{};required_files=@{};loopback=@();warnings=@()
 limits=@('No application, model, container or workflow started or stopped.',
          'No keys, environment values, remote URLs or response bodies collected.',
          'File presence, source SHA and HTTP status do not prove a working ecosystem.')
}
if([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT){
 $report.diagnostic='WINDOWS_REQUIRED';Write-Report $report;exit 2
}
if($ExpectedSha -and $ExpectedSha -cnotmatch '^[0-9a-f]{40}$'){
 throw 'ExpectedSha must be a full lowercase 40-hex Git commit.'
}
$script:Checkout=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RepoRoot)
if(!(Test-Path -LiteralPath $script:Checkout -PathType Container)){
 $report.diagnostic='CHECKOUT_NOT_FOUND';Write-Report $report;exit 3
}
foreach($name in @('git.exe','docker.exe','node.exe','python.exe','py.exe','ollama.exe')){
 $path=Find-Application $name
 $entry=@{installed=[bool]$path;version_state='NOT_QUERIED';version=$null}
 # Merely detect py/ollama: their configuration may select another runtime/host.
 if($path -and $name -in @('git.exe','docker.exe','node.exe','python.exe')){
  $version=Read-Command $path @('--version')
  $entry.version_state=$version.state
  if($version.state -eq 'OK'){$entry.version=([string]$version.value).Substring(0,[Math]::Min(160,([string]$version.value).Length))}
 }
 $report.tools[$name]=$entry
}
$script:GitPath=Find-Application 'git.exe'
if(!$script:GitPath){$report.diagnostic='GIT_MISSING';Write-Report $report;exit 4}
$top=Read-Git @('rev-parse','--show-toplevel')
if($top.state -ne 'OK'){$report.diagnostic='NOT_A_GIT_CHECKOUT';Write-Report $report;exit 5}
if([IO.Path]::GetFullPath($top.value).TrimEnd('\','/') -ine $script:Checkout.TrimEnd('\','/')){
 $report.diagnostic='REPO_ROOT_MUST_BE_GIT_TOPLEVEL';Write-Report $report;exit 6
}
$head=Read-Git @('rev-parse','HEAD')
$tree=Read-Git @('rev-parse','HEAD^{tree}')
$branch=Read-Git @('symbolic-ref','--quiet','--short','HEAD')
$changes=Read-Git @('status','--porcelain=v1','--untracked-files=all')
$changeLines=@()
if($changes.state -eq 'OK' -and $changes.value){$changeLines=@($changes.value -split "`r?`n")}
$report.checkout=@{
 root=$script:Checkout;head=$head.value;head_state=$head.state;tree=$tree.value;tree_state=$tree.state
 branch=$branch.value;branch_state=$branch.state;status_state=$changes.state
 dirty=($changes.state -ne 'OK' -or $changeLines.Count -gt 0);changed_entries=$changeLines.Count
 expected_sha=$ExpectedSha;expected_sha_match=$null
}
if($ExpectedSha){$report.checkout.expected_sha_match=($head.state -eq 'OK' -and $head.value -ceq $ExpectedSha)}
foreach($relative in @('CLAUDE.md','AGENTS.md','Dockerfile','requirements.txt','web/index.html',
 'app/main.py','app/execution_binding.py','policies/nina-review-v1.json',
 'scripts/build_source_manifest.py','source-manifest.json','workstation/OLA-Preview-Auth.ps1',
 'workstation/OLA-Local-Executor.ps1','tests/aurora_approval_state.test.cjs')){
 $report.required_files[$relative]=Test-Path -LiteralPath (Join-Path $script:Checkout $relative) -PathType Leaf
}
if($report.checkout.dirty){$report.warnings+= 'Checkout has changes or Git status is unavailable. Do not label it a clean source pin.'}
if(!$report.required_files['source-manifest.json']){
 $report.warnings+='Build inventory is absent. The preview bootstrap must generate it from the committed source before docker build.'
}
$report.warnings+='Do not use the historical OLA-Workstation.ps1 as the current preview installer.'
$report.warnings+='Existing preview data and volumes must be inspected and preserved before any replacement.'
if($ProbeLoopback){
 foreach($target in @(
  @{port=8000;path='/health'},@{port=8001;path='/api/health'},
  @{port=18080;path='/health'},@{port=18081;path='/health'},
  @{port=18110;path='/health'},@{port=11434;path='/api/tags'})){
  $response=$null
  $probe=@{host='127.0.0.1';port=$target.port;path=$target.path;http_status=$null;state='UNREACHABLE_OR_TIMEOUT'}
  try{
   $request=[Net.HttpWebRequest]::Create('http://127.0.0.1:'+$target.port+$target.path)
   $request.Method='GET';$request.Timeout=1500;$request.ReadWriteTimeout=1500
   $request.AllowAutoRedirect=$false;$request.Proxy=$null
   try{$response=$request.GetResponse()}catch [Net.WebException]{$response=$_.Exception.Response}
   if($response){$probe.http_status=[int]$response.StatusCode;$probe.state='HTTP_RESPONSE_ONLY'}
  }catch{}finally{if($response){$response.Close()}}
  $report.loopback+=$probe
 }
}
$report.diagnostic='COLLECTED';Write-Report $report
