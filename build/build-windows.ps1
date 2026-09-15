<#
.SYNOPSIS
    Windows build. Run on a Windows machine (your build VM) with `uv`
    installed and on PATH.

.DESCRIPTION
    Produces, under dist\:
        Pochtalion\                                 the onedir tree
        Pochtalion-<version>-windows-x86_64.zip      release archive
        SHA256SUMS
    and, if Inno Setup's iscc.exe is on PATH:
        Pochtalion-<version>-windows-setup.exe       installer
#>

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

$PythonVersion = (Get-Content "build\PYTHON_VERSION").Trim()
$VersionMatch = Select-String -Path "config.py" -Pattern '^__version__\s*=\s*"([^"]+)"'
if (-not $VersionMatch) { throw "could not read __version__ from config.py" }
$Version = $VersionMatch.Matches[0].Groups[1].Value

$env:UV_LINK_MODE = "copy"

$Venv = if ($env:POCHTALION_BUILD_VENV) { $env:POCHTALION_BUILD_VENV } else { Join-Path $env:TEMP "pochtalion-build-venv" }
$Work = if ($env:POCHTALION_BUILD_WORK) { $env:POCHTALION_BUILD_WORK } else { Join-Path $env:TEMP "pochtalion-pyi-work" }
$Dist = Join-Path $RepoRoot "dist"
$Archive = "Pochtalion-$Version-windows-x86_64.zip"

Write-Host ">> version=$Version python=$PythonVersion"

foreach ($p in @($Venv, $Work, $Dist)) {
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}

# --- provision the exact, hash-verified toolchain ---------------------------
uv venv --python $PythonVersion $Venv
uv pip install --python $Venv --require-hashes `
    -r requirements-windows.txt -r requirements-build-windows.txt

# --- build --------------------------------------------------------------
& "$Venv\Scripts\pyinstaller.exe" build\pochtalion.spec `
    --distpath $Dist --workpath $Work --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed (exit $LASTEXITCODE)" }

# --- smoke test -----------------------------------------------------
Write-Host ">> selfcheck"
& "$Dist\Pochtalion\Pochtalion.exe" --selfcheck
if ($LASTEXITCODE -ne 0) { throw "selfcheck failed (exit $LASTEXITCODE)" }

# --- package ---------------------------------------------------------
Write-Host ">> packaging"
Compress-Archive -Path "$Dist\Pochtalion" -DestinationPath "$Dist\$Archive" -CompressionLevel Optimal

Push-Location $Dist
(Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower() + "  " + $Archive | Out-File -Encoding ascii -FilePath "SHA256SUMS"
Get-Content "SHA256SUMS" | Write-Host
Pop-Location

Write-Host ">> done: dist\$Archive"

# --- installer (optional - only if Inno Setup is installed) --------------
$Iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
if ($Iscc) {
    Write-Host ">> building installer (Inno Setup)"
    $env:POCHTALION_VERSION = $Version
    & $Iscc.Path "build\installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "iscc failed (exit $LASTEXITCODE)" }
    Push-Location $Dist
    $installer = "Pochtalion-$Version-windows-setup.exe"
    "{0}  {1}" -f (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower(), $installer | Add-Content -Encoding ascii "SHA256SUMS"
    Pop-Location
    Write-Host ">> done: dist\$installer"
} else {
    Write-Host ">> Inno Setup (iscc.exe) not on PATH - skipping the installer, zip only."
    Write-Host "   See 'Installing Inno Setup' in build/README.md."
}
