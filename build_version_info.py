"""Generate PyInstaller's Windows VERSIONINFO resource from version.py."""

from __future__ import annotations
from pathlib import Path

from version import APP_VERSION

parts = [int(value) for value in APP_VERSION.split(".")]
if len(parts) != 3 or any(value < 0 or value > 65535 for value in parts):
    raise SystemExit(f"Unsupported Windows file version: {APP_VERSION}")
file_version = tuple(parts + [0])
version_text = ".".join(str(value) for value in file_version)

resource = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={file_version},
    prodvers={file_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Gasbyn'),
          StringStruct('FileDescription', 'AI Video Clipper for Windows'),
          StringStruct('FileVersion', '{version_text}'),
          StringStruct('InternalName', 'GasbynClipper'),
          StringStruct('LegalCopyright', 'Copyright (C) 2026 Gasbyn'),
          StringStruct('OriginalFilename', 'GasbynClipper.exe'),
          StringStruct('ProductName', 'Gasbyn Clipper'),
          StringStruct('ProductVersion', '{version_text}'),
          StringStruct('Comments', 'Official Gasbyn Clipper application')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

output = Path("build") / "version_info.txt"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(resource, encoding="utf-8")
print(f"Generated Windows version resource for Gasbyn Clipper {version_text}: {output}")
