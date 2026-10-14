"""DWG conversion via a legitimate installed converter -- never by renaming.

The demo machine is probed for the ODA File Converter (the standard free
DXF->DWG tool). When it is absent, the API returns the structured error code
``dwg_converter_unavailable`` naming the exact dependency; a DXF is NEVER
renamed or served as a DWG.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REQUIRED_DEPENDENCY = (
    "ODA File Converter (free download from opendesign.com) -- install it and "
    "ensure ODAFileConverter.exe is on PATH or in Program Files/ODA"
)

_CANDIDATE_NAMES = ("ODAFileConverter", "ODAFileConverter.exe", "TeighaFileConverter.exe")
_CANDIDATE_DIRS = (
    Path("C:/Program Files/ODA"),
    Path("C:/Program Files (x86)/ODA"),
)


class DwgUnavailable(Exception):
    pass


class DwgConversionFailed(Exception):
    pass


def find_converter() -> Path | None:
    for name in _CANDIDATE_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    for base in _CANDIDATE_DIRS:
        if base.is_dir():
            for exe in base.rglob("ODAFileConverter.exe"):
                return exe
    return None


def convert_dxf_to_dwg(dxf_path: Path, out_dir: Path) -> Path:
    """Convert with a fixed argument list (no shell). Verifies the output is a
    real DWG by its binary signature."""
    converter = find_converter()
    if converter is None:
        raise DwgUnavailable(REQUIRED_DEPENDENCY)

    out_dir.mkdir(parents=True, exist_ok=True)
    # ODA File Converter CLI: input dir, output dir, version, type, recurse, audit, filter
    arguments = [
        str(converter),
        str(dxf_path.parent),
        str(out_dir),
        "ACAD2018",
        "DWG",
        "0",
        "1",
        dxf_path.name,
    ]
    completed = subprocess.run(arguments, capture_output=True, timeout=120, shell=False)
    produced = out_dir / (dxf_path.stem + ".dwg")
    if completed.returncode != 0 or not produced.exists():
        raise DwgConversionFailed("the DWG converter did not produce an output file")
    header = produced.read_bytes()[:6]
    # Real DWG files start with the version signature b"AC10.." (e.g. AC1032).
    if not header.startswith(b"AC10"):
        produced.unlink(missing_ok=True)
        raise DwgConversionFailed("the converter output failed DWG signature verification")
    return produced
