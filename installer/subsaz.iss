; SubSaz (ساب‌ساز) — Inno Setup script. Produces SubSaz-Setup-x.y.z.exe
; Requires: Inno Setup 6 (https://jrsoftware.org/isinfo.php)
; Build first: pyinstaller subsaz-gui.spec  -> dist\SubSaz\
#define MyAppName "SubSaz"
#define MyAppVersion "0.0.3"
#define MyAppPublisher "SubSaz"
#define MyAppExeName "SubSaz.exe"

[Setup]
AppId={{8E4B1B2A-4C6F-4E9B-9E2A-7F1C3D5A9B01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=SubSaz-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; main app (PyInstaller onedir output)
Source: "..\dist\SubSaz\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
; portable ffmpeg (optional — copy ffmpeg.exe/ffprobe.exe next to the .iss
; build or into assets\bin before PyInstaller; picked up automatically)
Source: "..\assets\bin\ffmpeg.exe"; DestDir: "{app}\assets\bin"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\assets\bin\ffprobe.exe"; DestDir: "{app}\assets\bin"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
