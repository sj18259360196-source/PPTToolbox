# Dot-sourced only for an explicitly requested calibration export.
# Raw Office values; no font substitution or visual verdict is inferred.
function Read-TextCalibration {
    param($Shape)
    $tf=$Shape.TextFrame2
    $range=$tf.TextRange
    $lines=[System.Collections.Generic.List[object]]::new()
    $runs=[System.Collections.Generic.List[object]]::new()
    $errors=[System.Collections.Generic.List[string]]::new()
    $truncated=$false
    try {
        $count=[int]$range.Lines().Count
        if($count -gt 128){$truncated=$true}
        for($li=1;$li -le [Math]::Min(128,$count);$li++){
            $line=$range.Lines($li,1)
            $lines.Add(@{index=$li;text=[string]$line.Text;bound_pt=@([double]$line.BoundLeft,[double]$line.BoundTop,[double]$line.BoundWidth,[double]$line.BoundHeight);bound_height_pt=[double]$line.BoundHeight;baseline_y_pt=$null})
        }
    }catch{$errors.Add('lines: '+$_.Exception.Message)}
    try {
        $count=[int]$range.Runs().Count
        if($count -gt 128){$truncated=$true}
        for($ri=1;$ri -le [Math]::Min(128,$count);$ri++){
            $run=$range.Runs($ri,1);$font=$run.Font
            $size=[double]$font.Size;$offset=[double]$font.BaselineOffset
            $runs.Add(@{index=$ri;text=[string]$run.Text;font=[string]$font.Name;font_ascii=[string]$font.NameAscii;font_east_asia=[string]$font.NameFarEast;office_font_size_pt=$size;baseline_offset_fraction=$offset;baseline_shift_pt=$size*$offset;bound_pt=@([double]$run.BoundLeft,[double]$run.BoundTop,[double]$run.BoundWidth,[double]$run.BoundHeight)})
        }
    }catch{$errors.Add('runs: '+$_.Exception.Message)}
    return @{format='office-text-calibration/1';text=[string]$range.Text;auto_size=[int]$tf.AutoSize;word_wrap=[int]$tf.WordWrap;margins_pt=@([double]$tf.MarginLeft,[double]$tf.MarginTop,[double]$tf.MarginRight,[double]$tf.MarginBottom);lines=@($lines.ToArray());runs=@($runs.ToArray());truncated=$truncated;errors=@($errors.ToArray());baseline_y_status='unavailable_from_collector';baseline_shift_basis='Office Font.BaselineOffset relative to the normal baseline; not page Y';glyph_font_identity='not_certified'}
}
