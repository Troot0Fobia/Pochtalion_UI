# Detached self-update helper (Windows). Bundled into _internal\scripts\ by
# pochtalion.spec; modules.update_apply copies it out to a scratch dir
# (independent of anything this script is about to touch) before launching
# it detached, right before the app process exits.
#
# Usage:
#   apply_update.ps1 -Form directory -TargetPid <pid> -InstallDir <dir> -NewBuildDir <dir> -ExePath <path>
#   apply_update.ps1 -Form windows-installer -TargetPid <pid> -InstallerPath <path> -ExePath <path>
#
# "directory" replaces only the app's own files (Pochtalion.exe + _internal\)
# inside InstallDir - never the whole directory - so a portable data\ folder,
# or a POCHTALION_DATA_DIR that happens to live inside or alongside
# InstallDir, survives untouched. This fixed pair must match
# modules.update_apply.APP_OWNED_NAMES; modules.update_apply already refused
# to get here at all if POCHTALION_DATA_DIR collided with either name, so
# this script never has to re-check that itself.
#
# installer.iss's own post-install launch is skipped under /VERYSILENT
# (Flags: ... skipifsilent), so ExePath is always relaunched explicitly here
# for both forms.

param(
    [Parameter(Mandatory)] [ValidateSet("directory", "windows-installer")] [string]$Form,
    [Parameter(Mandatory)] [int]$TargetPid,
    [string]$InstallDir,
    [string]$NewBuildDir,
    [string]$InstallerPath,
    [Parameter(Mandatory)] [string]$ExePath
)

$ErrorActionPreference = "Stop"

# modules.update_apply redirects this process's own stdout/stderr to
# helper_output.log under UPDATES, which is where these Write-Host lines end
# up - kept short and few, just enough to tell what stage a failed apply got
# stuck at.
try {
    Write-Host "apply_update.ps1 starting: Form=$Form TargetPid=$TargetPid"

    while (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) {
        Start-Sleep -Milliseconds 200
    }

    switch ($Form) {
        "directory" {
            Remove-Item -Recurse -Force (Join-Path $InstallDir "_internal")
            Remove-Item -Force (Join-Path $InstallDir "Pochtalion.exe")
            Move-Item (Join-Path $NewBuildDir "_internal") (Join-Path $InstallDir "_internal")
            Move-Item (Join-Path $NewBuildDir "Pochtalion.exe") (Join-Path $InstallDir "Pochtalion.exe")
            Remove-Item -Recurse -Force (Split-Path $NewBuildDir -Parent) -ErrorAction SilentlyContinue
        }
        "windows-installer" {
            # /SILENT (not /VERYSILENT): still no wizard pages or dialogs to
            # interact with, but shows the installation progress window - the
            # only feedback the user has that an update is actually running
            # and the app isn't just stuck/safe to relaunch manually during
            # the several seconds this takes to copy everything into place.
            Start-Process -FilePath $InstallerPath -ArgumentList "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
            Remove-Item -Force $InstallerPath -ErrorAction SilentlyContinue
        }
    }
    Start-Process -FilePath $ExePath
    Write-Host "apply ($Form) done, relaunched $ExePath"
} catch {
    Write-Host "FAILED: $_"
    throw
}

Remove-Item -Force $PSCommandPath
