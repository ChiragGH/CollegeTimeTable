; Inno Setup Script for College Timetable System
; Download Inno Setup from: https://jrsoftware.org/isdl.php
; To build: Right-click this file and select "Compile", or run: ISCC.exe installer.iss

#define MyAppName "College Timetable System by CRG"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "CRG"
#define MyAppCopyright "Copyright (C) 2026 CRG. All Rights Reserved."
#define MyAppExeName "CollegeTimetable.exe"

[Setup]
AppId={{C8E11D34-9A4B-4E5F-889B-2E0F45A3C8B7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright={#MyAppCopyright}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=CollegeTimetable_CRG_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\CollegeTimetable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
