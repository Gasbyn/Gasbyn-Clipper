; Inno Setup skript: vytvoří Setup.exe z adresáře dist\GasbynClipper

[Setup]
AppName=Gasbyn Clipper
AppVersion={#AppVersion}
DefaultDirName={autopf}\GasbynClipper
DefaultGroupName=Gasbyn Clipper
OutputDir=installer
OutputBaseFilename=Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Files]
Source: "dist\GasbynClipper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Gasbyn Clipper"; Filename: "{cmd}"; Parameters: "/k ""{app}\GasbynClipper.exe"" --check"; WorkingDir: "{app}"
Name: "{group}\Odinstalovat Gasbyn Clipper"; Filename: "{uninstallexe}"
