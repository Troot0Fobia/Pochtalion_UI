; Pochtalion Windows installer (Inno Setup).
;
; Compile with a pinned, checksum-verified Inno Setup install (see
; "Installing Inno Setup" in build/README.md):
;
;   iscc build\installer.iss
;
; build\build-windows.ps1 runs this automatically as its last step if
; iscc.exe is on PATH, after setting POCHTALION_VERSION from the VERSION
; file and producing dist\Pochtalion\ (the onedir tree this packages).
;
; Not code-signed (see build/README.md - cost). Windows SmartScreen will
; warn on first run until that changes.

#define MyAppName "Pochtalion"
#define MyAppPublisher "Troot0Fobia"
#define MyAppExeName "Pochtalion.exe"
#define MyAppVersion GetEnv("POCHTALION_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; Fixed forever once released - Inno Setup uses this (not the app name) to
; recognize "this is an upgrade of the same app" across versions. Generated
; once with Python's uuid.uuid4(); do not regenerate.
AppId={{7C54F1CC-8641-4508-8998-F6E8D086A5FE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install, no admin/UAC prompt - same reasoning VS Code/Discord/Slack
; use this layout for: a self-updater running as the logged-in user can freely
; rewrite {localappdata}\Programs\Pochtalion, but could never touch Program
; Files without elevating on every single update. PrivilegesRequiredOverrides
; still lets someone launch the installer "as administrator" and get a
; per-machine install instead, if they really want one.
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; SourceDir is relative to this .iss file, i.e. build\ - so ..\dist\Pochtalion
SourceDir=.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\Pochtalion\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
