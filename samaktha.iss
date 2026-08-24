; Samaktha Windows Installer Script
; Compile with Inno Setup 6+
; Per-user installation to %LOCALAPPDATA%\Programs\Samaktha

#define AppName "Samaktha"
#define AppVersion "0.5.0"
#define AppPublisher "Samaktha Project"
#define AppURL "https://github.com/HARI9037/Samaktha"
#define AppExeName "samaktha.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\Samaktha
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=samaktha-{#AppVersion}-windows
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}
CreateAppDir=yes
DisableDirPage=no
DisableProgramGroupPage=yes

; Architecture
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

; Languages
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main executable and all dependencies
Source: "dist\samaktha\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Exclude unnecessary files
; (PyInstaller ONEDIR already excludes .pyc, __pycache__, etc.)

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Optional: Launch application after install
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Preserve user data by default - do NOT delete these directories
; Type: filesandordirs; Name: "{localappdata}\Samaktha"

[Registry]
; Register uninstall information
Root: HKCU; Subkey: "Software\{#AppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#AppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekey

[Code]
function InitializeSetup(): Boolean;
begin
  // Check if already installed and offer upgrade
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    // Post-install actions if needed
  end;
end;
