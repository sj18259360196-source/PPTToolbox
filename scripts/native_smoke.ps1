[CmdletBinding()]
param([Parameter(Mandatory)][string]$OutputPptx)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($env:OS -ne 'Windows_NT'){throw 'This native smoke test requires Windows and desktop PowerPoint'}
Import-Module (Join-Path $PSScriptRoot 'NativePpt.psm1') -Force
$out=[System.IO.Path]::GetFullPath($OutputPptx)
if(Test-Path -LiteralPath $out){throw 'Choose a new output file; existing files are not overwritten'}
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($out))|Out-Null
$app=$null;$deck=$null
try{
    $app=New-Object -ComObject PowerPoint.Application;$deck=$app.Presentations.Add(0)
    $deck.PageSetup.SlideWidth=960;$deck.PageSetup.SlideHeight=540
    $slide=$deck.Slides.Add(1,12)
    $null=Add-PptText -Slide $slide -Id 'smoke.title' -Text '原生对象功能样例 / Native smoke test' -Left 36 -Top 24 -Width 888 -Height 44 -FontSize 24 -Bold
    $left=Add-PptShape -Slide $slide -Id 'smoke.left' -Geometry RoundRectangle -Left 60 -Top 120 -Width 220 -Height 110 -Fill 'DCEBFA'
    Set-PptTwoColorGradient -Shape $left -Start 'E7F1FB' -End '6098D0' -Direction vertical
    $right=Add-PptShape -Slide $slide -Id 'smoke.right' -Geometry Oval -Left 520 -Top 120 -Width 110 -Height 110 -Fill 'DCEBFA'
    $null=Add-PptConnector -Slide $slide -Id 'smoke.bidirectional' -BeginShape $left -EndShape $right -BeginSite 3 -EndSite 1 -BeginArrow -EndArrow -Weight 2
    $cmds=@(@('M',60,360),@('C',60,280,280,280,280,360),@('L',60,360),@('Z'))
    $null=Add-PptPath -Slide $slide -Id 'smoke.halfdisc' -Commands $cmds -Fill '558CC4' -Line ''
    $rows=@(@('字段','测试值'),@('中文与单位','10 mg/L'),@('小数与符号','2.5% / ±10%'))
    $null=Add-PptTable -Slide $slide -Id 'smoke.table' -Rows $rows -Left 520 -Top 285 -Width 340 -Height 120
    $outer=Add-PptShape -Slide $slide -Id 'smoke.ring.outer' -Geometry Oval -Left 330 -Top 300 -Width 110 -Height 110 -Fill '7EAAD4'
    $inner=Add-PptShape -Slide $slide -Id 'smoke.ring.inner' -Geometry Oval -Left 355 -Top 325 -Width 60 -Height 60 -Fill 'FFFFFF'
    $null=Merge-PptShapes -Slide $slide -Id 'smoke.ring' -Names @('smoke.ring.outer','smoke.ring.inner') -Operation Subtract -PrimaryName 'smoke.ring.outer'
    $sample=Join-Path (Split-Path $PSScriptRoot -Parent) 'examples/sample-alpha.png'
    $null=Add-PptPictureFillShape -Slide $slide -Id 'smoke.picture-mask' -Path $sample -Geometry Oval -Left 700 -Top 420 -Width 60 -Height 60
    $null=Add-PptText -Slide $slide -Id 'smoke.note' -Text '仅用于功能验证，无参考原图，不代表复刻质量。' -Left 36 -Top 488 -Width 888 -Height 30 -FontSize 15
    $deck.SaveAs($out,24)
}finally{
    if($null -ne $deck){$deck.Close();[void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($deck)}
    if($null -ne $app){[void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
}
Write-Output "Created native test file: $out. Reopen and render it using render_powerpoint.ps1."
