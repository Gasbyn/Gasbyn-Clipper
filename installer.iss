; Inno Setup skript - vytvoří Setup.exe z složky dist\GasbynClipper
; Instalace je jen pro aktuálního uživatele (není potřeba správce), funguje na Windows 10 i 11.

#define AppName "Gasbyn Clipper"
#define AppVersion "1.1.0"

[Setup]
AppId={{B7C2D1E4-5A3F-4C8B-9D6E-1F2A3B4C5D6E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Gasbyn
VersionInfoCompany=Gasbyn
VersionInfoDescription=Gasbyn Clipper Setup
VersionInfoProductName=Gasbyn Clipper
VersionInfoVersion={#AppVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCopyright=Copyright (C) 2026 Gasbyn
VersionInfoOriginalFileName=GasbynClipper-Setup.exe
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\GasbynClipper.exe

[Tasks]
Name: "desktopicon"; Description: "Vytvořit zástupce na ploše"; Flags: unchecked

[Files]
Source: "dist\GasbynClipper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\GasbynClipper.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\GasbynClipper.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\GasbynClipper.exe"; WorkingDir: "{app}"; Description: "Spustit Gasbyn Clipper"; Flags: nowait postinstall skipifsilent
