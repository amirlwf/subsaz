; SubSaz (ساب‌ساز) — Inno Setup script. Produces SubSaz-Setup-x.y.z.exe
; Requires: Inno Setup 6.5.0+ (PNG wizard images; PNG transparency needs 6.6+)
;          https://jrsoftware.org/isinfo.php
; Build first: pyinstaller subsaz-gui.spec  -> dist\SubSaz\
#define MyAppName "SubSaz"
#define MyAppVersion "0.0.6"
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
; main app (PyInstaller onedir output) — ffmpeg/ffprobe are already inside
; _internal\assets\bin via the spec, do NOT ship a second copy
Source: "..\dist\SubSaz\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs; \
  Excludes: gui_started.log
; WebView2/TypeScript UI — own folder so its _internal never collides
Source: "..\dist\SubSaz-Web\*"; DestDir: "{app}\web"; \
  Flags: ignoreversion recursesubdirs; \
  Excludes: web_started.log

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\SubSaz Web"; Filename: "{app}\web\SubSaz-Web.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
