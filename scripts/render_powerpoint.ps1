[CmdletBinding()]
param(
    [string]$Pptx,
    [Parameter(Mandatory)][string]$OutputDir,
    [ValidateRange(1,16000)][int]$Width=1920,
    [ValidateRange(0,16000)][int]$Height=0,
    [switch]$ProbeOnly,
    [string]$SizesJson
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$out=[System.IO.Path]::GetFullPath($OutputDir)
if(Test-Path -LiteralPath $out){if(@(Get-ChildItem -LiteralPath $out -Force).Count -gt 0){throw 'OutputDir must be new or empty; never reuse old previews'}}
[System.IO.Directory]::CreateDirectory($out)|Out-Null
$report=[ordered]@{status='not_run';renderer='Microsoft PowerPoint';pptx_sha256=$null;slides=@();text_bounds=@();scope='Read-only PowerPoint open/export; visual and editing review not performed';probe_only=[bool]$ProbeOnly}
$app=$null;$deck=$null;$owned=$false;$code=0
try{
    if($env:OS -ne 'Windows_NT'){$report.status='blocked';throw 'Windows PowerPoint COM is required'}
    $app=New-Object -ComObject PowerPoint.Application
    $report['office_version']=[string]$app.Version
    if($ProbeOnly){$report.status='passed';$report.scope='COM availability only; no slide was rendered'}
    else{
        if([string]::IsNullOrWhiteSpace($Pptx)){throw '-Pptx is required unless -ProbeOnly'}
        $inputPath=(Resolve-Path -LiteralPath $Pptx).Path
        if([System.IO.Path]::GetExtension($inputPath).ToLowerInvariant() -ne '.pptx'){throw 'Only .pptx supported; macro-enabled/binary inputs require separate review'}
        for($i=1;$i -le $app.Presentations.Count;$i++){
            $existing=$app.Presentations.Item($i)
            if([string]::Equals([string]$existing.FullName,$inputPath,[System.StringComparison]::OrdinalIgnoreCase)){throw 'Target file is already open. Save/close it yourself or export a separate version; this script will not close user documents'}
        }
        $report.pptx_sha256=(Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        # ReadOnly true; Untitled false; WithWindow false. Never save source.
        $deck=$app.Presentations.Open($inputPath,-1,0,0);$owned=$true
        $wpt=[double]$deck.PageSetup.SlideWidth;$hpt=[double]$deck.PageSetup.SlideHeight
        if($Height -eq 0){$Height=[int][Math]::Round($Width*$hpt/$wpt)}
        if($Height -le 0){throw 'Invalid output height'}
        $report['canvas_pt']=@($wpt,$hpt)
        $sizes=@{}
        if($SizesJson){
            $entries=Get-Content -LiteralPath $SizesJson -Raw -Encoding UTF8|ConvertFrom-Json
            foreach($entry in $entries){
                if($entry.width -lt 1 -or $entry.width -gt 16000 -or $entry.height -lt 1 -or $entry.height -gt 16000){throw 'Invalid per-slide image size'}
                $sizes[[int]$entry.index]=@([int]$entry.width,[int]$entry.height)
            }
        }
        for($i=1;$i -le $deck.Slides.Count;$i++){
            $slide=$deck.Slides.Item($i);$file=Join-Path $out ('slide-{0:d3}.png' -f $i)
            $ew=$Width;$eh=$Height;if($sizes.ContainsKey($i)){$ew=$sizes[$i][0];$eh=$sizes[$i][1]}
            $slide.Export($file,'PNG',$ew,$eh)
            if(!(Test-Path -LiteralPath $file) -or (Get-Item -LiteralPath $file).Length -eq 0){throw "No export for slide $i"}
            $report.slides+=@{index=$i;file=[System.IO.Path]::GetFileName($file);sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant();width=$ew;height=$eh}
            for($j=1;$j -le $slide.Shapes.Count;$j++){
                $s=$slide.Shapes.Item($j)
                if($s.Type -eq 6){$report.text_bounds+=@{slide=$i;id=[string]$s.Name;status='not_run';reason='Grouped objects require recursive/local visual check'};continue}
                if($s.HasTable -eq -1){$report.text_bounds+=@{slide=$i;id=[string]$s.Name;status='not_run';reason='Table cells require separate checks'};continue}
                if($s.HasTextFrame -ne -1 -or $s.TextFrame2.HasText -ne -1){continue}
                try{
                    $t=$s.TextFrame2.TextRange
                    $g=@{slide=$i;id=[string]$s.Name;rotation=[double]$s.Rotation;box_pt=@([double]$s.Left,[double]$s.Top,[double]$s.Width,[double]$s.Height);bound_pt=@([double]$t.BoundLeft,[double]$t.BoundTop,[double]$t.BoundWidth,[double]$t.BoundHeight);status='not_run';reason='Raw text bounds recorded; interpret rotation/WordArt/margins against actual render'}
                    $report.text_bounds+=$g
                }catch{$report.text_bounds+=@{slide=$i;id=[string]$s.Name;status='blocked';reason=$_.Exception.Message}}
            }
        }
        $after=(Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if($after -ne $report.pptx_sha256){throw 'Source PPTX changed during rendering; all evidence invalidated'}
        $report.status='passed'
    }
}catch{
    if($report.status -ne 'blocked'){$report.status='failed'}
    $report['error']=$_.Exception.Message;$code=1
}finally{
    if($owned -and $null -ne $deck){try{$deck.Close()}catch{$report['close_warning']=$_.Exception.Message}}
    if($null -ne $deck){[void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($deck)}
    if($null -ne $app){[void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
    # No app.Quit, taskkill, or process-wide changes; a shared user Office instance may exist.
    $report['process_policy']='Closed only this script-owned presentation; no PowerPoint process terminated'
    $json=$report|ConvertTo-Json -Depth 15
    [System.IO.File]::WriteAllText((Join-Path $out 'office-render.json'),$json,[System.Text.UTF8Encoding]::new($false))
}
if($code -ne 0){Write-Error ($report.error) -ErrorAction Continue}
exit $code
