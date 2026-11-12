$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Official CPython NuGet distribution, version and hash pinned. It is installed
# only inside this project and does not alter the user's system Python or PATH.
$url = 'https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg'
$sha256 = '0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $root 'app\runtime'
$target = Join-Path $runtimeDir 'python-base'
$downloads = Join-Path $root 'app\work\installer-downloads'
$staging = Join-Path $runtimeDir ('python-base.incomplete-' + [Guid]::NewGuid().ToString('N'))
$archive = Join-Path $downloads ('python-3.12.10-' + [Guid]::NewGuid().ToString('N') + '.nupkg')

try {
    if (Test-Path -LiteralPath $target) {
        throw "Python target already exists; retained without modification: $target"
    }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    New-Item -ItemType Directory -Path $downloads -Force | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actual -ne $sha256) { throw "Python download failed SHA-256 verification: $archive" }

    New-Item -ItemType Directory -Path $staging | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $prefix = [IO.Path]::GetFullPath($staging).TrimEnd('\') + '\'
        foreach ($entry in $zip.Entries) {
            if (-not $entry.FullName.StartsWith('tools/', [StringComparison]::Ordinal)) { continue }
            $relative = $entry.FullName.Substring(6).Replace('/', '\')
            if ([string]::IsNullOrEmpty($relative)) { continue }
            $destination = [IO.Path]::GetFullPath((Join-Path $staging $relative))
            if (-not $destination.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe archive entry: $($entry.FullName)"
            }
            if ($entry.FullName.EndsWith('/')) {
                New-Item -ItemType Directory -Path $destination -Force | Out-Null
            } else {
                New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $false)
            }
        }
    } finally { $zip.Dispose() }
    $python = Join-Path $staging 'python.exe'
    & $python -c 'import sys,venv,ensurepip; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32'
    if ($LASTEXITCODE -ne 0) { throw 'The extracted Python runtime failed its self-check.' }
    Set-Content -LiteralPath (Join-Path $staging '.aigc-python-base') -Value 'CPython 3.12.10 NuGet package' -Encoding UTF8
    if (Test-Path -LiteralPath $target) { throw "Target appeared during installation; retained: $target" }
    Move-Item -LiteralPath $staging -Destination $target
    Write-Host "Local Python is ready: $target"
} catch {
    Write-Error ("Python preparation failed. Download and partial files were retained for inspection. " + $_.Exception.Message)
    exit 1
}
