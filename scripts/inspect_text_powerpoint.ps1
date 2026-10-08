[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Pptx,
    [Parameter(Mandatory)][string]$OutputDir,
    [ValidateRange(0,10)][double]$TolerancePt=0.75
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($env:OS -ne 'Windows_NT'){throw 'Actual Windows PowerPoint is required; this script has no fake or alternate renderer mode'}
$inputPath=(Resolve-Path -LiteralPath $Pptx).Path
if([IO.Path]::GetExtension($inputPath).ToLowerInvariant() -ne '.pptx'){throw 'Only .pptx inputs are handled'}
$out=[IO.Path]::GetFullPath($OutputDir)
if(Test-Path -LiteralPath $out){throw 'Use a new evidence directory'}
[IO.Directory]::CreateDirectory($out)|Out-Null
$rows=[System.Collections.Generic.List[object]]::new()
$before=(Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash.ToLowerInvariant()
$app=$null;$deck=$null;$owned=$false;$code=0
$report=[ordered]@{status='not_run';renderer='Microsoft PowerPoint';pptx_sha256=$before;scope='Recursive raw text and cell bounds. Not a semantic/visual/font identity certification.'}
function Read-TextObject {
    param($Shape,[int]$Slide,[string]$Path,[bool]$Grouped,[string]$Role)
    if($Shape.HasTextFrame -ne -1){return}
    try{
        $tf=$Shape.TextFrame2
        if($tf.HasText -ne -1){return}
        $t=$tf.TextRange;$rot=[double]$Shape.Rotation
        $bw=[double]$Shape.Width;$bh=[double]$Shape.Height
        $bound=@([double]$t.BoundLeft,[double]$t.BoundTop,[double]$t.BoundWidth,[double]$t.BoundHeight)
        $simple=(!$Grouped -and [Math]::Abs($rot%360) -lt 0.0001 -and $Role -eq 'shape')
        $candidate=$false
        if($simple){$candidate=($bound[2] -gt $bw-[double]$tf.MarginLeft-[double]$tf.MarginRight+$TolerancePt -or $bound[3] -gt $bh-[double]$tf.MarginTop-[double]$tf.MarginBottom+$TolerancePt)}
        $rows.Add([ordered]@{slide=$Slide;path=$Path;name=[string]$Shape.Name;role=$Role;text=[string]$t.Text;rotation=$rot;grouped=$Grouped;box_pt=@([double]$Shape.Left,[double]$Shape.Top,$bw,$bh);bound_pt=$bound;simple_geometry_comparison=$simple;candidate_overflow=$candidate;status= $(if($candidate){'needs_review'}elseif($simple){'no_simple_dimension_excess'}else{'local_review_required'});note='Group transforms, cell placement, WordArt and rotation require same-region visual comparison; raw bounds alone do not certify fitting.'})
    }catch{$rows.Add([ordered]@{slide=$Slide;path=$Path;status='blocked';error=$_.Exception.Message})}
}
function Walk-Shape {
    param($Shape,[int]$Slide,[string]$Path,[bool]$Grouped=$false,[int]$Depth=0)
    if($Depth -gt 32){throw 'Group depth exceeds inspection limit'}
    if($Shape.Type -eq 6){
        for($i=1;$i -le $Shape.GroupItems.Count;$i++){
            $child=$Shape.GroupItems.Item($i)
            Walk-Shape -Shape $child -Slide $Slide -Path ($Path+'/'+[string]$child.Name) -Grouped $true -Depth ($Depth+1)
        }
        return
    }
    if($Shape.HasTable -eq -1){
        $table=$Shape.Table
        for($r=1;$r -le $table.Rows.Count;$r++){
            for($c=1;$c -le $table.Columns.Count;$c++){
                try{Read-TextObject -Shape $table.Cell($r,$c).Shape -Slide $Slide -Path ($Path+'/cell-'+$r+'-'+$c) -Grouped $Grouped -Role 'table_cell'}
                catch{$rows.Add(@{slide=$Slide;path=($Path+'/cell-'+$r+'-'+$c);status='blocked';error=$_.Exception.Message})}
            }
        }
        return
    }
    Read-TextObject -Shape $Shape -Slide $Slide -Path $Path -Grouped $Grouped -Role 'shape'
}
try{
    $app=New-Object -ComObject PowerPoint.Application
    $report['office_version']=[string]$app.Version
    for($i=1;$i -le $app.Presentations.Count;$i++){
        if([string]::Equals([string]$app.Presentations.Item($i).FullName,$inputPath,[StringComparison]::OrdinalIgnoreCase)){throw 'Source is open in user Office; use a separate saved copy or close it yourself'}
    }
    $deck=$app.Presentations.Open($inputPath,-1,0,0);$owned=$true
    for($si=1;$si -le $deck.Slides.Count;$si++){
        $slide=$deck.Slides.Item($si)
        for($j=1;$j -le $slide.Shapes.Count;$j++){
            $shape=$slide.Shapes.Item($j);Walk-Shape -Shape $shape -Slide $si -Path ([string]$shape.Name)
        }
    }
    if((Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $before){throw 'Source changed during inspection'}
    $report.status='collected'
}catch{$report.status='failed';$report['error']=$_.Exception.Message;$code=1}
finally{
    if($owned -and $null -ne $deck){try{$deck.Close()}catch{$report['close_warning']=$_.Exception.Message}}
    if($null -ne $deck){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($deck)}
    if($null -ne $app){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
    $report['objects']=@($rows.ToArray())
    $report['process_policy']='Closed only the script-owned read-only presentation; no application Quit or taskkill'
    [IO.File]::WriteAllText((Join-Path $out 'recursive-text.json'),($report|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
}
exit $code
