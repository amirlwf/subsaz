; SubSaz (ساب‌ساز) — Inno Setup script. Produces SubSaz-Setup-x.y.z.exe
; Requires: Inno Setup 6.5.0+ (PNG wizard images; PNG transparency needs 6.6+)
;          https://jrsoftware.org/isinfo.php
; Build first: pyinstaller subsaz-web.spec  -> dist\SubSaz\
#define MyAppName "SubSaz"
#define MyAppVersion "0.0.7"
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
; branding: logo/ is the source, tools/make_brand_assets.py regenerates these
SetupIconFile=..\assets\icon.ico
WizardImageFile=images\wizard-image.png
WizardSmallImageFile=images\wizard-small.png
WizardImageBackColor=clBlack

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; the app (PyInstaller onedir output): WebView2/TypeScript UI; ffmpeg/ffprobe
; are already inside _internal\assets\bin via the spec, do NOT ship a copy
Source: "..\dist\SubSaz\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs; \
  Excludes: *_started.log

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
