"""Nastaví verzi podle tagu při buildu: python set_version.py v1.2.3"""

import re
import sys
from pathlib import Path

tag = sys.argv[1].strip()
version = tag.lstrip("vV")
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    sys.exit(f"Neplatná verze: {tag}")

Path("version.py").write_text(
    '"""Verze aplikace. Přepsáno při buildu z tagu."""\n\n'
    f'APP_VERSION = "{version}"\n'
    'GITHUB_REPO = "Gasbyn/Gasbyn-Clipper"\n',
    encoding="utf-8",
)
iss = Path("installer.iss")
text = iss.read_text(encoding="utf-8")
text = re.sub(r'#define AppVersion ".*"', f'#define AppVersion "{version}"', text)
iss.write_text(text, encoding="utf-8")
print(f"Verze nastavena na {version}")
