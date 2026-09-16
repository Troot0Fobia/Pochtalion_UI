<#
.SYNOPSIS
    Windows build. Run on a Windows machine (your build VM) with `uv`
    installed and on PATH.

.DESCRIPTION
    Produces, under dist\:
        Pochtalion\                                        the onedir tree
        Pochtalion-<version>-windows-x86_64.zip             release archive
        Pochtalion-<version>-windows-x86_64.zip.sha256       its sha256
    and, if Inno Setup's iscc.exe is on PATH:
        Pochtalion-<version>-windows-setup.exe               installer
        Pochtalion-<version>-windows-setup.exe.sha256        its sha256

    Set $env:POCHTALION_UPDATE_REPO = "owner/repo" before running this to
    enable the built binary's self-update checks (see build/README.md,
    "Enabling self-update checks") - unset means it's compiled out. No
    container is involved on Windows, so the child pyinstaller.exe process
    inherits it automatically; nothing else to configure here.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

$PythonVersion = (Get-Content "build\PYTHON_VERSION").Trim()
$Version = (Get-Content "VERSION").Trim()
if (-not $Version) { throw "VERSION file is empty" }

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
    -r requirements\windows.txt -r requirements\build-windows.txt

# --- build --------------------------------------------------------------
& "$Venv\Scripts\pyinstaller.exe" build\pochtalion.spec `
    --distpath $Dist --workpath $Work --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed (exit $LASTEXITCODE)" }

# --- smoke test -----------------------------------------------------
# Running the exe this soon after PyInstaller writes it can race something
# on the machine briefly locking the freshly created (unsigned) binary -
# confirmed even with Windows Defender fully disabled, so it's not
# necessarily Defender specifically (another AV/EDR, or a background
# Windows scan, can do the same thing). Symptom: PermissionError deep in
# the bootloader's own self-read of Pochtalion.exe. It has cleared within
# well under a minute every time seen so far - a plain double-click of the
# exe a bit later always worked - so retry patiently, but only for this
# exact known symptom; anything else fails fast instead of wasting the
# whole retry budget on a real bug.
Write-Host ">> selfcheck"
$Exe = "$Dist\Pochtalion\Pochtalion.exe"
$MaxAttempts = 10
$RetryDelaySeconds = 3
for ($Attempt = 1; $Attempt -le $MaxAttempts; $Attempt++) {
    $Output = & $Exe --selfcheck 2>&1
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -eq 0) { break }

    $OutputText = $Output -join "`n"
    $IsKnownFileLockFlake = $OutputText -match "PermissionError" -and $OutputText -match [regex]::Escape($Exe)
    if (-not $IsKnownFileLockFlake -or $Attempt -eq $MaxAttempts) {
        Write-Host $OutputText
        throw "selfcheck failed (exit $ExitCode) after $Attempt attempt(s)"
    }
    Write-Host ">> selfcheck hit the known file-lock flake (exit $ExitCode), retrying in ${RetryDelaySeconds}s (attempt $Attempt/$MaxAttempts)..."
    Start-Sleep -Seconds $RetryDelaySeconds
}

# --- package ---------------------------------------------------------
Write-Host ">> packaging"
Compress-Archive -Path "$Dist\Pochtalion" -DestinationPath "$Dist\$Archive" -CompressionLevel Optimal

Push-Location $Dist
$ArchiveSha = "$Archive.sha256"
(Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower() + "  " + $Archive | Out-File -Encoding ascii -FilePath $ArchiveSha
Get-Content $ArchiveSha | Write-Host
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
    "{0}  {1}" -f (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower(), $installer | Out-File -Encoding ascii -FilePath "$installer.sha256"
    Pop-Location
    Write-Host ">> done: dist\$installer"
} else {
    Write-Host ">> Inno Setup (iscc.exe) not on PATH - skipping the installer, zip only."
    Write-Host "   See 'Installing Inno Setup' in build/README.md."
}
