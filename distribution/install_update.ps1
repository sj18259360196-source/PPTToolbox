param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [Parameter(Mandatory=$true)][string]$ResultPath,
    [Parameter(Mandatory=$true)][string]$LogPath
)
$ErrorActionPreference = 'Stop'
$exitValue = 1
try {
    foreach ($value in @($Installer, $Destination, $ResultPath, $LogPath)) {
        if ($value.Contains('"') -or $value.Contains("`n") -or $value.Contains("`r")) { throw 'Invalid update path' }
        $current = [IO.Path]::GetFullPath($value)
        while ($current) {
            if (Test-Path -LiteralPath $current) {
                if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked update path' }
            }
            $current = [IO.Path]::GetDirectoryName($current)
        }
    }
    if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256) { throw 'Installer hash mismatch' }
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR="' + $Destination + '"'), ('/LOG="' + $LogPath + '"'))
    $process = Start-Process -FilePath $Installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    $exitValue = $process.ExitCode
} catch {
    [IO.File]::AppendAllText($LogPath, "`n" + $_.Exception.Message, [Text.UTF8Encoding]::new($false))
} finally {
    $result = @{version=$Version; exit_code=$exitValue; finished_at=[DateTime]::UtcNow.ToString('o')}
    [IO.File]::WriteAllText($ResultPath, ($result | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    $launcher = Join-Path $Destination 'PPTToolbox.exe'
    if (Test-Path -LiteralPath $launcher) { Start-Process -FilePath $launcher -WindowStyle Hidden }
}
