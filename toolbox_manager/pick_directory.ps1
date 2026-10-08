$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$picker = [System.Windows.Forms.FolderBrowserDialog]::new()
$owner = [System.Windows.Forms.Form]::new()
try {
    $picker.Description = '选择默认项目根目录'
    if ($picker.PSObject.Properties['UseDescriptionForTitle']) { $picker.UseDescriptionForTitle = $true }
    $picker.ShowNewFolderButton = $true
    if ($env:PPT_TOOLBOX_PICK_INITIAL -and (Test-Path -LiteralPath $env:PPT_TOOLBOX_PICK_INITIAL -PathType Container)) {
        $picker.SelectedPath = $env:PPT_TOOLBOX_PICK_INITIAL
    }
    $owner.ShowInTaskbar = $false
    $owner.Opacity = 0
    $owner.TopMost = $true
    $owner.Show()
    $result = if ($picker.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        @{ cancelled = $false; path = $picker.SelectedPath }
    } else {
        @{ cancelled = $true }
    }
    $result | ConvertTo-Json -Compress
} finally {
    $picker.Dispose()
    $owner.Dispose()
}
