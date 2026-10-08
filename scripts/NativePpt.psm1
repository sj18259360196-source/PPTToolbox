# Native PowerPoint operation helpers. Tested API references, NOT Office-runtime-certified in this package.
# Geometry/line widths/fonts are points. PowerShell 5.1+ on Windows.
Set-StrictMode -Version Latest
$script:C = @{
    False=0; True=-1; BlankLayout=12; TextHorizontal=1; AlignLeft=1; AlignCenter=2; AlignRight=3;
    AnchorTop=1; AnchorMiddle=3; AnchorBottom=4; AutoSizeNone=0;
    Rectangle=1; RoundRectangle=5; Oval=9; Triangle=7; Diamond=4; RightArrow=33; LeftRightArrow=37; Star5=92;
    ConnectorStraight=1; ConnectorElbow=2; ConnectorCurve=3;
    SegmentLine=0; SegmentCurve=1; EditingAuto=0; EditingCorner=1;
    BringToFront=0; SendToBack=1; BringForward=2; SendBackward=3; GradientHorizontal=1; GradientVertical=2;
    MergeUnion=1; MergeCombine=2; MergeIntersect=3; MergeSubtract=4; MergeFragment=5;
    ArrowNone=1; ArrowTriangle=2; ArrowStealth=4; PptxFormat=24
}
function ConvertTo-PptRgb {
    param([Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{6}$')][string]$Hex)
    $r=[Convert]::ToInt32($Hex.Substring(0,2),16);$g=[Convert]::ToInt32($Hex.Substring(2,2),16);$b=[Convert]::ToInt32($Hex.Substring(4,2),16)
    return ($r + 256*$g + 65536*$b)
}
function Set-PptSolidStyle {
    param([Parameter(Mandatory)]$Shape,[AllowNull()][string]$Fill,[AllowNull()][string]$Line,[double]$LineWidth=1)
    $Shape.Shadow.Visible=$script:C.False
    if ([string]::IsNullOrEmpty($Fill)) {$Shape.Fill.Visible=$script:C.False}
    else {$Shape.Fill.Visible=$script:C.True;$Shape.Fill.Solid();$Shape.Fill.ForeColor.RGB=ConvertTo-PptRgb $Fill}
    if ([string]::IsNullOrEmpty($Line)) {$Shape.Line.Visible=$script:C.False}
    else {$Shape.Line.Visible=$script:C.True;$Shape.Line.ForeColor.RGB=ConvertTo-PptRgb $Line;$Shape.Line.Weight=$LineWidth}
}
function Add-PptText {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,
      [Parameter(Mandatory)][string]$Text,[double]$Left,[double]$Top,[double]$Width,[double]$Height,
      [string]$Font='Arial',[string]$EastAsiaFont='Microsoft YaHei',[double]$FontSize=18,
      [string]$Color='222222',[switch]$Bold,[ValidateSet('left','center','right')][string]$Align='left',
      [ValidateSet('top','middle','bottom')][string]$VerticalAlign='top',[double]$Margin=0,[switch]$Wrap,[double]$LineSpacing=0)
    if ($Width -le 0 -or $Height -le 0) {throw 'Text box needs positive Width and Height'}
    $s=$Slide.Shapes.AddTextbox($script:C.TextHorizontal,$Left,$Top,$Width,$Height);$s.Name=$Id
    $tf=$s.TextFrame;$tf.AutoSize=$script:C.AutoSizeNone;$tf.WordWrap=$(if($Wrap){-1}else{0})
    $tf.MarginLeft=$Margin;$tf.MarginRight=$Margin;$tf.MarginTop=$Margin;$tf.MarginBottom=$Margin
    $tf.VerticalAnchor=@{top=1;middle=3;bottom=4}[$VerticalAlign]
    $tr=$tf.TextRange;$tr.Text=($Text -replace "`r`n|`n","`r")
    $tr.Font.Name=$Font;$tr.Font.NameAscii=$Font;$tr.Font.NameFarEast=$EastAsiaFont;$tr.Font.NameOther=$Font
    $tr.Font.Size=$FontSize;$tr.Font.Bold=$(if($Bold){-1}else{0});$tr.Font.Color.RGB=ConvertTo-PptRgb $Color
    $pf=$tr.ParagraphFormat;$pf.Alignment=@{left=1;center=2;right=3}[$Align]
    $pf.SpaceBefore=0;$pf.SpaceAfter=0
    if ($LineSpacing -gt 0) {$pf.LineRuleWithin=0;$pf.SpaceWithin=$LineSpacing}
    # Reapply geometry after text setup; repeated historical shrink-width symptom.
    $s.Left=$Left;$s.Top=$Top;$s.Width=$Width;$s.Height=$Height
    $s.Fill.Visible=0;$s.Line.Visible=0;$s.Shadow.Visible=0
    return $s
}
function Add-PptShape {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,
      [ValidateSet('Rectangle','RoundRectangle','Oval','Triangle','Diamond','RightArrow','LeftRightArrow','Star5')][string]$Geometry='Rectangle',
      [double]$Left,[double]$Top,[double]$Width,[double]$Height,[string]$Fill='FFFFFF',[string]$Line='',[double]$LineWidth=1)
    $s=$Slide.Shapes.AddShape($script:C[$Geometry],$Left,$Top,$Width,$Height);$s.Name=$Id
    Set-PptSolidStyle -Shape $s -Fill $Fill -Line $Line -LineWidth $LineWidth
    return $s
}
function Set-PptTwoColorGradient {
    param([Parameter(Mandatory)]$Shape,[Parameter(Mandatory)][string]$Start,[Parameter(Mandatory)][string]$End,
      [ValidateSet('horizontal','vertical')][string]$Direction='vertical')
    $style=$(if($Direction -eq 'horizontal'){1}else{2})
    $Shape.Fill.Visible=-1;$Shape.Fill.TwoColorGradient($style,1)
    $Shape.Fill.ForeColor.RGB=ConvertTo-PptRgb $Start;$Shape.Fill.BackColor.RGB=ConvertTo-PptRgb $End
    # Visual direction depends on variant/rendering. Verify before replication.
}
function Add-PptLine {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,
      [double]$X1,[double]$Y1,[double]$X2,[double]$Y2,[string]$Color='345678',[double]$Weight=1,
      [switch]$BeginArrow,[switch]$EndArrow)
    $s=$Slide.Shapes.AddLine($X1,$Y1,$X2,$Y2);$s.Name=$Id;$s.Shadow.Visible=0
    $s.Line.ForeColor.RGB=ConvertTo-PptRgb $Color;$s.Line.Weight=$Weight
    $s.Line.BeginArrowheadStyle=$(if($BeginArrow){2}else{1});$s.Line.EndArrowheadStyle=$(if($EndArrow){2}else{1})
    return $s
}
function Add-PptConnector {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,
      [Parameter(Mandatory)]$BeginShape,[Parameter(Mandatory)]$EndShape,
      [ValidateRange(0,99)][int]$BeginSite=0,[ValidateRange(0,99)][int]$EndSite=0,
      [ValidateSet('straight','elbow','curve')][string]$Kind='straight',[string]$Color='345678',[double]$Weight=1,
      [switch]$BeginArrow,[switch]$EndArrow)
    $s=$Slide.Shapes.AddConnector(@{straight=1;elbow=2;curve=3}[$Kind],0,0,1,1);$s.Name=$Id
    # scene/site convention is zero-based; Office COM is one-based.
    $s.ConnectorFormat.BeginConnect($BeginShape,$BeginSite+1);$s.ConnectorFormat.EndConnect($EndShape,$EndSite+1)
    $s.Line.ForeColor.RGB=ConvertTo-PptRgb $Color;$s.Line.Weight=$Weight;$s.Shadow.Visible=0
    $s.Line.BeginArrowheadStyle=$(if($BeginArrow){2}else{1});$s.Line.EndArrowheadStyle=$(if($EndArrow){2}else{1})
    # Do not auto-reroute a reference-matched path without checking its semantics/layout.
    return $s
}
function Add-PptPath {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,
      [Parameter(Mandatory)][object[]]$Commands,[string]$Fill='',[string]$Line='345678',[double]$LineWidth=1)
    if ($Commands.Count -lt 2 -or $Commands[0][0] -ne 'M') {throw 'Commands must start with [M,x,y]'}
    $start=$Commands[0];$b=$Slide.Shapes.BuildFreeform(1,[double]$start[1],[double]$start[2])
    for($i=1;$i -lt $Commands.Count;$i++){
        $n=$Commands[$i]
        switch($n[0]){
            'L' {if($n.Count -ne 3){throw 'L needs x,y'};$b.AddNodes(0,0,[double]$n[1],[double]$n[2])}
            'C' {if($n.Count -ne 7){throw 'C needs two control points and endpoint'};$b.AddNodes(1,1,[double]$n[1],[double]$n[2],[double]$n[3],[double]$n[4],[double]$n[5],[double]$n[6])}
            'Z' {$b.AddNodes(0,0,[double]$start[1],[double]$start[2])}
            default {throw "Unsupported path command $($n[0]); do not silently substitute"}
        }
    }
    $s=$b.ConvertToShape();$s.Name=$Id;Set-PptSolidStyle -Shape $s -Fill $Fill -Line $Line -LineWidth $LineWidth
    return $s
}
function Add-PptPicture {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][string]$Path,
      [double]$Left,[double]$Top,[double]$Width,[double]$Height)
    $full=(Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    # Embedded, never linked. Width/Height are explicit; prepare contain/cover geometry beforehand.
    $s=$Slide.Shapes.AddPicture($full,0,-1,$Left,$Top,$Width,$Height);$s.Name=$Id
    return $s
}
function Add-PptTable {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][object[]]$Rows,
      [double]$Left,[double]$Top,[double]$Width,[double]$Height,[double]$FontSize=14,[string]$EastAsiaFont='Microsoft YaHei')
    $nrow=$Rows.Count;$ncol=$Rows[0].Count
    foreach($row in $Rows){if($row.Count -ne $ncol){throw 'Table rows have different column counts'}}
    $s=$Slide.Shapes.AddTable($nrow,$ncol,$Left,$Top,$Width,$Height);$s.Name=$Id
    for($r=1;$r -le $nrow;$r++){
        for($c=1;$c -le $ncol;$c++){
            $tf=$s.Table.Cell($r,$c).Shape.TextFrame;$tf.TextRange.Text=[string]$Rows[$r-1][$c-1]
            $tf.MarginLeft=3;$tf.MarginRight=3;$tf.MarginTop=1;$tf.MarginBottom=1
            $tf.TextRange.Font.Name='Arial';$tf.TextRange.Font.NameFarEast=$EastAsiaFont;$tf.TextRange.Font.Size=$FontSize
            $tf.TextRange.ParagraphFormat.SpaceBefore=0;$tf.TextRange.ParagraphFormat.SpaceAfter=0
        }
        $s.Table.Rows.Item($r).Height=$Height/$nrow
    }
    return $s
}
function Group-PptObjects {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][string[]]$Names)
    if($Names.Count -lt 2){throw 'Grouping needs at least two objects'}
    $range=$Slide.Shapes.Range([object[]]$Names);$group=$range.Group();$group.Name=$Id
    return $group
}
function Set-PptShapePictureFill {
    param([Parameter(Mandatory)]$Shape,[Parameter(Mandatory)][string]$Path)
    $full=(Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    $Shape.Fill.Visible=$script:C.True
    $Shape.Fill.UserPicture($full)
    return $Shape
}
function Add-PptPictureFillShape {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][string]$Path,
      [ValidateSet('Rectangle','RoundRectangle','Oval','Triangle','Diamond','RightArrow','LeftRightArrow','Star5')][string]$Geometry='Rectangle',
      [double]$Left,[double]$Top,[double]$Width,[double]$Height,[string]$Line='',[double]$LineWidth=1)
    $s=Add-PptShape -Slide $Slide -Id $Id -Geometry $Geometry -Left $Left -Top $Top -Width $Width -Height $Height -Fill 'FFFFFF' -Line $Line -LineWidth $LineWidth
    Set-PptShapePictureFill -Shape $s -Path $Path | Out-Null
    return $s
}
function Set-PptPictureCrop {
    param([Parameter(Mandatory)]$Shape,[double]$Left=0,[double]$Top=0,[double]$Right=0,[double]$Bottom=0)
    if ($Left -lt 0 -or $Top -lt 0 -or $Right -lt 0 -or $Bottom -lt 0) {throw 'Crop values must be non-negative point amounts'}
    $pf=$Shape.PictureFormat
    $pf.CropLeft=$Left;$pf.CropTop=$Top;$pf.CropRight=$Right;$pf.CropBottom=$Bottom
    return $Shape
}
function Set-PptZOrder {
    param([Parameter(Mandatory)]$Shape,[ValidateSet('BringToFront','SendToBack','BringForward','SendBackward')][string]$Action)
    $Shape.ZOrder($script:C[$Action])
    return $Shape
}
function Merge-PptShapes {
    param([Parameter(Mandatory)]$Slide,[Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][string[]]$Names,
      [ValidateSet('Union','Combine','Intersect','Subtract','Fragment')][string]$Operation='Union',[string]$PrimaryName='')
    if ($Names.Count -lt 2) {throw 'MergeShapes needs at least two objects'}
    foreach($n in $Names){$null=$Slide.Shapes.Item($n)}
    if ([string]::IsNullOrEmpty($PrimaryName)) {$PrimaryName=$Names[0]}
    if ($Names -notcontains $PrimaryName) {throw 'PrimaryName must be one of Names'}
    $before=@{};for($i=1;$i -le $Slide.Shapes.Count;$i++){$before[[int]$Slide.Shapes.Item($i).Id]=$true}
    $range=$Slide.Shapes.Range([object[]]$Names);$primary=$Slide.Shapes.Item($PrimaryName)
    $cmd=@{Union=1;Combine=2;Intersect=3;Subtract=4;Fragment=5}[$Operation]
    $range.MergeShapes($cmd,$primary)
    $created=@()
    for($i=1;$i -le $Slide.Shapes.Count;$i++){$x=$Slide.Shapes.Item($i);if(-not $before.ContainsKey([int]$x.Id)){$created+=,$x}}
    if ($created.Count -eq 0) {throw 'MergeShapes completed but no new shape ID was detected; inspect current Office behavior before continuing'}
    if ($created.Count -eq 1) {$created[0].Name=$Id;return $created[0]}
    for($i=0;$i -lt $created.Count;$i++){$created[$i].Name="$Id.$($i+1)"}
    return ,$created
}
Export-ModuleMember -Function ConvertTo-PptRgb,Add-PptText,Add-PptShape,Set-PptSolidStyle,Set-PptTwoColorGradient,Add-PptLine,Add-PptConnector,Add-PptPath,Add-PptPicture,Add-PptTable,Group-PptObjects,Set-PptShapePictureFill,Add-PptPictureFillShape,Set-PptPictureCrop,Set-PptZOrder,Merge-PptShapes
