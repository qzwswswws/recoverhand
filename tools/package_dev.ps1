param(
    [string]$Version = "v0.2.0",
    [string]$Date = (Get-Date -Format "yyyyMMdd")
)

$ErrorActionPreference = "Stop"
$sourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$archiveName = "RecoverHand-dev-$Version-$Date-win64"
$bundleName = "RecoverHand-dev"
$buildRoot = [IO.Path]::GetFullPath((Join-Path $sourceRoot "build\dev-package"))
$bundleRoot = Join-Path $buildRoot $bundleName
$distRoot = Join-Path $sourceRoot "dist"
$zipPath = Join-Path $distRoot "$archiveName.zip"
$hashPath = "$zipPath.sha256"

if (-not $buildRoot.StartsWith([IO.Path]::GetFullPath((Join-Path $sourceRoot "build")), [StringComparison]::OrdinalIgnoreCase)) {
    throw "The staging directory is outside the expected build directory: $buildRoot"
}

if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $bundleRoot -Force | Out-Null
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null

$excludedDirectories = @(
    ".venv", ".pytest_cache", ".ruff_cache", "__pycache__", "artifacts",
    "build", "data", "dist", "node_modules", "*.egg-info"
)
$excludedFiles = @("*.pyc", "*.pyo", "*.tsbuildinfo")
$robocopyArguments = @($sourceRoot, $bundleRoot, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD")
$robocopyArguments += $excludedDirectories
$robocopyArguments += "/XF"
$robocopyArguments += $excludedFiles
& robocopy @robocopyArguments | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "Robocopy failed with exit code $LASTEXITCODE"
}

$decisionRoot = [IO.Path]::GetFullPath((Join-Path $sourceRoot "..\项目\辅助屈伸手套"))
$decisionTarget = Join-Path $bundleRoot "docs\decision_records"
$decisionFiles = @(
    @{ Source = "ADR-20260911-上位机改用Qt-Widgets桌面架构.md"; Target = "ADR-qt-widgets-desktop.md" },
    @{ Source = "ADR-20260911-上位机设备抽象与连接设置.md"; Target = "ADR-device-abstraction.md" },
    @{ Source = "ADR-20260911-数字手镜像与姿态接口.md"; Target = "ADR-virtual-hand-mapping.md" },
    @{ Source = "ADR-20260911-复用MIdemo-P03E三维粒子手.md"; Target = "ADR-p03e-integration.md" },
    @{ Source = "ADR-20260912-P03E内嵌性能档.md"; Target = "ADR-p03e-embed-performance.md" },
    @{ Source = "ADR-20260916-唯理单通道肌电贴只读接入.md"; Target = "ADR-waveletech-emg-integration.md" },
    @{ Source = "ADR-20260916-肌电原始信号独立监视器.md"; Target = "ADR-emg-standalone-monitor.md" },
    @{ Source = "ADR-20260914-上位机开发包与环境复现.md"; Target = "ADR-development-bundle.md" }
)
New-Item -ItemType Directory -Path $decisionTarget -Force | Out-Null
foreach ($decisionFile in $decisionFiles) {
    $decisionPath = Join-Path $decisionRoot $decisionFile.Source
    if (Test-Path -LiteralPath $decisionPath) {
        Copy-Item -LiteralPath $decisionPath -Destination (Join-Path $decisionTarget $decisionFile.Target)
    }
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $hashPath) {
    Remove-Item -LiteralPath $hashPath -Force
}
Compress-Archive -LiteralPath $bundleRoot -DestinationPath $zipPath -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
"$hash  $archiveName.zip" | Set-Content -LiteralPath $hashPath -Encoding ascii

Remove-Item -LiteralPath $buildRoot -Recurse -Force
Write-Host "Development bundle: $zipPath"
Write-Host "SHA-256: $hash"
