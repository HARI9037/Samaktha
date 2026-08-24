<#>
.SYNOPSIS
    Build Samaktha Windows executable using PyInstaller (ONEDIR mode).

.DESCRIPTION
    This script builds the Samaktha application for Windows distribution.
    It creates a standalone executable with all dependencies bundled.

.NOTES
    Requires: Python 3.12+, PyInstaller 6+
    Output: dist/samaktha/samaktha.exe (ONEDIR mode)
#>

param(
    [switch]$Clean
)

# Determine repository root
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $RepoRoot

# Import version from pyproject.toml
$PyProject = Get-Content pyproject.toml -Raw
$VersionMatch = [regex]::Match($PyProject, '^version\s*=\s*"([^"]+)"', 'Multiline')
$AppVersion = if ($VersionMatch.Success) { $VersionMatch.Groups[1].Value } else { "0.0.0" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Samaktha Windows Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Repository: $RepoRoot"
Write-Host "Version: $AppVersion"
Write-Host ""

# Clean previous builds if requested
if ($Clean) {
    Write-Host "Cleaning previous builds..." -ForegroundColor Yellow
    if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
    if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
}

# Check Python environment
$PythonExe = ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python environment not found at $PythonExe"
    exit 1
}

# Check PyInstaller
try {
    & $PythonExe -c "import PyInstaller; print('PyInstaller:', PyInstaller.__version__)"
} catch {
    Write-Error "PyInstaller not installed. Run: $PythonExe -m pip install pyinstaller"
    exit 1
}

# Build with PyInstaller (ONEDIR mode)
Write-Host ""
Write-Host "Building with PyInstaller (ONEDIR mode)..." -ForegroundColor Green
$StartTime = Get-Date

$PyInstallerArgs = @(
    "--clean",
    "--noconfirm",
    "samaktha.spec"
)

$Result = & $PythonExe -m PyInstaller @PyInstallerArgs 2>&1

$EndTime = Get-Date
$Duration = $EndTime - $StartTime

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed with exit code $LASTEXITCODE"
    Write-Host $Result
    exit 1
}

# Verify artifact
$ExePath = "dist\samaktha\samaktha.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "Executable not found at $ExePath"
    exit 1
}

# Get artifact info
$ExeSize = (Get-Item $ExePath).Length
$TotalSize = (Get-ChildItem "dist\samaktha" -Recurse | Measure-Object -Property Length -Sum).Sum

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Build Successful!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Executable: $ExePath"
Write-Host ("EXE Size:   {0:N2} MB" -f ($ExeSize / 1MB))
Write-Host ("Total Size: {0:N2} MB" -f ($TotalSize / 1MB))
Write-Host "Version:    $AppVersion"
Write-Host ("Build Time: $($Duration.TotalSeconds.ToString('F1')) seconds")
Write-Host "Signed:     No (unsigned build)"
Write-Host ""

# Quick smoke test
Write-Host "Running smoke test..." -ForegroundColor Yellow
$TestResult = & $ExePath --version
Write-Host "Version check: $TestResult"

$TestResult = & $ExePath bootstrap --status 2>&1
if ($TestResult -match "mode: installed") {
    Write-Host "Bootstrap status: PASS (installed mode detected)" -ForegroundColor Green
} else {
    Write-Host "Bootstrap status: FAIL" -ForegroundColor Red
    Write-Host $TestResult
}

Write-Host ""
Write-Host "Build completed successfully." -ForegroundColor Green
